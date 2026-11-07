"""Estado de reproducción y voz, aislado por servidor.

Cada guild tiene su propio :class:`GuildPlayer`, así que dos servidores
pueden escuchar música distinta al mismo tiempo sin pisarse.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import tempfile
from collections import deque
from dataclasses import dataclass

import discord

from mango import personality
from mango.services.audio import MixerSource
from mango.services.dave import is_disabled as dave_is_disabled
from mango.services.dave import restore as dave_restore
from mango.services.texto import titulo_normalizado

try:  # recepción de audio (necesario para la charla por voz)
    from discord.ext.voice_recv import VoiceRecvClient
except Exception:  # pragma: no cover
    VoiceRecvClient = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Opciones de FFmpeg para streaming: reconexión automática y sin vídeo.
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -bufsize 128k",
}

LOOP_LABELS = {
    "off": "desactivado",
    "track": "repetir canción",
    "queue": "repetir cola",
}

LOOP_ALIASES = {
    "off": "off",
    "none": "off",
    "no": "off",
    "desactivado": "off",
    "track": "track",
    "song": "track",
    "one": "track",
    "cancion": "track",
    "canción": "track",
    "queue": "queue",
    "all": "queue",
    "cola": "queue",
}


class VoiceError(RuntimeError):
    """Problema al entrar al canal de voz, con mensaje para el usuario."""


class VoicePermissionError(VoiceError):
    """Faltan permisos de Conectar/Hablar en el canal."""


@dataclass
class Track:
    """Una canción en la cola."""

    title: str
    url: str | None = None          # URL canónica (YouTube)
    query: str | None = None        # búsqueda de respaldo (Spotify -> YouTube)
    duration: int = 0               # segundos
    requester_id: int = 0
    requester_name: str = ""
    source: str = "YouTube"
    thumbnail: str | None = None

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "en vivo / sin dato"
        minutes, seconds = divmod(int(self.duration), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def source_label(self) -> str:
        return self.source


class GuildPlayer:
    """Reproductor independiente para un servidor de Discord."""

    def __init__(self, bot: object, guild: discord.Guild) -> None:
        self.bot = bot
        self.guild = guild

        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        # Última canción puesta: sirve para no «perder» qué sonaba aunque el
        # mezclador acabe de cerrar la pista.
        self.last_track: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None

        self.volume: float = float(bot.config.default_volume)
        self.loop_mode: str = "off"

        self.mixer: MixerSource | None = None
        # Lo pone en True la sesión de Mango AI: evita la desconexión por inactividad.
        self.keep_alive = False
        self._ffmpeg_stderr = None
        # Lo pone la IA de voz: la canción no se anuncia en el chat
        self.silent_next_track = False

        self._lock = asyncio.Lock()
        self._skip_next = False
        self._token = 0                     # invalida reproducciones en curso
        self._idle_task: asyncio.Task | None = None
        self._alone_task: asyncio.Task | None = None

    # ---------------------------------------------------------
    # Propiedades
    # ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.voice is not None and self.voice.is_connected()

    @property
    def is_playing(self) -> bool:
        mixer = self.mixer
        return bool(mixer and mixer.music_active and not mixer.music_paused)

    @property
    def is_paused(self) -> bool:
        mixer = self.mixer
        return bool(mixer and mixer.music_active and mixer.music_paused)

    @property
    def is_speaking(self) -> bool:
        return bool(self.mixer and self.mixer.speaking)

    @property
    def is_active(self) -> bool:
        """Hay algo sonando o pendiente."""
        return self.is_playing or self.is_paused or bool(self.queue)

    @property
    def loop_label(self) -> str:
        return LOOP_LABELS.get(self.loop_mode, self.loop_mode)

    @property
    def channel(self) -> discord.abc.GuildChannel | None:
        return self.voice.channel if self.connected else None

    # ---------------------------------------------------------
    # Conexión
    # ---------------------------------------------------------
    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """Conecta (o mueve) el bot al canal indicado.

        Lanza :class:`VoiceError` con un mensaje claro si Discord no completa
        el handshake (timeout, permisos, otra instancia…).
        """
        existing = self.voice
        if existing is not None and existing.is_connected():
            if existing.channel != channel:
                await existing.move_to(channel)
                log.info("Movido a '%s' en %s", channel, self.guild)
            self._ensure_mixer(existing)
            # Aunque ya estuviera conectado, la IA debe quedar escuchando.
            await self._notify_voice_connected()
            return existing

        # Cliente a medio conectar (handshake fallido): se descarta y se reintenta.
        if existing is not None:
            log.warning("Había un cliente de voz sin conexión en %s; lo descarto", self.guild)
            with contextlib.suppress(Exception):
                await existing.disconnect(force=True)
            self.voice = None

        self._check_voice_permissions(channel)

        # self_deaf=False: hay que escuchar para la charla por voz.
        # Se usa VoiceRecvClient (sirve también solo para música) para que el
        # bot pueda oír en CUALQUIER canal al que entre.
        kwargs: dict[str, object] = {"self_deaf": False, "self_mute": False, "timeout": 20}
        if VoiceRecvClient is not None:
            kwargs["cls"] = VoiceRecvClient

        try:
            self.voice = await self._handshake(channel, kwargs)
        except VoicePermissionError:
            raise
        except VoiceError:
            raise
        self._ensure_mixer(self.voice)
        log.info(
            "Conectado a '%s' en %s%s",
            channel,
            self.guild,
            "" if VoiceRecvClient is not None else " (sin recepción de audio)",
        )
        # Avisa a Mango AI (u otros cogs) para que armen su escucha.
        await self._notify_voice_connected()
        return self.voice

    async def _notify_voice_connected(self) -> None:
        """Avisa a los cogs de que hay conexión de voz (la IA arma la escucha)."""
        dispatch = getattr(self.bot, "dispatch_voice_connected", None)
        if dispatch is None:
            return
        try:
            await dispatch(self.guild)
        except Exception:
            log.debug("Fallo avisando de la conexión de voz", exc_info=True)

    async def _handshake(
        self, channel: discord.VoiceChannel, kwargs: dict[str, object]
    ) -> discord.VoiceClient:
        """Intenta el handshake de voz con un reintento (los timeouts son transitorios)."""
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                return await channel.connect(**kwargs)  # type: ignore[arg-type]
            except VoicePermissionError:
                raise
            except TimeoutError as exc:
                last_error = exc
                self.voice = None
                log.warning(
                    "El handshake de voz se agotó (intento %s/2) en %s", attempt + 1, self.guild
                )
            except discord.errors.ConnectionClosed as exc:
                code = getattr(exc, "code", None)
                self.voice = None
                if code == 4017 and dave_is_disabled():
                    # El canal exige E2EE: se vuelve a habilitar DAVE y se reintenta.
                    dave_restore()
                    last_error = exc
                    await asyncio.sleep(1.0)
                    continue
                if code == 4017:
                    raise VoiceError(
                        "Discord exige cifrado E2EE (DAVE) en ese canal y la sesión "
                        "no llegó a establecerse."
                    ) from exc
                raise VoiceError(f"Discord cerró la conexión de voz (código {code}).") from exc
            except discord.ClientException as exc:
                self.voice = None
                raise VoiceError(f"Discord rechazó la conexión: {exc}") from exc
            except Exception as exc:
                self.voice = None
                raise VoiceError(
                    f"Error conectando al canal ({type(exc).__name__})."
                ) from exc

            # Deja limpio el cliente a medias antes del segundo intento.
            with contextlib.suppress(Exception):
                stale = channel.guild.voice_client
                if stale is not None:
                    await stale.disconnect(force=True)
            await asyncio.sleep(1.5)

        raise VoiceError(
            "Discord no completó la conexión de voz (se agotó el tiempo dos veces)."
        ) from last_error

    @staticmethod
    def _check_voice_permissions(channel: discord.VoiceChannel) -> None:
        """Verifica Conectar/Hablar antes de intentar el handshake."""
        me = getattr(channel.guild, "me", None)
        if me is None:
            return
        try:
            permissions = channel.permissions_for(me)
        except Exception:
            return

        if not permissions.connect:
            raise VoicePermissionError(
                f"No tengo permiso para **Conectar** en {channel.mention}."
            )
        if not permissions.speak:
            raise VoicePermissionError(
                f"No tengo permiso para **Hablar** en {channel.mention}: "
                "entraría, pero no se oiría nada."
            )

    def _ensure_mixer(self, voice: discord.VoiceClient) -> MixerSource:
        """Instala el mezclador como fuente permanente del cliente de voz."""
        if self.mixer is None:
            self.mixer = MixerSource(self.volume, tts_gain=self.bot.config.tts_gain)
        if not voice.is_playing() and not voice.is_paused():
            try:
                voice.play(self.mixer, after=self._on_mixer_end)
            except Exception:
                log.exception("No pude iniciar el mezclador de audio")
        return self.mixer

    def _on_mixer_end(self, error: Exception | None) -> None:
        if error is not None:
            log.error("El mezclador terminó con error: %r", error)
        self.mixer = None

    def attach_voice(self, voice: discord.VoiceClient) -> None:
        """Registra un cliente de voz ya conectado (p. ej. ``VoiceRecvClient``)."""
        self.voice = voice
        self._ensure_mixer(voice)

    async def disconnect(self) -> None:
        """Sale del canal de voz y limpia el estado."""
        self._token += 1
        self._skip_next = False
        self._cancel_idle_timer()
        self.cancel_alone_disconnect()
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"
        self._release_mixer()

        voice, self.voice = self.voice, None
        if voice is None:
            return
        # 1) Parar el lector ANTES de cerrar: si queda vivo, decodifica los
        #    paquetes de la siguiente sesión con la clave vieja (OpusError).
        with contextlib.suppress(Exception):
            if getattr(voice, "is_listening", lambda: False)() is True:
                voice.stop_listening()
        # 2) Cerrar la conexión
        try:
            await voice.disconnect(force=True)
        except Exception:  # el cliente puede estar ya desconectado
            log.debug("Desconexión no limpia en %s", self.guild, exc_info=True)

        dispatch = getattr(self.bot, "dispatch_voice_disconnected", None)
        if dispatch is not None:
            with contextlib.suppress(Exception):
                await dispatch(self.guild)

    def _release_mixer(self) -> None:
        mixer, self.mixer = self.mixer, None
        if mixer is not None:
            mixer.clear_music()
            mixer.clear_tts()
    # ---------------------------------------------------------
    # Mensajería
    # ---------------------------------------------------------
    async def _send(self, **kwargs: object) -> None:
        channel = self.text_channel
        if channel is None:
            return
        try:
            await channel.send(**kwargs)
        except discord.HTTPException:
            log.warning(
                "No pude enviar mensaje en el canal %s",
                getattr(channel, "id", "?"),
                exc_info=True,
            )

    async def notify(self, embed: discord.Embed) -> None:
        await self._send(embed=embed)

    # ---------------------------------------------------------
    # Cola
    # ---------------------------------------------------------
    def enqueue(self, track: Track, *, max_size: int) -> int | None:
        """Añade una canción. Devuelve su posición o ``None`` si la cola está llena."""
        if len(self.queue) >= max_size:
            return None
        self.queue.append(track)
        return len(self.queue)

    def find_duplicate(self, track: Track) -> tuple[Track, int | None] | None:
        """¿Esta canción ya está puesta? Devuelve ``(existente, posición)``.

        Posición ``0`` = sonando ahora; ``1..N`` = en la cola.
        Se compara por URL (mismo vídeo) y por título normalizado (misma
        canción desde otra fuente o con «(Official Video)» de más).
        """
        existentes: list[tuple[Track, int | None]] = []
        if self.current is not None:
            existentes.append((self.current, 0))
        existentes.extend((item, indice) for indice, item in enumerate(self.queue, start=1))

        url = track.url
        clave = titulo_normalizado(track.title)
        clave_busqueda = titulo_normalizado(track.query or "")

        for existente, posicion in existentes:
            if url and existente.url and url == existente.url:
                return existente, posicion
            if clave and titulo_normalizado(existente.title) == clave:
                return existente, posicion
            if clave_busqueda and titulo_normalizado(existente.query or "") == clave_busqueda:
                return existente, posicion
        return None

    def remove_index(self, index: int) -> Track | None:
        """Quita la canción en la posición ``index`` (1-based)."""
        if not 1 <= index <= len(self.queue):
            return None
        tracks = list(self.queue)
        removed = tracks.pop(index - 1)
        self.queue.clear()
        self.queue.extend(tracks)
        return removed

    def shuffle(self) -> int:
        tracks = list(self.queue)
        random.shuffle(tracks)
        self.queue.clear()
        self.queue.extend(tracks)
        return len(tracks)

    def set_loop(self, mode: str) -> str:
        resolved = LOOP_ALIASES.get(mode.strip().lower())
        if resolved is None:
            raise ValueError(f"modo de loop desconocido: {mode!r}")
        self.loop_mode = resolved
        return resolved

    def set_volume(self, volume: float) -> float:
        self.volume = max(0.0, min(2.0, float(volume)))
        if self.mixer is not None:
            self.mixer.set_volume(self.volume)
        return self.volume

    # ---------------------------------------------------------
    # Reproducción
    # ---------------------------------------------------------
    async def play_next(self, *, depth: int = 0) -> None:
        """Prepara y reproduce la siguiente canción de la cola."""
        async with self._lock:
            voice = self.voice
            if voice is None or not voice.is_connected():
                return
            if self.is_playing or self.is_paused:
                return

            skipped = self._skip_next
            self._skip_next = False

            track: Track | None
            if skipped:
                track = self.queue.popleft() if self.queue else None
            elif self.loop_mode == "track" and self.current is not None:
                track = self.current
            else:
                track = self.queue.popleft() if self.queue else None
                if track is not None and self.loop_mode == "queue" and self.current is not None:
                    self.queue.append(self.current)

            if track is None:
                self.current = None
                self._start_idle_timer()
                return

            self.current = track
            self.last_track = track
            self._cancel_idle_timer()
            token = self._token

        # La resolución del stream va fuera del lock para que el resto de
        # comandos (skip, stop, queue...) no se queden esperando.
        try:
            stream_url, meta = await self.bot.ytdlp.stream_url(
                webpage_url=track.url,
                search_query=track.query,
            )
        except Exception:
            log.exception("No se pudo preparar el audio de %r", track.title)
            if depth < 5:
                await self.notify(
                    personality.error_embed(
                        f"No pude preparar **{track.title}**. Salto a la siguiente."
                    )
                )
                await self.play_next(depth=depth + 1)
            return

        if token != self._token:
            log.debug("Reproducción cancelada para %r", track.title)
            return

        async with self._lock:
            voice = self.voice
            if voice is None or not voice.is_connected():
                return
            if self.is_playing or self.is_paused:
                return

            track.title = meta.get("title") or track.title
            track.duration = int(meta.get("duration") or track.duration or 0)
            if meta.get("webpage_url"):
                track.url = meta["webpage_url"]
            if not track.thumbnail:
                track.thumbnail = meta.get("thumbnail")

            try:
                # El archivo se cierra al terminar la pista (ver _read_ffmpeg_stderr)
                stderr_capture = tempfile.TemporaryFile()  # noqa: SIM115
                source = discord.FFmpegPCMAudio(
                    stream_url, stderr=stderr_capture, **FFMPEG_OPTIONS
                )
                self._ffmpeg_stderr = stderr_capture
                mixer = self._ensure_mixer(voice)
                mixer.set_volume(self.volume)
                mixer.set_music(source, on_end=self._music_finished)
            except Exception:
                log.exception("FFmpeg/mixer falló para %r", track.title)
                return

        if self.silent_next_track:
            self.silent_next_track = False
        else:
            await self.notify(personality.now_playing_embed(track))
        await self._prefetch_next()

    def _music_finished(self) -> None:
        """Callback del mixer cuando se acaba una canción (hilo de audio)."""
        loop = getattr(self.bot, "loop", None)
        if loop is None or loop.is_closed():
            return
        report = self._collect_track_report()
        loop.call_soon_threadsafe(self._schedule_next, report)

    def _collect_track_report(self) -> dict:
        mixer = self.mixer
        report: dict = dict(mixer.stats) if mixer is not None else {}
        report["stderr"] = self._read_ffmpeg_stderr()
        report["title"] = self.current.title if self.current is not None else "?"
        return report

    def _read_ffmpeg_stderr(self) -> str:
        handle, self._ffmpeg_stderr = self._ffmpeg_stderr, None
        if handle is None:
            return ""
        try:
            handle.seek(0)
            data = handle.read(1500).decode("utf-8", "ignore").strip()
        except Exception:
            data = ""
        finally:
            with contextlib.suppress(Exception):
                handle.close()
        return data

    def _schedule_next(self, report: dict | None = None) -> None:
        if report:
            self._log_track_report(report)
        try:
            task = asyncio.create_task(self.play_next())
        except RuntimeError:
            log.debug("Sin event loop activo para programar la siguiente canción")
            return
        task.add_done_callback(self._log_future_result)

    def _log_track_report(self, report: dict) -> None:
        seconds = float(report.get("track_seconds") or 0.0)
        peak = float(report.get("track_peak") or 0.0)
        title = str(report.get("title") or "?")
        stderr = str(report.get("stderr") or "")

        if stderr:
            log.warning("FFmpeg reportó: %s", stderr.replace("\n", " ")[:300])

        if seconds >= 5 and peak < 0.01:
            log.warning(
                "La pista '%s' sonó %.1f s con pico %.4f (posible silencio)",
                title,
                seconds,
                peak,
            )
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(
                    self.notify(
                        personality.error_embed(
                            f"**{title}** salió sin audio perceptible "
                            "(intro silenciosa o stream roto). Prueba con otro tema."
                        )
                    )
                )
        else:
            log.debug("Pista '%s': %.1f s, pico %.3f", title, seconds, peak)

    @property
    def audio_stats(self) -> dict:
        """Estadísticas del mezclador para `!diag`."""
        return dict(self.mixer.stats) if self.mixer is not None else {}

    @staticmethod
    def _log_future_result(future: asyncio.Future[None]) -> None:
        try:
            future.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("play_next falló en segundo plano")

    async def _prefetch_next(self) -> None:
        """Resuelve la próxima canción en segundo plano (menos silencio entre temas)."""
        candidate = next((t for t in self.queue if t.url or t.query), None)
        if candidate is None:
            return
        try:
            await self.bot.ytdlp.stream_url(
                webpage_url=candidate.url,
                search_query=candidate.query,
            )
        except Exception:
            log.debug("Prefetch falló para %r", candidate.title, exc_info=True)

    # ---------------------------------------------------------
    # Controles de transporte (cualquiera que escuche puede usarlos)
    # ---------------------------------------------------------
    async def skip(self) -> bool:
        # Tolerante: sirve aunque el mezclador acabe de cerrar la pista.
        if not (
            self.is_playing
            or self.is_paused
            or self.current is not None
            or bool(self.queue)
        ):
            return False
        self._skip_next = True
        self._stop_music_source()
        await self.play_next()
        return True

    async def stop(self) -> None:
        self._token += 1
        self._skip_next = False
        self.loop_mode = "off"
        self.queue.clear()
        self.current = None
        self._stop_music_source()
        self.clear_speech()
        self._start_idle_timer()

    def pause(self) -> bool:
        if not self.is_playing or self.mixer is None:
            return False
        self.mixer.set_music_paused(True)
        return True

    def resume(self) -> bool:
        if not self.is_paused or self.mixer is None:
            return False
        self.mixer.set_music_paused(False)
        return True

    async def replay(self) -> bool:
        if self.current is None:
            return False
        self.queue.appendleft(self.current)
        self._skip_next = True
        self._stop_music_source()
        await self.play_next()
        return True

    def play_source(self, source: discord.AudioSource) -> bool:
        """Reproduce una fuente arbitraria por el mezclador (p. ej. `!test`)."""
        if self.mixer is None and self.voice is not None:
            self._ensure_mixer(self.voice)
        if self.mixer is None:
            return False
        self.mixer.set_volume(self.volume)
        self.mixer.set_music(source, on_end=self._music_finished)
        return True

    def _stop_music_source(self) -> None:
        if self.mixer is not None:
            self.mixer.clear_music()

    # ---------------------------------------------------------
    # Voz de Mango AI (se mezcla con la música)
    # ---------------------------------------------------------
    def speak(self, pcm: bytes) -> None:
        """Encola voz sintetizada (PCM 48 kHz estéreo) para reproducir."""
        if self.mixer is not None:
            self.mixer.push_tts(pcm)

    def clear_speech(self) -> None:
        if self.mixer is not None:
            self.mixer.clear_tts()

    # ---------------------------------------------------------
    # Temporizadores: inactividad y canal vacío
    # ---------------------------------------------------------
    def mark_disconnected(self) -> None:
        """Limpia el estado si el bot es expulsado del canal de voz."""
        self._token += 1
        self._skip_next = False
        self._cancel_idle_timer()
        self.cancel_alone_disconnect()
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"
        voice = self.voice
        with contextlib.suppress(Exception):
            if voice is not None and getattr(voice, "is_listening", lambda: False)() is True:
                voice.stop_listening()
        self._release_mixer()
        self.voice = None
        self._notify_voice_disconnected()

    def _notify_voice_disconnected(self) -> None:
        dispatch = getattr(self.bot, "dispatch_voice_disconnected", None)
        if dispatch is None:
            return
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(dispatch(self.guild))

    def _start_idle_timer(self) -> None:
        self._cancel_idle_timer()
        if not self.connected:
            return
        # IDLE_TIMEOUT=0 → nunca se desconecta por inactividad: solo se sale
        # si el bot se queda solo o si se lo piden (!bye o hablando con Mango).
        if int(self.bot.config.idle_timeout) <= 0:
            return
        self._idle_task = asyncio.create_task(
            self._idle_watchdog(), name=f"mango-idle-{self.guild.id}"
        )

    def _cancel_idle_timer(self) -> None:
        task, self._idle_task = self._idle_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _idle_watchdog(self) -> None:
        try:
            await asyncio.sleep(self.bot.config.idle_timeout)
        except asyncio.CancelledError:
            return
        self._idle_task = None
        if self.keep_alive:
            return
        if self.voice is None or self.is_playing or self.is_paused or self.queue:
            return
        minutes = max(1, self.bot.config.idle_timeout // 60)
        await self.notify(personality.idle_disconnect_embed(minutes))
        await self.disconnect()

    def schedule_alone_disconnect(self) -> None:
        if self._alone_task is not None and not self._alone_task.done():
            return
        if not self.connected:
            return
        self._alone_task = asyncio.create_task(
            self._alone_watchdog(), name=f"mango-alone-{self.guild.id}"
        )

    def cancel_alone_disconnect(self) -> None:
        task, self._alone_task = self._alone_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _alone_watchdog(self) -> None:
        try:
            await asyncio.sleep(self.bot.config.alone_grace)
        except asyncio.CancelledError:
            return
        self._alone_task = None
        channel = self.channel
        if channel is None:
            return
        humans = [member for member in getattr(channel, "members", []) if not member.bot]
        if humans:
            return
        await self.notify(personality.alone_disconnect_embed())
        await self.disconnect()
