"""Letras de canciones vía Genius, con limpieza del texto.

lyricsgenius es una dependencia *opcional*: si falta o está rota, el bot
arranca igual y solo se desactiva el comando de letras.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from mango.services.texto import limpiar_titulo

log = logging.getLogger(__name__)

try:  # dependencia opcional: no debe tumbar el bot
    import lyricsgenius
except Exception:  # ImportError o fallo interno de la librería
    lyricsgenius = None  # type: ignore[assignment]
    log.warning("lyricsgenius no está disponible: !lyrics quedará desactivado")

SEARCH_TIMEOUT = 20
_EMBED_SUFFIX = re.compile(r"\d*\s*Embed\s*$")


# Separadores «Artista - Canción» / «Canción — Artista» / «A | B»
_SEPARADORES = re.compile(r"\s+[\u2013\u2014-]\s+|\s*\|\s*|\s*//\s*")


def candidatos(texto: str) -> list[tuple[str, str]]:
    """Posibles pares ``(título, artista)`` a partir de un título sucio.

    Cubre los dos formatos habituales:
      · YouTube:  «Artista - Canción (Official Video)»
      · Spotify:  «Canción — Artista»
    Se devuelven en orden de probabilidad para probarlos en Genius.
    """
    limpio = limpiar_titulo(texto or "")
    if not limpio:
        return []

    partes = [parte.strip(" -–—|:,") for parte in _SEPARADORES.split(limpio, maxsplit=1)]
    partes = [parte for parte in partes if parte]

    salida: list[tuple[str, str]] = []
    if len(partes) == 2:
        izquierda, derecha = partes
        salida.append((derecha, izquierda))   # YouTube: artista primero
        salida.append((izquierda, derecha))   # Spotify: canción primero
    salida.append((limpio, ""))

    vistos: set[tuple[str, str]] = set()
    unicos: list[tuple[str, str]] = []
    for par in salida:
        if par not in vistos and par[0]:
            vistos.add(par)
            unicos.append(par)
    return unicos


class LyricsError(RuntimeError):
    """Fallo al consultar Genius."""


class LyricsService:
    """Buscador de letras asíncrono.

    Acepta un *access token* directamente (``GENIUS_TOKEN``) o, si no hay,
    obtiene uno con el flujo OAuth ``client_credentials`` a partir de
    ``GENIUS_CLIENT_ID`` y ``GENIUS_CLIENT_SECRET``.
    """

    def __init__(
        self,
        token: str = "",
        *,
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self._token = (token or "").strip()
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._genius: Any = None
        self._lock = asyncio.Lock()
        self._mode = "token" if self._token else "OAuth"
        # Caché: Genius tarda 3-6 s y la misma canción se pide a menudo.
        self._cache: dict[str, tuple[float, tuple[str, str] | None]] = {}
        self._cache_ttl = 3600.0

    @property
    def enabled(self) -> bool:
        if lyricsgenius is None:
            return False
        return bool(self._token or (self._client_id and self._client_secret))

    @property
    def label(self) -> str:
        return f"Genius · {self._mode}"

    # ---------------------------------------------------------
    # Cliente perezoso
    # ---------------------------------------------------------
    async def _ensure_client(self) -> Any:
        if self._genius is not None:
            return self._genius
        if lyricsgenius is None:
            raise LyricsError("lyricsgenius no está instalado.")

        async with self._lock:
            if self._genius is not None:
                return self._genius

            token = self._token
            if not token:
                token = await self._fetch_access_token()
                self._token = token

            self._genius = lyricsgenius.Genius(
                token,
                timeout=10,
                retries=2,
                remove_section_headers=True,
                skip_non_songs=True,
                excluded_terms=["(Remix)", "(Live)", "(Edit)", "(Cover)"],
            )
        return self._genius

    async def _fetch_access_token(self) -> str:
        """Pide un token temporal con client_credentials."""
        if not (self._client_id and self._client_secret):
            raise LyricsError(
                "Falta GENIUS_TOKEN o las credenciales "
                "GENIUS_CLIENT_ID / GENIUS_CLIENT_SECRET en el .env."
            )

        import aiohttp

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            async with aiohttp.ClientSession() as session, session.post(
                "https://api.genius.com/oauth/token", data=payload, timeout=20
            ) as response:
                data = await response.json(content_type=None)
                if response.status != 200 or "access_token" not in data:
                    raise LyricsError(
                        f"Genius rechazó las credenciales ({response.status})."
                    )
                return str(data["access_token"])
        except aiohttp.ClientError as exc:
            raise LyricsError("No pude obtener el token de Genius.") from exc

    # ---------------------------------------------------------
    # Búsqueda
    # ---------------------------------------------------------
    async def fetch(self, query: str) -> tuple[str, str] | None:
        """Devuelve ``(título, letra)`` o ``None`` si no hay resultados.

        Se prueban varias formas del título: así «Artista - Canción (Official
        Music Video) [HD UPGRADE]» (el título del vídeo de YouTube) también
        encuentra la letra sin que el usuario tenga que afinarlo a mano.
        """
        client = await self._ensure_client()

        clave = " ".join((query or "").lower().split())
        guardado = self._cache.get(clave)
        if guardado is not None and time.monotonic() - guardado[0] < self._cache_ttl:
            log.debug("Letra en caché para %r", query)
            return guardado[1]

        intentos = candidatos(query)
        if not intentos:
            return None

        for titulo, artista in intentos:
            try:
                song = await asyncio.wait_for(
                    asyncio.to_thread(client.search_song, titulo, artista),
                    timeout=SEARCH_TIMEOUT,
                )
            except TimeoutError as exc:
                raise LyricsError(
                    "Genius tardó demasiado en responder. Inténtalo de nuevo."
                ) from exc
            except Exception as exc:  # errores de red o de la API
                log.exception("Error consultando Genius para %r", (titulo, artista))
                raise LyricsError("No pude consultar Genius en este momento.") from exc

            if song is not None and song.lyrics:
                log.debug("Letra encontrada con (%r, %r)", titulo, artista)
                resultado = ((song.title or titulo), self._clean(song.lyrics))
                self._cache[clave] = (time.monotonic(), resultado)
                return resultado
            log.debug("Genius no encontró (%r, %r); siguiente intento", titulo, artista)

        self._cache[clave] = (time.monotonic(), None)
        return None

    @staticmethod
    def _clean(lyrics: str) -> str:
        """Quita el ruido que añade Genius al final de cada letra."""
        text = lyrics.replace("You might also like", "").strip()
        text = _EMBED_SUFFIX.sub("", text).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def chunk(lyrics: str, size: int = 1800) -> list[str]:
        """Parte la letra en trozos que quepan en un embed."""
        if not lyrics:
            return []
        return [lyrics[i : i + size] for i in range(0, len(lyrics), size)]
