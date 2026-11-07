"""Búsquedas, playlists y streams de audio vía yt-dlp.

Todo se ejecuta en hilos (``asyncio.to_thread``) para no bloquear el
event loop: antes, una playlist podía congelar el bot entero.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yt_dlp

from mango.services.texto import normalizar as _normalizar
from mango.state import Track

log = logging.getLogger(__name__)

# Dominios de confianza. Solo se descargan cosas de aquí: sin esta lista,
# una URL como `http://192.168.1.1/youtube.com` pasaría el filtro y el bot
# haría peticiones a la red interna (SSRF).
DOMINIOS_YOUTUBE = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})
DOMINIOS_SPOTIFY = frozenset({"spotify.com", "spotify.link"})


def _dominio_permitido(url: str, dominios: frozenset[str]) -> bool:
    """¿La URL es http(s) y su host pertenece a la lista? (estricto)"""
    try:
        partes = urlsplit((url or "").strip())
        host = (partes.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if partes.scheme not in {"http", "https"} or not host:
        return False
    return any(host == dominio or host.endswith("." + dominio) for dominio in dominios)


def parece_url(texto: str) -> bool:
    """¿El texto es un enlace (aunque no sea de YouTube ni Spotify)?"""
    try:
        partes = urlsplit((texto or "").strip())
    except ValueError:
        return False
    return bool(partes.scheme in {"http", "https", "ftp", "file"} and partes.netloc)


def es_url_youtube(url: str) -> bool:
    return _dominio_permitido(url, DOMINIOS_YOUTUBE)


def es_url_spotify(url: str) -> bool:
    return _dominio_permitido(url, DOMINIOS_SPOTIFY)


def normalizar_url(url: str) -> str:
    """Añade `https://` si falta y el dominio es de confianza."""
    limpia = (url or "").strip()
    if not limpia:
        return limpia
    if "://" not in limpia and _dominio_permitido(f"https://{limpia}", DOMINIOS_YOUTUBE):
        return f"https://{limpia}"
    return limpia

BASE_OPTIONS: dict[str, Any] = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "extractor_retries": 3,
    "socket_timeout": 15,
    "default_search": "ytsearch1",
    "skip_download": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
}

FLAT_OPTIONS: dict[str, Any] = {
    **BASE_OPTIONS,
    "extract_flat": "in_playlist",
    "noplaylist": False,
}

STREAM_CACHE_TTL = 1800      # 30 min (las URLs de YouTube caducan)
SEARCH_CACHE_TTL = 600       # 10 min
MAX_CACHED_SEARCHES = 200


class TrackResolutionError(RuntimeError):
    """No se pudo obtener un stream reproducible para una canción."""


# Palabras que suelen indicar que el vídeo NO es la canción que se busca
_MALAS = (
    "cover", "karaoke", "instrumental", "tutorial", "reaction", "mashup",
    "nightcore", "8d", "tiktok", "shorts", "parodia", "remix", "loop",
)
# Señales de buen resultado (audio oficial, canal de artista…)
_BUENAS = ("official", "oficial", "audio", "lyric", "letra", "hd")


# Contenido que NO es una canción (aunque esté en YouTube)
_NO_MUSICA = (
    "gameplay", "game play", "walkthrough", "trailer", "teaser", "review",
    "reaction", "tutorial", "how to", "como hacer", "podcast", "vlog",
    "news", "noticias", "prank", "meme", "unboxing", "documental",
    "documentary", "entrevista", "interview", "conferencia", "charla",
    "curso", "clase", "directo", "live stream", "full set", "dj set",
    "highlights", "resumen del partido", "speedrun", "montage", "fails",
    "compilation", "recopilacion", "asmr", "meditacion", "ruido blanco",
)
CATEGORIA_MUSICA = "music"


def es_musica(entry: dict[str, Any], consulta: str = "") -> bool:
    """¿El resultado es una canción y no un vídeo cualquiera?

    Se apoya en la categoría de YouTube (``Music``), los canales de artista
    (``- Topic``, VEVO), los metadatos musicales (track/artist) y la duración
    típica de una canción. Sirve tanto para búsquedas como para videos sueltos.
    """
    titulo = _normalizar(str(entry.get("title") or ""))
    canal = _normalizar(str(entry.get("channel") or entry.get("uploader") or ""))
    categoria = " ".join(str(c) for c in entry.get("categories") or []).lower()
    duracion = int(entry.get("duration") or 0)
    en_vivo = str(entry.get("live_status") or "")

    # Señales claras de que NO es una canción (salvo que se pidan)
    for palabra in _NO_MUSICA:
        limpia = _normalizar(palabra)
        if limpia in titulo and limpia not in consulta:
            return False

    if en_vivo in {"is_live", "is_upcoming"}:
        return False
    if duracion and not 45 <= duracion <= 900:
        return False

    if categoria:
        # YouTube dice la categoría: manda esa información
        return CATEGORIA_MUSICA in categoria

    # Sin categoría (resultados «planos»): pistas indirectas
    if "topic" in canal or "vevo" in canal:
        return True
    if entry.get("track") or entry.get("artist"):
        return True
    return " - " in str(entry.get("title") or "") and 45 <= duracion <= 900


def _puntuar(entry: dict[str, Any], tokens: set[str], consulta: str) -> float:
    """Cuánto se parece este resultado a lo pedido (más alto = mejor)."""
    titulo = _normalizar(str(entry.get("title") or ""))
    canal = _normalizar(str(entry.get("uploader") or entry.get("channel") or ""))
    puntaje = 0.0

    if tokens:
        encontradas = sum(1 for token in tokens if token in titulo)
        puntaje += encontradas * 2.0
        if encontradas == len(tokens):
            puntaje += 4.0

    if "topic" in canal or "vevo" in canal:
        puntaje += 2.5
    puntaje += sum(1.0 for palabra in _BUENAS if palabra in titulo)

    for mala in _MALAS:
        if mala in titulo and mala not in consulta:
            puntaje -= 4.0

    duracion = int(entry.get("duration") or 0)
    if duracion:
        if duracion < 45:
            puntaje -= 3.0     # clips / shorts
        elif duracion > 1800:
            puntaje -= 1.5     # mezclas de 30 min
        elif 60 <= duracion <= 600:
            puntaje += 1.0     # duración típica de canción

    if titulo:
        puntaje -= max(0.0, (len(titulo) - len(consulta)) * 0.02)
    return puntaje


def _variantes(query: str) -> list[str]:
    """Formulaciones a probar cuando una transcripción no da resultados.

    Primero la frase tal cual; después se quitan palabras por delante, porque
    Whisper suele estropear el nombre del artista y no el del título
    («Dazpump get lucky» → «get lucky»).
    """
    limpia = " ".join(query.split())
    palabras = limpia.split()
    intentos = [limpia]
    if len(palabras) >= 3:
        intentos.append(" ".join(palabras[-2:]))
    if len(palabras) >= 4:
        intentos.append(" ".join(palabras[-3:]))
    if len(palabras) >= 2:
        intentos.append(" ".join(palabras[1:]))

    vistos: set[str] = set()
    unicos: list[str] = []
    for intento in intentos:
        clave = intento.lower()
        if intento and clave not in vistos:
            vistos.add(clave)
            unicos.append(intento)
    return unicos


class YTDLPService:
    """Envoltorio asíncrono de yt-dlp con caché de búsquedas y streams."""

    def __init__(self, *, cookies_file: Path | None = None) -> None:
        self._base = dict(BASE_OPTIONS)
        self._flat = dict(FLAT_OPTIONS)
        if cookies_file is not None:
            self._base["cookiefile"] = str(cookies_file)
            self._flat["cookiefile"] = str(cookies_file)

        self._stream_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}
        self._search_cache: dict[str, tuple[float, Track]] = {}

    # ---------------------------------------------------------
    # Utilidades
    # ---------------------------------------------------------
    @staticmethod
    def is_youtube_url(url: str) -> bool:
        return es_url_youtube(normalizar_url(url))

    @staticmethod
    def is_playlist_url(url: str) -> bool:
        limpia = normalizar_url(url)
        if not es_url_youtube(limpia):
            return False
        try:
            partes = urlsplit(limpia)
        except ValueError:
            return False
        return bool(parse_qs(partes.query).get("list"))

    async def _extract(self, target: str, options: dict[str, Any]) -> dict[str, Any] | None:
        def run() -> dict[str, Any] | None:
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(target, download=False)

        return await asyncio.to_thread(run)

    @staticmethod
    def _first_entry(info: dict[str, Any] | None) -> dict[str, Any] | None:
        if not info:
            return None
        entries = info.get("entries")
        if entries:
            for entry in entries:
                if entry and (entry.get("url") or entry.get("webpage_url")):
                    return entry
            return None
        return info

    @staticmethod
    def _track_from_entry(
        entry: dict[str, Any],
        *,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> Track:
        url = entry.get("webpage_url") or entry.get("url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"

        thumbnail = entry.get("thumbnail")
        if not thumbnail:
            thumbnails = entry.get("thumbnails") or []
            if thumbnails:
                thumbnail = thumbnails[-1].get("url")

        return Track(
            title=entry.get("title") or "Sin título",
            url=url or None,
            duration=int(entry.get("duration") or 0),
            requester_id=requester_id,
            requester_name=requester_name,
            source="YouTube",
            thumbnail=thumbnail,
        )

    # ---------------------------------------------------------
    # Búsquedas y playlists
    # ---------------------------------------------------------
    async def search(
        self,
        query: str,
        *,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> Track | None:
        """Busca en YouTube y devuelve **la mejor** coincidencia (no la primera).

        Pide 5 resultados, los puntúa (coincidencia de palabras, canal oficial,
        duración, penalizando covers/karaoke/shorts) y resuelve solo el ganador.
        Así «tren al sur» encuentra la canción aunque no se diga el artista.
        """
        key = query.strip().lower()
        cached = self._search_cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < SEARCH_CACHE_TTL:
            track = cached[1]
            track.requester_id = requester_id
            track.requester_name = requester_name
            return track

        consulta = _normalizar(query)
        tokens = {token for token in consulta.split() if len(token) > 1}

        # 1) se prueban varias formulaciones: la dicha y, si falla, variantes
        #    (una transcripción mala devuelve 0 resultados; «Dazpump get lucky»
        #    → «get lucky» sí encuentra la canción).
        for intento in _variantes(query):
            track, habia = await self._buscar_una(
                intento,
                tokens=tokens,
                consulta=consulta,
                requester_id=requester_id,
                requester_name=requester_name,
            )
            if track is not None:
                log.info("Búsqueda %r → %r", query, track.title)
                if len(self._search_cache) >= MAX_CACHED_SEARCHES:
                    self._search_cache.clear()
                self._search_cache[key] = (now, track)
                return track
            # Con resultados pero nada que sea música, insistir solo daría
            # canciones equivocadas: se corta aquí.
            if habia:
                break
            if intento != query:
                log.info("Sin resultados para %r; probando otra formulación", intento)

        log.info("Sin resultados de música para %r", query)
        return None

    async def _buscar_una(
        self,
        consulta_busqueda: str,
        *,
        tokens: set[str],
        consulta: str,
        requester_id: int,
        requester_name: str,
    ) -> tuple[Track | None, bool]:
        """Una pasada: pide 5 candidatos, puntúa y devuelve (canción, ¿hubo resultados?)."""
        info = await self._extract(f"ytsearch5:{consulta_busqueda}", self._flat)
        entries = [entry for entry in (info or {}).get("entries") or [] if entry]
        if not entries:
            return None, False

        ordenados = sorted(
            entries, key=lambda entry: _puntuar(entry, tokens, consulta), reverse=True
        )

        for elegido in ordenados[:3]:
            url = str(elegido.get("webpage_url") or elegido.get("url") or "")
            if url and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"

            # Vía rápida: si con los datos de la búsqueda ya se ve que es música,
            # no se descarga el vídeo (el stream se resuelve al reproducir).
            entry = elegido
            if not es_musica(elegido, consulta):
                if not url:
                    continue
                try:
                    detalle = await self._extract(url, self._base)
                    entry = self._first_entry(detalle) or elegido
                except Exception:
                    log.debug("No pude resolver el detalle de %r", url, exc_info=True)
                if not es_musica(entry, consulta):
                    log.info(
                        "Descartado (no es música): %r · categoría=%s",
                        entry.get("title"),
                        entry.get("categories"),
                    )
                    continue

            track = self._track_from_entry(
                entry, requester_id=requester_id, requester_name=requester_name
            )
            if not track.url and url:
                track.url = url
            return track, True

        return None, True
        return None

    async def playlist(
        self,
        url: str,
        *,
        limit: int,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> list[Track]:
        """Lee una playlist de YouTube sin resolver cada vídeo (rápido)."""
        info = await self._extract(url, self._flat)
        if not info:
            return []

        tracks: list[Track] = []
        for entry in info.get("entries") or []:
            if len(tracks) >= limit:
                break
            if not entry:
                continue
            track = self._track_from_entry(
                entry, requester_id=requester_id, requester_name=requester_name
            )
            if track.url:
                tracks.append(track)
        log.info("Playlist de YouTube leída: %s temas", len(tracks))
        return tracks

    # ---------------------------------------------------------
    # Streams
    # ---------------------------------------------------------
    async def stream_url(
        self,
        *,
        webpage_url: str | None = None,
        search_query: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Devuelve ``(url_de_audio, metadatos)`` listo para FFmpeg."""
        target = webpage_url or (f"ytsearch1:{search_query}" if search_query else None)
        if not target:
            raise TrackResolutionError("La canción no tiene URL ni búsqueda asociada.")

        # Defensa en profundidad contra SSRF: solo se resuelven enlaces de
        # YouTube. Así, aunque otra parte del código fallara, yt-dlp nunca
        # acabaría pidiendo una URL interna (router, metadatos de nube, etc.).
        if webpage_url and parece_url(webpage_url) and not es_url_youtube(webpage_url):
            raise TrackResolutionError("Solo reproduzco enlaces de YouTube.")

        now = time.monotonic()
        if webpage_url:
            cached = self._stream_cache.get(webpage_url)
            if cached is not None and now - cached[0] < STREAM_CACHE_TTL:
                return cached[1], cached[2]

        info = await self._extract(target, self._base)
        entry = self._first_entry(info)
        if entry is None:
            raise TrackResolutionError(f"Sin resultados para {target!r}")

        stream = entry.get("url")
        if not stream:
            raise TrackResolutionError(f"'{target}' no tiene stream de audio utilizable.")
        if not stream.startswith("http"):
            raise TrackResolutionError("El stream obtenido no es una URL válida.")

        if webpage_url:
            if len(self._stream_cache) >= MAX_CACHED_SEARCHES:
                self._stream_cache.clear()
            self._stream_cache[webpage_url] = (now, stream, entry)

        return stream, entry
