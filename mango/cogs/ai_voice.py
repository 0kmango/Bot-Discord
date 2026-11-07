"""Mango AI por voz: escucha el canal y se activa con «oye Mango».

Flujo completo:

    audio del canal → VAD (frases) → STT → ¿«oye Mango»? → LLM → TTS
    → mezclado con la música (la música baja de volumen, no se corta)

El bot no guarda audio: transcribe, responde y descarta los frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord.ext import commands

from mango import personality
from mango.services.audio import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    UtteranceCollector,
    tail_seconds,
)
from mango.services.dave import dave_status
from mango.services.intent import es_para_mango
from mango.services.llm import MUSIC_TOOLS, LLMError
from mango.services.stt import STTError
from mango.services.texto import (
    control_de_voz,
    es_peticion_musica,
    es_saludo,
    limpiar_peticion,
)
from mango.services.tools import MangoTools
from mango.services.tts import SentenceChunker, TTSError, split_sentences
from mango.services.wake import contains_wake_word, strip_wake_word

try:  # dependencia opcional: sin ella el bot sigue funcionando sin voz
    from discord.ext import voice_recv
except Exception:  # pragma: no cover
    voice_recv = None
    logging.getLogger(__name__).warning(
        "discord-ext-voice-recv no está instalado: la charla por voz queda desactivada"
    )

log = logging.getLogger(__name__)

MAX_QUEUE = 8
TTS_SENTENCE_CHARS = 180
# Cada petición por voz cuesta STT + LLM + TTS. Con esto, hablarle en bucle no
# dispara decenas de llamadas (y de factura): mismo usuario, como mínimo 2,5 s.
VOICE_USER_COOLDOWN = 2.5
# Si tras «oye Mango» el audio dura al menos esto y no se entendió nada, se
# avisa por voz («no te pillé»). Si fue más corto, solo dijo el nombre.
NO_ENTENDI_MIN_SEGUNDOS = 1.8


def _is_listening(voice) -> bool:
    """¿Está el lector de audio realmente activo?

    ``voice_recv`` devuelve el centinela ``MISSING`` (``_MissingSentinel``)
    cuando no hay lector, en lugar de un booleano. Comparar con ``is True``
    evita cualquier ambigüedad (``MISSING`` es *falsy* pero no ``False``).
    """
    try:
        return getattr(voice, "is_listening", lambda: False)() is True
    except Exception:
        return False


@dataclass
class VoiceSession:
    """Estado de la conversación por voz de un servidor."""

    guild_id: int
    channel_id: int
    text_channel: Optional[discord.abc.Messageable] = None
    active_until: float = 0.0
    wake_enabled: bool = True
    announced: bool = False
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=MAX_QUEUE))
    worker: Optional[asyncio.Task] = None

    def in_conversation(self) -> bool:
        return time.monotonic() < self.active_until

    def open_window(self, seconds: int) -> None:
        """Abre la ventana de conversación (0 = nunca: hace falta «oye Mango")."""
        if seconds <= 0:
            self.active_until = 0.0
            return
        self.active_until = time.monotonic() + max(5, seconds)

    def close_window(self) -> None:
        self.active_until = 0.0


if voice_recv is not None:

    class MangoSink(voice_recv.AudioSink):
        """Recibe el audio del canal y lo trocea en frases por usuario."""

        def __init__(self, cog: AIVoice, session: VoiceSession) -> None:
            super().__init__()
            self._cog = cog
            self._session = session
            self._collectors: dict[int, UtteranceCollector] = {}

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data) -> None:  # noqa: ANN001 - firma de la librería
            if user is None or getattr(user, "bot", False):
                return

            player = self._cog.bot.players.get(self._session.guild_id)
            if player is None or not player.connected:
                return

            pcm = getattr(data, "pcm", b"")
            config = self._cog.bot.config

            # Con música sonando se exige un poco más de energía (el micro del
            # usuario la capta), pero **no se toca el volumen**: la canción se
            # oye igual y solo baja cuando habla Mango.
            umbral = config.voice_energy
            if player.is_playing:
                umbral = config.voice_energy_music

            if player.is_speaking:
                return  # mientras Mango habla se ignora el audio (evita eco)

            collector = self._collectors.get(user.id)
            if collector is None:
                collector = UtteranceCollector(
                    energy=umbral,
                    silence_ms=config.voice_silence_ms,
                    min_speech_ms=config.voice_min_speech_ms,
                )
                self._collectors[user.id] = collector
            else:
                collector.set_energy(umbral)

            utterance = collector.feed(pcm)
            self._cog._note_audio(self._session.guild_id, bool(utterance))
            if utterance:
                self._cog.on_utterance(self._session, user, utterance)

        def reset(self) -> None:
            for collector in self._collectors.values():
                collector.reset()

        def cleanup(self) -> None:
            self._collectors.clear()

else:  # pragma: no cover
    MangoSink = None  # type: ignore[assignment]


class AIVoice(commands.Cog):
    """Charla por voz con Mango AI, activada por «oye Mango»."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.sessions: dict[int, VoiceSession] = {}
        self._sinks: dict[int, object] = {}
        self._sink_channels: dict[int, int] = {}
        self._auto_started = False
        # Interjecciones ya sintetizadas («¡Marchando!»…) para responder al
        # instante, sin esperar a la búsqueda ni al modelo.
        self._interjecciones: list[bytes] = []
        self._interjeccion_idx = 0
        # Saludos ya sintetizados («¡Hola! Dime qué te pongo.»…).
        self._saludos: list[bytes] = []
        self._saludo_idx = 0
        # Respuestas de control («¡Fuera!», «Parado.»…) por acción.
        self._controles: dict[str, list[bytes]] = {}
        self._control_idx = 0
        # Última petición por (servidor, usuario): límite de tasa de la voz.
        self._ultima_peticion: dict[tuple[int, int], float] = {}
        # Contadores y último texto oído (para `!diag`)
        self._stats: dict[int, dict] = {}
        self._warned: dict[int, bool] = {}
        self._dave_seen: dict[int, tuple] = {}
        self._watchdog: asyncio.Task | None = None

    # ---------------------------------------------------------
    # Diagnóstico
    # ---------------------------------------------------------
    def _note_audio(self, guild_id: int, emitted_utterance: bool) -> None:
        """Se llama desde el hilo del sink por cada frame recibido."""
        stats = self._stats.setdefault(guild_id, {"frames": 0, "utterances": 0})
        stats["frames"] = stats.get("frames", 0) + 1
        if emitted_utterance:
            stats["utterances"] = stats.get("utterances", 0) + 1
            stats["last_at"] = time.time()

    def diag_report(self, guild: discord.Guild) -> dict:
        session = self.sessions.get(guild.id)
        stats = self._stats.get(guild.id, {})
        voice = guild.voice_client
        return {
            "session": session is not None,
            "conversando": bool(session and session.in_conversation()),
            "listening": _is_listening(voice),
            "frames": int(stats.get("frames", 0)),
            "utterances": int(stats.get("utterances", 0)),
            "last_text": str(stats.get("last_text", "")),
        }

    @staticmethod
    def _voice_warning(guild: discord.Guild) -> Optional[str]:
        state = getattr(getattr(guild, "me", None), "voice", None)
        if state is None:
            return None
        if getattr(state, "deaf", False):
            return (
                "Estoy **ensordecido** en este servidor, así que no puedo oírte.\n"
                "Quítame el «ensordecer»: clic derecho sobre mí en el canal."
            )
        if getattr(state, "self_deaf", False):
            return "Estoy sordo por mi propia configuración: reinicia el bot."
        if getattr(state, "mute", False):
            return (
                "Estoy **silenciado** en este servidor: la música y mi voz no sonarán.\n"
                "Quítame el «silenciar»: clic derecho sobre mí en el canal."
            )
        return None

    def cog_unload(self) -> None:
        if self._watchdog is not None and not self._watchdog.done():
            self._watchdog.cancel()
        self._watchdog = None
        for session in list(self.sessions.values()):
            self._cancel_worker(session)
        self.sessions.clear()
        self._sinks.clear()

    # ---------------------------------------------------------
    # Disponibilidad
    # ---------------------------------------------------------
    def _voice_available(self) -> bool:
        return (
            MangoSink is not None
            and voice_recv is not None
            and self.bot.config.voice_enabled
        )

    def _unavailable_reason(self) -> str:
        if voice_recv is None or MangoSink is None:
            return "Falta el paquete `discord-ext-voice-recv`."
        if not self.bot.config.ai_enabled:
            return "Falta el LLM (`LLM_API_KEY`) en el `.env`."
        if not self.bot.config.stt_enabled or not self.bot.config.tts_enabled:
            return "Revisa `STT_*` / `TTS_*` en el `.env`."
        return "La IA de voz no está disponible ahora mismo."

    # ---------------------------------------------------------
    # Comandos
    # ---------------------------------------------------------
    @commands.group(name="ai", invoke_without_command=True)
    @commands.guild_only()
    async def ai(self, ctx: commands.Context) -> None:
        """Mango AI: charla por voz en el canal donde estés."""
        await self._send_status(ctx)

    @ai.command(name="join", aliases=["entrar", "escuchar", "on"])
    @commands.guild_only()
    async def ai_join(self, ctx: commands.Context) -> None:
        """Igual que `!hi`: entra a tu canal de voz y queda escuchando."""
        await self._delegar(ctx, "hi")

    @ai.command(name="leave", aliases=["salir", "off"])
    @commands.guild_only()
    async def ai_leave(self, ctx: commands.Context) -> None:
        """Igual que `!bye`: sale del canal de voz y deja de escuchar."""
        await self._delegar(ctx, "bye")

    async def _delegar(self, ctx: commands.Context, nombre: str) -> None:
        """Ejecuta otro comando (`!hi`/`!bye`) para no duplicar lógica."""
        comando = self.bot.get_command(nombre)
        if comando is None:
            await ctx.send(
                embed=personality.warn_embed(f"El comando `!{nombre}` no está disponible.")
            )
            return
        await ctx.invoke(comando)
    # ---------------------------------------------------------
    # Armar la escucha (en CUALQUIER canal donde esté el bot)
    # ---------------------------------------------------------
    def _session(self, guild: discord.Guild, channel_id: int) -> VoiceSession:
        session = self.sessions.get(guild.id)
        if session is None:
            session = VoiceSession(guild_id=guild.id, channel_id=channel_id)
            self.sessions[guild.id] = session
        else:
            session.channel_id = channel_id
        return session

    def _default_text_channel(self, guild: discord.Guild, player):
        """Canal donde avisar: el de la IA, el último usado o el general."""
        candidates = [
            guild.get_channel(self.bot.config.ai_channel_id)
            if self.bot.config.ai_channel_id
            else None,
            getattr(player, "text_channel", None),
            guild.system_channel,
        ]
        for candidate in candidates:
            if isinstance(candidate, discord.abc.Messageable):
                return candidate
        return None

    async def _arm(self, guild: discord.Guild, *, announce: bool = False) -> bool:
        """Deja al bot escuchando «oye Mango» en el canal donde esté."""
        if not self._voice_available():
            return False

        voice = guild.voice_client
        channel = getattr(voice, "channel", None)
        if voice is None or channel is None or not hasattr(voice, "listen"):
            return False

        if not getattr(voice, "is_connected", lambda: False)():
            session_prev = self.sessions.get(guild.id)
            if session_prev is not None:
                session_prev.close_window()
            log.debug("El cliente de voz aún no está conectado en %s", guild)
            return False

        player = self.bot.get_player(guild)
        player.keep_alive = True

        session = self._session(guild, channel.id)
        if session.text_channel is None:
            session.text_channel = self._default_text_channel(guild, player)

        # Si ya escuchamos de verdad en ese mismo canal, no se reinicia nada.
        if self._sink_channels.get(guild.id) == channel.id and _is_listening(voice):
            session.wake_enabled = True
            session.open_window(self.bot.config.voice_session_timeout)
            return True

        self._ensure_worker(session)
        if not self._start_listening(voice, session):
            session.close_window()
            return False

        session.wake_enabled = True
        session.open_window(self.bot.config.voice_session_timeout)

        warning = self._voice_warning(guild)
        if warning and not self._warned.get(guild.id):
            self._warned[guild.id] = True
            if session.text_channel is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.text_channel.send(embed=personality.warn_embed(warning))
            log.warning("Aviso de voz en %s: %s", guild, warning)

        if announce and not session.announced:
            session.announced = True
            if session.text_channel is not None:
                with contextlib.suppress(discord.HTTPException):
                    await session.text_channel.send(
                        embed=personality.ai_consent_embed(self.bot.config.command_prefix)
                    )
        return True


    # ---------------------------------------------------------
    # Eventos de voz (entrar, mover, salir) y arranque
    # ---------------------------------------------------------
    async def on_voice_connected(self, guild: discord.Guild) -> None:
        """Lo llama el bot al conectar al canal (música, `!hi`, `!play`…)."""
        if await self._arm(guild, announce=True):
            channel = getattr(guild.voice_client, "channel", None)
            log.debug("Mango AI escuchando en '%s' (%s)", channel, guild)

    async def on_voice_disconnected(self, guild: discord.Guild) -> None:
        """El bot salió del canal: se limpia la escucha y el estado."""
        session = self.sessions.pop(guild.id, None)
        if session is not None:
            self._cancel_worker(session)
        self._stop_listening(guild)
        self._dave_seen.pop(guild.id, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after) -> None:
        if self.bot.user is None or member.id != self.bot.user.id:
            return

        if after.channel is None:
            await self.on_voice_disconnected(member.guild)
            return

        # Entró o lo movieron a otro canal: se arma ahí mismo.
        if before.channel != after.channel or not self._sinks.get(member.guild.id):
            voice = member.guild.voice_client
            if voice is None or not getattr(voice, "is_connected", lambda: False)():
                return  # handshake en curso: lo armará dispatch_voice_connected
            with contextlib.suppress(Exception):
                if await self._arm(member.guild, announce=True):
                    log.info(
                        "Mango AI escuchando en '%s' (%s)", after.channel, member.guild
                    )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Arma la escucha donde ya esté conectado y entra al canal configurado."""
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watchdog_loop())

        if not self._voice_available():
            return

        for guild in self.bot.guilds:
            if guild.voice_client is not None:
                with contextlib.suppress(Exception):
                    await self._arm(guild)

        if not self._auto_started:
            await self._auto_join_configured_channel()

    async def _auto_join_configured_channel(self) -> None:
        channel_id = self.bot.config.ai_voice_channel_id
        if channel_id is None:
            return
        self._auto_started = True

        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            log.warning("AI_VOICE_CHANNEL_ID (%s) no es un canal de voz válido", channel_id)
            return

        player = self.bot.get_player(channel.guild)
        try:
            await player.connect(channel)
        except Exception:
            log.exception("No pude entrar al canal de voz configurado")
            return

        if await self._arm(channel.guild, announce=True):
            log.info("Mango AI se unió automáticamente a '%s'", channel)


    async def _watchdog_loop(self) -> None:
        """Red de seguridad cada 30 s.

        - Vigila el estado DAVE (causa nº1 de «no se oye nada») y reintenta la
          sesión de cifrado si hace falta.
        - Si el bot está en un canal y no está escuchando, rearma el lector.
        """
        while True:
            await asyncio.sleep(30)
            if not self._voice_available():
                continue
            for guild in list(self.bot.guilds):
                voice = guild.voice_client
                if voice is None or not getattr(voice, "is_connected", lambda: False)():
                    continue

                await self._watch_dave(guild, voice)

                if _is_listening(voice):
                    continue
                try:
                    if await self._arm(guild):
                        log.info("Escucha rearmada por el vigilante en %s", guild)
                except Exception:
                    log.debug("El vigilante de voz falló en %s", guild, exc_info=True)

    async def _watch_dave(self, guild: discord.Guild, voice) -> None:
        """Registra cambios de DAVE y reintenta la sesión si no cifra."""
        estado = dave_status(voice)
        firma = (estado.get("protocol"), estado.get("ready"), estado.get("can_encrypt"))
        if firma != self._dave_seen.get(guild.id):
            self._dave_seen[guild.id] = firma
            log.info(
                "DAVE en %s → protocolo=%s · lista=%s · cifra_salida=%s",
                guild,
                estado.get("protocol"),
                estado.get("ready"),
                estado.get("can_encrypt"),
            )

        state = getattr(voice, "_connection", None)
        if not getattr(state, "dave_protocol_version", 0):
            return
        if getattr(state, "can_encrypt", False):
            return

        humanos = [
            m for m in getattr(getattr(voice, "channel", None), "members", []) if not m.bot
        ]
        reinit = getattr(state, "reinit_dave_session", None)
        if humanos and reinit is not None:
            with contextlib.suppress(Exception):
                await reinit()
                log.info("Sesión DAVE reiniciada en %s", guild)


    @ai.command(name="status", aliases=["estado"])
    @commands.guild_only()
    async def ai_status(self, ctx: commands.Context) -> None:
        """Muestra el estado de la sesión de voz."""
        await self._send_status(ctx)

    @ai.command(name="sleep", aliases=["dormir", "callar"])
    @commands.guild_only()
    async def ai_sleep(self, ctx: commands.Context) -> None:
        """Cierra la conversación actual (sigue atento a «oye Mango»)."""
        session = self.sessions.get(ctx.guild.id)
        if session is None:
            await ctx.send(
                embed=personality.warn_embed("No estoy escuchando. Usa `!ai join` primero.")
            )
            return
        session.close_window()
        await ctx.send(
            embed=personality.info_embed(
                "Vale, me callo. Sigo con el oído puesto: di «oye Mango» cuando quieras algo."
            )
        )

    @ai.command(name="wake", aliases=["despertar"])
    @commands.guild_only()
    async def ai_wake(self, ctx: commands.Context) -> None:
        """Abre una ventana de conversación sin decir la palabra clave."""
        session = self.sessions.get(ctx.guild.id)
        if session is None:
            await ctx.send(
                embed=personality.warn_embed("No estoy escuchando. Usa `!ai join` primero.")
            )
            return
        segundos = self.bot.config.voice_session_timeout or 30
        session.open_window(segundos)
        await ctx.send(
            embed=personality.success_embed(
                f"Te escucho durante {segundos} s sin decir la palabra clave. Dispara."
            )
        )

    @ai.command(name="say", hidden=True)
    @commands.is_owner()
    async def ai_say(self, ctx: commands.Context, *, text: str) -> None:
        """Prueba de voz: hace que Mango diga el texto indicado.

        Alias: `!mango di <texto>` (también sirve con el texto entre comillas).
        """
        player = self.bot.players.get(ctx.guild.id)
        if player is None or not player.connected:
            await ctx.send(embed=personality.not_connected_embed())
            return
        if not await self.speak_text(player, text):
            await ctx.send(
                embed=personality.warn_embed("No me salió la voz; prueba otra vez.")
            )
            return
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.add_reaction("🔊")

    # ---------------------------------------------------------
    # Estado y escucha
    # ---------------------------------------------------------
    async def _send_status(self, ctx: commands.Context) -> None:
        session = self.sessions.get(ctx.guild.id)
        player = self.bot.players.get(ctx.guild.id)

        if session is None:
            if player is not None and player.connected:
                state = "conectado, sin escucha activa"
            else:
                state = "no estoy en ningún canal de voz"
        elif session.in_conversation():
            state = "en conversación"
        elif self.bot.config.voice_session_timeout <= 0:
            state = "escuchando «oye Mango» (solo responde a la palabra clave)"
        else:
            state = "escuchando «oye Mango»"
        await ctx.send(
            embed=personality.ai_status_embed(
                state=state,
                wake_words=self.bot.config.wake_word_list,
                stt=getattr(self.bot.stt, "label", "no disponible"),
                tts=getattr(self.bot.tts, "label", "no disponible"),
                model=" → ".join(self.bot._llm_chain()) or "no configurado",
                channel=player.channel if player is not None else None,
            )
        )

    def _start_listening(self, voice, session: VoiceSession) -> bool:
        """Engancha el sink y devuelve si realmente quedó escuchando."""
        if MangoSink is None:
            return False

        sink = MangoSink(self, session)
        for intento in range(3):
            try:
                if _is_listening(voice):
                    voice.stop_listening()
                    # El lector se detiene en su hilo: hay que darle un respiro.
                    time.sleep(0.2 * (intento + 1))
                voice.listen(sink)
            except Exception as exc:
                log.warning("Intento %s de escuchar falló: %s", intento + 1, exc)
                time.sleep(0.2)
                continue

            self._sinks[session.guild_id] = sink
            self._sink_channels[session.guild_id] = session.channel_id
            log.info(
                "Mango AI escuchando en %s (servidor %s)",
                session.channel_id,
                session.guild_id,
            )
            return True

        log.error("No pude empezar a escuchar en el servidor %s", session.guild_id)
        return False

    def _stop_listening(self, guild: discord.Guild) -> None:
        self._sinks.pop(guild.id, None)
        self._sink_channels.pop(guild.id, None)
        voice = guild.voice_client
        if voice is None:
            return
        with contextlib.suppress(Exception):
            if _is_listening(voice):
                voice.stop_listening()

    # ---------------------------------------------------------
    # Entrada de audio → cola
    # ---------------------------------------------------------
    def on_utterance(self, session: VoiceSession, user, pcm: bytes) -> None:
        """Llamado desde el hilo del sink: pasa el audio al event loop."""
        loop = getattr(self.bot, "loop", None)
        if loop is None or loop.is_closed():
            return
        name = getattr(user, "display_name", "alguien")
        loop.call_soon_threadsafe(self._enqueue, session, user.id, name, pcm)

    def _enqueue(self, session: VoiceSession, user_id: int, name: str, pcm: bytes) -> None:
        if session.queue.full():
            log.debug("Cola de voz llena: descarto una frase")
            return
        session.queue.put_nowait((user_id, name, pcm))

    def _ensure_worker(self, session: VoiceSession) -> None:
        if session.worker is None or session.worker.done():
            session.worker = asyncio.create_task(self._worker(session))

    def _cancel_worker(self, session: VoiceSession) -> None:
        worker, session.worker = session.worker, None
        if worker is not None and not worker.done():
            worker.cancel()

    async def _worker(self, session: VoiceSession) -> None:
        while True:
            user_id, name, pcm = await session.queue.get()
            try:
                await self._handle_utterance(session, user_id, name, pcm)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Error procesando una frase de voz")
            finally:
                session.queue.task_done()

    # ---------------------------------------------------------
    # Cerebro: STT → wake word → LLM → TTS
    # ---------------------------------------------------------
    async def _handle_utterance(
        self,
        session: VoiceSession,
        user_id: int,
        name: str,
        pcm: bytes,
    ) -> None:
        player = self.bot.players.get(session.guild_id)
        if player is None or not player.connected or self.bot.stt is None:
            return
        if player.is_speaking:
            return

        conversando = session.in_conversation()
        segundos = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
        config = self.bot.config

        # Fuera de conversación solo se analizan frases cortas: así la música o
        # una charla larga NO se transcriben (más rápido y más privado).
        if (
            not conversando
            and not config.voice_transcribe_all
            and segundos > config.voice_wake_max_seconds
        ):
            if player.is_playing:
                # Con música de fondo el micro puede captarla y el detector no
                # encuentra silencio: en vez de tirar la frase se mira su final,
                # que es donde acaba de hablar. Así «oye Mango» se detecta igual.
                pcm = tail_seconds(pcm, config.voice_wake_max_seconds)
                log.debug(
                    "[voz] audio de %.1fs con música: analizo los últimos %.0fs",
                    segundos,
                    config.voice_wake_max_seconds,
                )
            else:
                log.debug(
                    "Audio de %.1fs sin conversación activa: no se transcribe", segundos
                )
                return

        arranque = time.perf_counter()

        if conversando or config.voice_transcribe_all:
            text = await self._transcribir(self.bot.stt, pcm, "comando")
        else:
            # 1) frase rápida con el modelo pequeño, solo para la palabra clave
            rapido = self.bot.wake_stt or self.bot.stt
            text = await self._transcribir(rapido, pcm, "clave")
            # 2) Si sonó la palabra clave, el comando se re-transcribe con el
            #    modelo bueno (la búsqueda de música necesita precisión).
            if (
                text
                and rapido is not None
                and rapido is not self.bot.stt
                and contains_wake_word(text, config.wake_word_list)
            ):
                mejor = await self._transcribir(self.bot.stt, pcm, "comando")
                if mejor:
                    text = mejor

        if not text or len(text.strip()) < 2:
            log.debug("[voz] %s: audio sin texto reconocible", name)
            return

        wake = session.wake_enabled and contains_wake_word(text, config.wake_word_list)
        stats = self._stats.setdefault(session.guild_id, {})
        stats["last_text"] = text

        if wake or conversando:
            log.info(
                "[voz] %s dijo %r → %s (STT %.2fs)",
                name,
                text,
                "ACTIVA" if wake else "en conversación",
                time.perf_counter() - arranque,
            )
        else:
            log.debug("[voz] %s: %r (sin «oye Mango»)", name, text)

        if not wake and not conversando:
            return

        request = strip_wake_word(text, config.wake_word_list) if wake else text

        # Con la ventana de conversación abierta el bot oye TODO lo que se dice
        # en el canal (incluida la charla entre otras personas). Solo responde
        # si la frase parece dirigida a él.
        if (
            conversando
            and not wake
            and config.voice_conversation_filter
            and not es_para_mango(text, config.wake_word_list)
        ):
            log.debug("[voz] %s: charla ajena, no contesto (%r)", name, text)
            return

        session.open_window(config.voice_session_timeout)

        if not request.strip():
            # Un saludo («hola Mango») se contesta al instante: es una persona
            # saludando, no una petición. Nunca se pone música por eso.
            if es_saludo(text):
                log.info("[voz] %s saludó: contesto sin poner nada", name)
                await self._hablar_saludo(player)
                return

            # Dijo la palabra clave y nada más: no se interrumpe lo que estaba
            # haciendo. Pero si el audio era largo, es que habló y no se
            # entendió: se le avisa por voz.
            if segundos >= NO_ENTENDI_MIN_SEGUNDOS:
                log.info("[voz] %s: no entendí la petición tras «oye Mango»", name)
                await self._speak_sentence(
                    player, personality.pick(personality.AI_NO_ENTENDI)
                )
            else:
                log.info("[voz] %s dijo solo la palabra clave: sigo a lo mío", name)
            return

        # Límite de tasa por usuario: una petición cada VOICE_USER_COOLDOWN.
        # Los controles («salta», «para») no cuentan: deben ser instantáneos.
        clave = (session.guild_id, user_id)
        ahora = time.monotonic()
        es_control = control_de_voz(request) is not None
        if (
            not es_control
            and ahora - self._ultima_peticion.get(clave, 0.0) < VOICE_USER_COOLDOWN
        ):
            log.info("[voz] %s pidió dos cosas seguidas: se ignora la segunda", name)
            return
        self._ultima_peticion[clave] = ahora
        if len(self._ultima_peticion) > 2000:
            self._ultima_peticion.clear()

        await self._respond(session, player, user_id, name, request)

    async def _transcribir(self, servicio, pcm: bytes, etiqueta: str) -> str:
        """Transcribe con el servicio indicado, midiendo el tiempo."""
        if servicio is None:
            return ""
        inicio = time.perf_counter()
        try:
            texto = await servicio.transcribe(pcm)
        except STTError as exc:
            log.warning("No pude transcribir (%s): %s", etiqueta, exc)
            return ""
        log.debug(
            "STT %s con %s en %.2fs",
            etiqueta,
            getattr(servicio, "label", "?"),
            time.perf_counter() - inicio,
        )
        return texto

    async def _prebuscar(self, consulta: str, user_id: int, nombre: str, tools=None):
        """Búsqueda especulativa en YouTube. Nunca lanza: devuelve Track o None.

        Si encuentra la canción, deja también la confirmación hablada lista,
        para que suene sin esperas cuando el modelo decida ponerla.
        """
        try:
            track = await self.bot.ytdlp.search(
                consulta, requester_id=user_id, requester_name=nombre
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("Prebúsqueda %r falló", consulta, exc_info=True)
            return None

        if track is not None and tools is not None:
            tools.prepare_confirmation(track)
        return track

    async def _respond(
        self,
        session: VoiceSession,
        player,
        user_id: int,
        name: str,
        request: str,
    ) -> None:
        if self.bot.llm is None:
            return

        guild = self.bot.get_guild(session.guild_id)
        member = guild.get_member(user_id) if guild is not None else None
        scope = f"voice:{session.guild_id}:{user_id}"
        # Menos historial = prompt más corto = respuesta más rápida.
        history = await self.bot.memory.history(scope, 8)
        # Sin el intent de miembros, `get_member()` puede venir vacío: se busca
        # al hablante entre los miembros del canal de voz y se pasa el canal.
        player = self.bot.players.get(session.guild_id)
        canal_voz = player.channel if player is not None else None
        if member is None and canal_voz is not None:
            member = next(
                (m for m in getattr(canal_voz, "members", []) if m.id == user_id), None
            )

        tools = MangoTools(
            self.bot,
            guild,
            member,
            session.text_channel,
            announce_tracks=False,
            voice_channel=canal_voz,
            request_hint=request,
        )

        # Controles instantáneos: «salta», «para», «pausa», «reanuda»… se
        # ejecutan directamente, sin consultar al modelo (respuesta inmediata y
        # sin riesgo de que se «pierda» preguntando qué suena).
        accion = control_de_voz(request)
        if accion is not None:
            if player is None:
                log.info("[voz] control %s sin reproductor activo", accion)
                return
            await self._ejecutar_control(player, accion)
            return

        # Búsqueda especulativa: se lanza el mismo tiempo que la consulta al
        # modelo. Si acaba pidiendo esa música, ya estará resuelta (≈1,3 s menos).
        sugerencia = limpiar_peticion(request)
        if es_peticion_musica(request) and len(sugerencia) >= 3:
            # Petición de música clara: se dice «¡Marchando!» al instante (audio
            # ya sintetizado) y la confirmación irá solo con título y artista.
            concreto = len(sugerencia.split()) >= 2
            if concreto:
                tools.con_apertura = False
            tools.prefetch = asyncio.create_task(
                self._prebuscar(sugerencia, user_id, name, tools)
            )
            if concreto and not await self._hablar_interjeccion(player):
                tools.con_apertura = True

        troceador = SentenceChunker()
        respuesta: list[str] = []
        primera = True

        try:
            async for delta in self.bot.llm.stream(
                history=[*history, {"role": "user", "content": request[:1000]}],
                system=personality.MANGO_VOICE_PERSONA,
                tools=MUSIC_TOOLS,
                tool_runner=tools.run,
                max_chars=self.bot.config.ai_max_reply_chars,
            ):
                respuesta.append(delta)
                for frase in troceador.push(delta):
                    if primera:
                        log.info("[voz] primera frase lista para hablar")
                        primera = False
                    await self._speak_sentence(player, frase)
        except LLMError as exc:
            log.warning("LLM falló: %s", exc)
            if not respuesta:
                await self._speak_sentence(
                    player, "Se me cruzaron los cables. Repítemelo, ¿sí?"
                )
            return
        finally:
            # Si al final no se pidió música, se descarta todo lo preparado.
            tools.cancel_background()

        for frase in troceador.flush():
            await self._speak_sentence(player, frase)

        texto = "".join(respuesta).strip()

        # Si la herramienta ya respondió (canción confirmada por voz, texto
        # dicho en alto…), no hay texto del modelo y **no** se dice «no te
        # entendí»: sería una incongruencia justo después de confirmar.
        if tools.handled_reply:
            log.info("[voz] respuesta gestionada por la herramienta; no se repite")
            await self.bot.memory.add(scope, "user", request)
            return

        if not texto:
            # Aquí sí: se oyó la petición pero el modelo no devolvió nada.
            await self._speak_sentence(player, personality.pick(personality.AI_NO_ENTENDI))
            return

        await self.bot.memory.add(scope, "user", request)
        await self.bot.memory.add(scope, "assistant", texto)

        # Lo hablado NO se publica en el chat (solo se registra en el log).
        # Con VOICE_POST_REPLIES=true vuelve a dejar la respuesta en el canal.
        if session.text_channel is not None and (
            self.bot.config.voice_post_replies
            or self.bot.config.voice_show_transcript
        ):
            if self.bot.config.voice_show_transcript:
                with contextlib.suppress(discord.HTTPException):
                    await session.text_channel.send(
                        embed=personality.ai_heard_embed(name, request)
                    )
            if self.bot.config.voice_post_replies:
                with contextlib.suppress(discord.HTTPException):
                    await session.text_channel.send(
                        embed=personality.ai_reply_embed(texto)
                    )

    async def _speak_sentence(self, player, texto: str) -> None:
        """Sintetiza una frase y la encola en el mezclador.

        Si el motor de voz permite streaming, el audio se va encolando según
        llega: Mango empieza a hablar sin esperar a terminar de generarla.
        """
        tts = self.bot.tts
        if tts is None or not texto.strip():
            return

        sink = self._sinks.get(getattr(player.guild, "id", 0))
        if sink is not None and hasattr(sink, "reset"):
            sink.reset()

        flujo = getattr(tts, "stream_pcm", None)
        try:
            if flujo is not None:
                primero = True
                async for bloque in flujo(texto):
                    if primero:
                        log.debug("[voz] primer audio sintetizado")
                        primero = False
                    player.speak(bloque)
                return

            pcm = await tts.synthesize(texto)
        except TTSError as exc:
            log.warning("TTS falló: %s", exc)
            return
        if pcm:
            player.speak(pcm)

    async def _speak(self, player, text: str) -> None:
        """Habla un texto completo (usado por `!ai say`)."""
        for frase in split_sentences(text, max_len=TTS_SENTENCE_CHARS):
            await self._speak_sentence(player, frase)

    async def precalentar_interjecciones(self) -> int:
        """Sintetiza las frases cortas **en paralelo** (al arrancar).

        Así, en cuanto terminas de hablar, Mango puede decir «¡Marchando!»,
        contestar a un saludo o confirmar un «salta» sin gastar ni un
        milisegundo en TTS.
        """
        if self.bot.tts is None:
            return 0

        pendientes: list[tuple[list[bytes], str]] = []
        if not self._interjecciones:
            pendientes += [(self._interjecciones, f) for f in personality.INTERJECCIONES]
        if not self._saludos:
            pendientes += [(self._saludos, f) for f in personality.AI_GREETINGS]
        for accion, frases in personality.AI_CONTROLES.items():
            if self._controles.get(accion):
                continue
            destino = self._controles.setdefault(accion, [])
            pendientes += [(destino, f) for f in frases]

        if not pendientes:
            return len(self._interjecciones)

        # En paralelo (con límite para no saturar el servicio de voz).
        limite = asyncio.Semaphore(5)

        async def una(destino: list[bytes], frase: str) -> None:
            async with limite:
                try:
                    pcm = await self.bot.tts.synthesize(frase)
                except Exception:
                    log.debug("No pude pregenerar %r", frase, exc_info=True)
                    return
                if pcm:
                    destino.append(pcm)

        inicio = time.perf_counter()
        await asyncio.gather(*(una(destino, frase) for destino, frase in pendientes))

        total_controles = sum(len(v) for v in self._controles.values())
        log.info(
            "Frases cortas listas en %.1fs (%s interjecciones · %s saludos · %s controles)",
            time.perf_counter() - inicio,
            len(self._interjecciones),
            len(self._saludos),
            total_controles,
        )
        return len(self._interjecciones)

    def _interjeccion(self) -> Optional[bytes]:
        """Siguiente interjección pregenerada (rotando), o None."""
        if not self._interjecciones:
            return None
        pcm = self._interjecciones[self._interjeccion_idx % len(self._interjecciones)]
        self._interjeccion_idx += 1
        return pcm

    async def _hablar_interjeccion(self, player) -> bool:
        """Dice «¡Marchando!» al instante. True si sonó."""
        pcm = self._interjeccion()
        if pcm is None:
            await self.precalentar_interjecciones()
            pcm = self._interjeccion()
        if pcm is None:
            return False
        player.speak(pcm)
        return True

    async def _hablar_saludo(self, player) -> bool:
        """Contesta a un saludo al instante. True si sonó."""
        if not self._saludos:
            await self.precalentar_interjecciones()
        if not self._saludos:
            return False
        pcm = self._saludos[self._saludo_idx % len(self._saludos)]
        self._saludo_idx += 1
        player.speak(pcm)
        return True

    async def _hablar_control(self, player, accion: str) -> bool:
        """Confirma una orden de control al instante. True si sonó."""
        if not self._controles:
            await self.precalentar_interjecciones()
        frases = self._controles.get(accion) or self._controles.get("nada") or []
        if not frases:
            return False
        player.speak(frases[self._control_idx % len(frases)])
        self._control_idx += 1
        return True

    async def _ejecutar_control(self, player, accion: str) -> None:
        """Ejecuta skip/stop/pause/resume **sin** pasar por el modelo."""
        hecho = True
        if accion == "skip":
            hecho = await player.skip()
        elif accion == "stop":
            await player.stop()
            player.clear_speech()
        elif accion == "pause":
            hecho = player.pause()
        elif accion == "resume":
            hecho = player.resume()

        log.info("[voz] control %s -> %s", accion, "ok" if hecho else "nada que hacer")
        await self._hablar_control(player, accion if hecho else "nada")

    async def speak_text(self, player, text: str) -> bool:
        """Dice un texto en voz alta. Devuelve True si llegó a hablar.

        Lo usan `!ai say`, `!mango di …` y la herramienta `say_text` de la IA.
        """
        limpio = " ".join((text or "").split())
        if not limpio or self.bot.tts is None:
            return False
        if player is None or not player.connected:
            return False
        await self._speak(player, limpio[:300])
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIVoice(bot))
