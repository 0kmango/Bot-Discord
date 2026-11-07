"""Integración con Spotify.

Spotify no permite descargar audio, así que convertimos cada tema en una
búsqueda de YouTube ("artista + título + audio"). Toda la parte síncrona
de spotipy se ejecuta en un hilo para no bloquear el bot.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from mango.state import Track

log = logging.getLogger(__name__)

try:  # dependencia opcional: si falla, solo se desactiva Spotify
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
except Exception:  # pragma: no cover
    spotipy = None  # type: ignore[assignment]
    SpotifyClientCredentials = None  # type: ignore[assignment]
    log.warning("spotipy no está disponible: los links de Spotify quedarán desactivados")

SPOTIFY_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z\-]+/)?(?P<kind>track|playlist|album)/(?P<id>[A-Za-z0-9]+)"
)

API_TIMEOUT = 10
MAX_PAGES = 10


class SpotifyError(RuntimeError):
    """Fallo al leer datos de Spotify."""


class SpotifyService:
    """Cliente de Spotify con control de credenciales y concurrencia."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client: Any = None
        self._lock = asyncio.Lock()
        if spotipy is None or SpotifyClientCredentials is None:
            return
        if client_id and client_secret:
            credentials = SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
            self._client = spotipy.Spotify(
                auth_manager=credentials,
                requests_timeout=API_TIMEOUT,
                retries=2,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @staticmethod
    def parse(url: str) -> tuple[str, str] | None:
        """Devuelve ``(tipo, id)`` si la URL es de Spotify."""
        match = SPOTIFY_URL_RE.search(url)
        if match is None:
            return None
        return match.group("kind"), match.group("id")

    # ---------------------------------------------------------
    # Conversión
    # ---------------------------------------------------------
    @staticmethod
    def _to_track(
        item: dict,
        *,
        requester_id: int,
        requester_name: str,
    ) -> Track | None:
        if not item or not item.get("name"):
            return None
        artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
        name = item["name"]
        title = f"{name} — {artists}" if artists else name
        query = f"{name} {artists} audio" if artists else f"{name} audio"
        return Track(
            title=title,
            query=query,
            duration=int(item.get("duration_ms") or 0) // 1000,
            requester_id=requester_id,
            requester_name=requester_name,
            source="Spotify",
        )

    # ---------------------------------------------------------
    # Lectura de datos (síncrona, se llama en un hilo)
    # ---------------------------------------------------------
    def _fetch_track(self, track_id: str) -> dict:
        assert self._client is not None
        return self._client.track(track_id)

    def _fetch_playlist(self, playlist_id: str, limit: int) -> list[dict]:
        assert self._client is not None
        results = self._client.playlist_items(
            playlist_id, additional_types=("track",), limit=100
        )
        items: list[dict] = []
        pages = 0
        while results and len(items) < limit and pages < MAX_PAGES:
            for item in results.get("items") or []:
                track = (item or {}).get("track")
                if track:
                    items.append(track)
                if len(items) >= limit:
                    break
            if len(items) >= limit or not results.get("next"):
                break
            results = self._client.next(results)
            pages += 1
        return items

    def _fetch_album(self, album_id: str, limit: int) -> list[dict]:
        assert self._client is not None
        results = self._client.album_tracks(album_id, limit=50)
        items: list[dict] = []
        pages = 0
        while results and len(items) < limit and pages < MAX_PAGES:
            items.extend(results.get("items") or [])
            if len(items) >= limit or not results.get("next"):
                break
            results = self._client.next(results)
            pages += 1
        return items[:limit]

    # ---------------------------------------------------------
    # API pública asíncrona
    # ---------------------------------------------------------
    def _require_client(self) -> spotipy.Spotify:
        if self._client is None:
            raise SpotifyError(
                "Spotify no está configurado: faltan SPOTIFY_CLIENT_ID y "
                "SPOTIFY_CLIENT_SECRET en el archivo .env."
            )
        return self._client

    async def track(
        self,
        url: str,
        *,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> Track:
        parsed = self.parse(url)
        if parsed is None or parsed[0] != "track":
            raise SpotifyError("Ese enlace no parece un tema de Spotify.")
        self._require_client()

        async with self._lock:
            data = await asyncio.to_thread(self._fetch_track, parsed[1])

        track = self._to_track(
            data, requester_id=requester_id, requester_name=requester_name
        )
        if track is None:
            raise SpotifyError("Spotify no devolvió información del tema.")
        return track

    async def playlist(
        self,
        url: str,
        *,
        limit: int,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> list[Track]:
        parsed = self.parse(url)
        if parsed is None or parsed[0] != "playlist":
            raise SpotifyError("Ese enlace no parece una playlist de Spotify.")
        self._require_client()

        async with self._lock:
            items = await asyncio.to_thread(self._fetch_playlist, parsed[1], limit)

        tracks: list[Track] = []
        for item in items:
            track = self._to_track(
                item, requester_id=requester_id, requester_name=requester_name
            )
            if track is not None:
                tracks.append(track)
        log.info("Playlist de Spotify leída: %s temas", len(tracks))
        return tracks

    async def album(
        self,
        url: str,
        *,
        limit: int,
        requester_id: int = 0,
        requester_name: str = "",
    ) -> list[Track]:
        parsed = self.parse(url)
        if parsed is None or parsed[0] != "album":
            raise SpotifyError("Ese enlace no parece un álbum de Spotify.")
        self._require_client()

        async with self._lock:
            items = await asyncio.to_thread(self._fetch_album, parsed[1], limit)

        tracks: list[Track] = []
        for item in items:
            track = self._to_track(
                item, requester_id=requester_id, requester_name=requester_name
            )
            if track is not None:
                tracks.append(track)
        log.info("Álbum de Spotify leído: %s temas", len(tracks))
        return tracks
