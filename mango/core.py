"""Clase principal del bot y registro de extensiones (cogs)."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from mango.config import Config
from mango.db import MemoryStore
from mango.services.dave import install as install_dave_patch
from mango.services.llm import LLMRouter, LLMService
from mango.services.lyrics import LyricsService
from mango.services.spotify import SpotifyService
from mango.services.stt import build_stt, build_wake_stt
from mango.services.tts import build_tts
from mango.services.ytdlp import YTDLPService
from mango.state import GuildPlayer

log = logging.getLogger(__name__)

INITIAL_EXTENSIONS = (
    "mango.cogs.events",
    "mango.cogs.utility",
    "mango.cogs.music",
    "mango.cogs.ai_chat",
    "mango.cogs.ai_voice",
    "mango.cogs.slash",
)


class MangoBot(commands.Bot):
    """Bot de Discord con estado aislado por servidor."""

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=intents,
            owner_ids=set(config.owner_ids) or None,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            # Nunca permitimos que un texto haga ping a @everyone o a roles.
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=True, replied_user=False
            ),
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="🥭 pide con !help"
            ),
        )

        self.config = config
        self.players: dict[int, GuildPlayer] = {}

        self.ytdlp = YTDLPService(cookies_file=config.cookies_path)
        self.spotify = SpotifyService(
            config.spotify_client_id, config.spotify_client_secret
        )
        self.lyrics = LyricsService(
            config.genius_token,
            client_id=config.genius_client_id,
            client_secret=config.genius_client_secret,
        )

        # ---- Mango AI ----
        self.memory = MemoryStore()
        self.llm = self._build_llm(config)
        self.stt = build_stt(config)
        self.wake_stt = build_wake_stt(config, main=self.stt)
        self.tts = build_tts(config)

    @staticmethod
    def _build_llm(config: Config) -> LLMService | LLMRouter | None:
        """Proveedor principal + respaldo opcional (cadena de fallback)."""
        if not config.ai_enabled:
            return None

        services = [
            LLMService(
                base_url=config.llm_base_url,
                api_key=config.llm_api_key,
                model=config.llm_model,
                temperature=config.llm_temperature,
                reasoning_effort=config.llm_reasoning_effort,
            )
        ]

        if config.llm_fallback_enabled:
            services.append(
                LLMService(
                    base_url=config.llm_fallback_base_url or "https://api.openai.com/v1",
                    api_key=config.llm_fallback_api_key,
                    model=config.llm_fallback_model,
                    temperature=config.llm_temperature,
                )
            )

        return services[0] if len(services) == 1 else LLMRouter(services)

    def _llm_chain(self) -> list[str]:
        """Modelos en uso, en orden de prioridad (para logs y estado)."""
        chain = getattr(self.llm, "chain", None)
        if chain:
            return list(chain)
        return [self.config.llm_model] if self.config.llm_model else []

    # ---------------------------------------------------------
    # Ciclo de vida
    # ---------------------------------------------------------
    async def setup_hook(self) -> None:
        # Descifrado DAVE/E2EE para la voz entrante (voice_recv no lo trae)
        from mango.services.dave import disable as disable_dave

        if self.config.voice_dave == "off":
            disable_dave()
        else:
            install_dave_patch()

        # Precalienta los modelos de voz en segundo plano: así la primera
        # respuesta no paga la carga del modelo (varios segundos). Se lanza
        # después de cargar los cogs para poder pregenerar las interjecciones.
        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
            log.info("Extensión cargada: %s", extension)

        if self.config.voice_enabled:
            asyncio.create_task(self._warmup_voice())

        # Estado limpio al arrancar: sin historial de conversación ni colas
        # heredadas. Así el bot no «recuerda» la última canción pedida.
        if self.config.clear_memory_on_start:
            try:
                borrados = await self.memory.clear_all()
                log.info("Historial de conversación borrado al arrancar (%s mensajes)", borrados)
            except Exception:
                log.debug("No pude limpiar el historial al arrancar", exc_info=True)

        # Comandos de barra diagonal (/clear…). Se registran globalmente; con
        # `!sync` (dueño) se fuerzan en el servidor actual al instante.
        await self._sync_slash_commands()

    async def _sync_slash_commands(self) -> None:
        """Publica los comandos de barra en Discord."""
        try:
            comandos = await self.tree.sync()
        except Exception:
            log.exception("No pude sincronizar los comandos de barra")
            return
        log.info(
            "Comandos de barra sincronizados: %s (%s)",
            len(comandos),
            ", ".join(f"/{c.name}" for c in comandos) or "ninguno",
        )

    async def _warmup_voice(self) -> None:
        # El LLM también: así la primera respuesta no paga DNS/TLS ni el
        # arranque en frío del modelo (unos cientos de ms).
        if self.llm is not None:
            try:
                await self.llm.reply(
                    history=[{"role": "user", "content": "hola"}], max_chars=5
                )
                log.info("Modelo de lenguaje listo: %s", self.config.llm_model)
            except Exception:
                log.debug("No pude precalentar el LLM", exc_info=True)

        # El TTS abre conexión la primera vez: se calienta con una palabra.
        if self.tts is not None:
            try:
                await self.tts.synthesize("Listo.")
                log.info("Voz lista (TTS): %s", getattr(self.tts, "label", "?"))
            except Exception:
                log.debug("No pude precalentar el TTS", exc_info=True)

        for nombre, servicio in (("STT", self.stt), ("wake", self.wake_stt)):
            calentar = getattr(servicio, "warmup", None)
            if calentar is None:
                continue
            try:
                await calentar()
                log.info("Modelo de voz listo (%s): %s", nombre, getattr(servicio, "label", "?"))
            except Exception:
                log.debug("No pude precalentar %s", nombre, exc_info=True)

        # Interjecciones («¡Marchando!»…) ya sintetizadas: respuesta instantánea.
        cog = self.get_cog("AIVoice")
        precalentar = getattr(cog, "precalentar_interjecciones", None)
        if precalentar is not None:
            try:
                await precalentar()
            except Exception:
                log.debug("No pude pregenerar las interjecciones", exc_info=True)

        if not self.config.spotify_enabled:
            log.warning("Spotify desactivado (faltan credenciales en .env)")
        if not self.config.lyrics_enabled:
            log.warning("Genius/letras desactivado (falta GENIUS_TOKEN en .env)")

        if not self.config.ai_enabled:
            log.warning("Mango AI desactivado (falta LLM_API_KEY en .env)")
        else:
            log.info("Mango AI listo · modelo %s", " → ".join(self._llm_chain()))
            log.info(
                "Voz: STT=%s (%s) · TTS=%s (%s)%s",
                self.config.stt_provider,
                getattr(self.stt, "label", "no disponible"),
                self.config.tts_provider,
                getattr(self.tts, "label", "no disponible"),
                "" if self.config.ai_channel_id else " · sin AI_CHANNEL_ID",
            )
            if not self.config.voice_enabled:
                log.warning(
                    "Charla por voz desactivada: revisa STT/TTS en el .env "
                    "(¿falta STT_API_KEY?)"
                )

        if not self.config.owner_ids:
            log.info(
                "OWNER_IDS vacío: el dueño se detectará automáticamente "
                "desde la aplicación de Discord."
            )

    async def close(self) -> None:
        for player in list(self.players.values()):
            try:
                await player.disconnect()
            except Exception:
                log.debug("Error cerrando reproductor", exc_info=True)
        self.players.clear()
        try:
            self.memory.close()
        except Exception:
            log.debug("No pude cerrar la memoria", exc_info=True)
        await super().close()

    # ---------------------------------------------------------
    # Estado por servidor
    # ---------------------------------------------------------
    def get_player(self, guild: discord.Guild) -> GuildPlayer:
        player = self.players.get(guild.id)
        if player is None:
            player = GuildPlayer(self, guild)
            self.players[guild.id] = player
            log.debug("Nuevo reproductor para %s (%s)", guild.name, guild.id)
        return player

    async def dispatch_voice_connected(self, guild: discord.Guild) -> None:
        """Avisa a los cogs de que el bot acaba de entrar a un canal de voz.

        Se usa para armar la escucha de Mango AI sin depender solo del evento
        ``on_voice_state_update`` del gateway.
        """
        await self._dispatch_voice_event("on_voice_connected", guild)

    async def dispatch_voice_disconnected(self, guild: discord.Guild) -> None:
        """Avisa a los cogs de que el bot salió del canal de voz."""
        await self._dispatch_voice_event("on_voice_disconnected", guild)

    async def _dispatch_voice_event(self, name: str, guild: discord.Guild) -> None:
        for cog in list(self.cogs.values()):
            handler = getattr(cog, name, None)
            if handler is None:
                continue
            try:
                await handler(guild)
            except Exception:
                log.exception("Error en %s de %s", name, type(cog).__name__)

    def drop_player(self, guild: discord.Guild) -> None:
        player = self.players.pop(guild.id, None)
        if player is not None:
            player.mark_disconnected()
