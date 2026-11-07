"""Ejecutor de herramientas de Mango AI.

Traduce las llamadas del modelo (function calling) a acciones reales sobre
el reproductor del servidor: reproducir, saltar, parar, consultar cola…
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections import deque
from typing import Any, Optional

import discord

from mango import personality
from mango.services.texto import normalizar as _normalizar
from mango.services.texto import (
    peticion_compatible,
    pide_musica,
    separar_titulo_artista,
    titulo_normalizado,
)
from mango.state import Track

log = logging.getLogger(__name__)


class PreparedSpeech:
    """Voz que se sintetiza y se reproduce a la vez (sin esperar al final)."""

    def __init__(self) -> None:
        self._cola: deque[bytes] = deque()
        self._aviso = asyncio.Event()
        self._fin = False

    def push(self, trozo: bytes) -> None:
        if trozo:
            self._cola.append(trozo)
            self._aviso.set()

    def close(self) -> None:
        self._fin = True
        self._aviso.set()

    @property
    def finished(self) -> bool:
        return self._fin and not self._cola

    async def next_chunk(self, timeout: float = 1.5) -> bytes:
        """Siguiente trozo; vacío si terminó o si se agota el tiempo."""
        while True:
            if self._cola:
                return self._cola.popleft()
            if self._fin:
                return b""
            self._aviso.clear()
            try:
                await asyncio.wait_for(self._aviso.wait(), timeout=timeout)
            except TimeoutError:
                return b""


class MangoTools:
    """Herramientas disponibles para el LLM dentro de un servidor."""

    def __init__(
        self,
        bot: Any,
        guild: discord.Guild,
        member: Optional[discord.Member],
        text_channel: Optional[discord.abc.Messageable] = None,
        announce_tracks: bool = True,
        voice_channel: Optional[discord.abc.GuildChannel] = None,
        request_hint: str = "",
    ) -> None:
        self.bot = bot
        self.guild = guild
        self.member = member
        self.text_channel = text_channel
        # Canal de voz de referencia: sin el intent de miembros, `get_member()`
        # puede devolver None, pero el canal se deduce del estado de voz igual.
        self.voice_channel = voice_channel
        # Lo que dijo el usuario, por si la IA recorta la petición.
        self.request_hint = request_hint
        # En voz el bot confirma la canción hablando y el modelo no repite nada.
        self.speak_confirmations = not announce_tracks
        self.handled_reply = False
        # Si ya se dijo una interjección («¡Marchando!»), la confirmación va
        # solo con el título y el artista (no se repite la apertura).
        self.con_apertura = True
        # En la voz no se anuncia la canción en el chat (ya la comenta hablando).
        self.announce_tracks = announce_tracks
        # Búsqueda ya lanzada en paralelo (ahorra ~1,3 s de la ruta crítica).
        self.prefetch: Optional[asyncio.Task] = None
        # Confirmación hablada ya sintetizada de la prebúsqueda.
        self._prepared: Optional[tuple[str, asyncio.Task]] = None

    @property
    def player(self):
        return self.bot.get_player(self.guild)

    async def run(self, name: str, arguments: dict[str, Any]) -> str:
        handler = {
            "play_music": self._play,
            "skip_music": self._skip,
            "stop_music": self._stop,
            "now_playing": self._now_playing,
            "queue_info": self._queue,
            "search_lyrics": self._lyrics,
            "leave_voice": self._leave_voice,
            "join_voice": self._join_voice,
            "say_text": self._say,
        }.get(name)

        if handler is None:
            return f"No existe la herramienta {name}."
        try:
            return await handler(**(arguments or {}))
        except TypeError as exc:
            log.warning("Argumentos inválidos para %s: %s", name, exc)
            return "Me faltan datos para hacer eso."

    # ---------------------------------------------------------
    # Música
    # ---------------------------------------------------------
    _VERBOS = re.compile(
        r"(?i)^(?:(?:oye|hey|hola|escucha|mango|por\s+favor)[,\s]+)*"
        r"(?:pon|ponme|poner|reproduce|reproducir|toca|tocar|escucha|escuchar|"
        r"añade|anade|agrega|encola|quiero|dame|busca)"
        r"(?:\s+(?:la|el|un|una|algo\s+de|un\s+poco\s+de|m[uú]sica\s+de|tema\s+de))?\s+"
    )

    @classmethod
    def _limpiar_peticion(cls, texto: str) -> str:
        """Quita el «oye Mango, pon…» inicial y deja lo que se quiere oír."""
        limpio = cls._VERBOS.sub("", (texto or "").strip(), count=1)
        return limpio.strip(" ,.;:¡!¿?")

    def _query_util(self, query: str) -> str:
        """Si la IA recortó la petición (p. ej. «avalon»), se recupera el texto
        completo del usuario («avalon suicideboys») para buscar mejor."""
        if not self.request_hint:
            return query
        sugerencia = self._limpiar_peticion(self.request_hint)
        if (
            len(query.split()) == 1
            and len(sugerencia.split()) > 1
            and _normalizar(query) in _normalizar(sugerencia)
        ):
            log.info("La IA recortó la petición: %r → uso %r", query, sugerencia)
            return sugerencia
        return query

    async def _play(self, query: str = "") -> str:
        query = self._query_util((query or "").strip())
        if not query:
            return "Me falta el nombre de la canción."

        # Barrera determinista: solo se reproduce si el usuario pidió música en
        # esta misma frase. Así el modelo no puede «repetir la última canción»
        # al saludar o al hablar de otra cosa.
        if not pide_musica(self.request_hint or query):
            log.info("play_music: bloqueado (la frase no pide música): %r", self.request_hint)
            return (
                "Esa frase no me pide música, así que no pongo nada. "
                "Dime qué te pongo si quieres que suene algo."
            )

        voice = getattr(self.member, "voice", None) if self.member else None
        channel = getattr(voice, "channel", None) or self.voice_channel
        if channel is None:
            return (
                "El usuario no está en un canal de voz, así que no puedo "
                "reproducir. Pídele que entre a uno."
            )

        player = self.player
        if player.text_channel is None and self.text_channel is not None:
            player.text_channel = self.text_channel

        log.info("play_music: buscando %r", query)
        if not player.connected:
            try:
                await player.connect(channel)
            except Exception as exc:  # VoiceError del handshake de voz
                log.warning("play_music: no pude entrar al canal: %s", exc)
                return f"No pude entrar al canal de voz: {exc}"
        elif player.channel is not None and player.channel != channel and player.is_active:
            return "Estoy ocupado sonando en otro canal; no me cambio a mitad de canción."

        track = None
        # Si ya hay una búsqueda especulativa en marcha y pide lo mismo, se
        # reutiliza: no se paga otra vez el coste de YouTube.
        if self.prefetch is not None:
            tarea, self.prefetch = self.prefetch, None
            if peticion_compatible(query, self.request_hint):
                try:
                    track = await tarea
                except asyncio.CancelledError:
                    track = None
                except Exception:
                    log.debug("La prebúsqueda falló", exc_info=True)
                    track = None
            else:
                tarea.cancel()

        if track is None:
            track = await self.bot.ytdlp.search(
                query,
                requester_id=getattr(self.member, "id", 0),
                requester_name=getattr(self.member, "display_name", "alguien"),
            )
        if track is None:
            return f"No encontré nada para «{query}»."
        log.info("play_music: elegido %r", track.title)

        repetida = player.find_duplicate(track)
        if repetida is not None:
            existente, posicion = repetida
            donde = (
                "ya está sonando"
                if posicion == 0
                else f"ya está en la cola (posición {posicion})"
            )
            return f"«{existente.title}» {donde}; no la añado otra vez."

        position = player.enqueue(track, max_size=self.bot.config.max_queue)
        if position is None:
            return "La cola está llena; no puedo añadir más."

        if not (player.is_playing or player.is_paused):
            empezo = True
            if not self.announce_tracks:
                player.silent_next_track = True
            await player.play_next()
        else:
            empezo = False

        # En voz, el propio bot confirma la canción hablando: la respuesta es
        # inmediata y no depende de que el modelo repita el título.
        if self.speak_confirmations and await self._confirmar_en_voz(player, track, empezo):
            self.handled_reply = True
            return f"Ya confirmaste por voz «{track.title}»; no digas nada más."

        if empezo:
            return f"Listo: «{track.title}», ya está sonando."
        return f"Añadida «{track.title}» (posición {position} en la cola)."

    def prepare_confirmation(self, track: Track) -> None:
        """Deja lista la voz de «Voy con X» mientras el modelo sigue pensando."""
        tts = getattr(self.bot, "tts", None)
        if tts is None or not self.speak_confirmations:
            return
        frase = self._frase_confirmacion(track, empezo=True)
        preparada = PreparedSpeech()
        tarea = asyncio.create_task(self._sintetizar(tts, frase, preparada))
        self._prepared = (titulo_normalizado(track.title), preparada, tarea)

    def cancel_background(self) -> None:
        """Descarta la prebúsqueda y la voz preparada si al final no se usan."""
        if self.prefetch is not None:
            self.prefetch.cancel()
            self.prefetch = None
        if self._prepared is not None:
            self._prepared[2].cancel()
            self._prepared = None

    async def _sintetizar(self, tts, frase: str, preparada: PreparedSpeech) -> None:
        """Vuelca la voz en `preparada` según llega. Nunca lanza."""
        try:
            flujo = getattr(tts, "stream_pcm", None)
            if flujo is not None:
                async for bloque in flujo(frase):
                    preparada.push(bloque)
            else:
                pcm = await tts.synthesize(frase)
                preparada.push(pcm or b"")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("No pude preparar la confirmación", exc_info=True)
        finally:
            preparada.close()

    async def _seguir_hablando(self, player, preparada: PreparedSpeech) -> None:
        """Suelta el resto de la frase preparada sin bloquear."""
        while not preparada.finished:
            trozo = await preparada.next_chunk(2.0)
            if trozo:
                player.speak(trozo)

    def _frase_confirmacion(self, track: Track, *, empezo: bool) -> str:
        """Frase de locutor: «¡Marchando! "Tren Al Sur", de Los Prisioneros.»"""
        titulo, artista = separar_titulo_artista(track.title)
        frase = personality.linea_locutor(
            titulo or track.title,
            artista,
            a_la_cola=not empezo,
            con_apertura=self.con_apertura,
        )
        return frase[:200]

    async def _confirmar_en_voz(self, player, track: Track, empezo: bool) -> bool:
        """Dice en voz alta qué canción se pone. Devuelve True si habló."""
        tts = getattr(self.bot, "tts", None)
        if tts is None:
            return False

        frase = self._frase_confirmacion(track, empezo=empezo)

        # Si la prebúsqueda ya sintetizó la voz («Voy con X»), se usa tal cual:
        # el usuario la oye sin esperar nada.
        preparada = self._prepared
        if preparada is not None:
            self._prepared = None
            clave, voz, tarea = preparada
            if clave == titulo_normalizado(track.title) and empezo:
                primero = await voz.next_chunk(2.5)
                if primero:
                    player.speak(primero)
                    asyncio.create_task(self._seguir_hablando(player, voz))
                    log.info("Confirmado por voz (preparado): %r", frase)
                    return True
            tarea.cancel()

        try:
            flujo = getattr(tts, "stream_pcm", None)
            if flujo is not None:
                emitido = False
                async for bloque in flujo(frase):
                    if bloque:
                        emitido = True
                        player.speak(bloque)
                if emitido:
                    log.info("Confirmado por voz: %r", frase)
                return emitido

            pcm = await tts.synthesize(frase)
        except Exception:
            log.debug("No pude confirmar por voz la canción", exc_info=True)
            return False
        if not pcm:
            return False
        player.speak(pcm)
        log.info("Confirmado por voz: %r", frase)
        return True

    def _solo_oyentes(self) -> Optional[str]:
        """Solo quien está escuchando puede controlar la música.

        Misma regla que los comandos de texto (`_require_listening`): sin esto,
        cualquiera desde el canal de IA podría saltar, parar o echar al bot.
        Si no se conoce al hablante (ruta de voz sin caché de miembros) se
        permite: el audio llega del propio canal del bot.
        """
        player = self.player
        if not player.connected:
            return "No estoy en ningún canal de voz."
        if self.member is None:
            return None
        escuchando = (
            getattr(getattr(self.member, "voice", None), "channel", None)
            == player.channel
        )
        if not escuchando:
            return (
                "Solo quien está en mi canal de voz puede controlar la música. "
                "Entra al canal y vuelve a pedírmelo."
            )
        return None

    async def _skip(self) -> str:
        player = self.player
        negativa = self._solo_oyentes()
        if negativa:
            return negativa
        if not await player.skip():
            return "Ahora mismo no hay nada sonando, así que no hay nada que saltar."
        next_title = player.queue[0].title if player.queue else None
        if next_title:
            return f"Saltada. Ahora suena «{next_title}»."
        return "Saltada. No queda nada más en la cola."

    async def _stop(self) -> str:
        player = self.player
        negativa = self._solo_oyentes()
        if negativa:
            return negativa
        await player.stop()
        player.clear_speech()
        return "Música detenida y cola vaciada."

    async def _now_playing(self) -> str:
        player = self.player
        if player.current is None:
            ultimo = getattr(player, "last_track", None)
            if ultimo is not None:
                return f"Ahora mismo no suena nada. La última fue «{ultimo.title}»."
            return "No hay nada sonando en este servidor."
        estado = "en pausa" if player.is_paused else "sonando"
        puesto = ""
        if player.queue:
            puesto = f" Quedan {len(player.queue)} en la cola."
        return (
            f"«{player.current.title}» {estado} ({player.current.duration_str}).{puesto}"
        )

    async def _queue(self) -> str:
        player = self.player
        pending = list(player.queue)
        if not pending:
            return "La cola está vacía."
        names = "; ".join(track.title for track in pending[:5])
        extra = f" y {len(pending) - 5} más" if len(pending) > 5 else ""
        return f"{len(pending)} canciones en cola: {names}{extra}."

    async def _decir_permitido(self) -> Optional[str]:
        """¿Puede quien lo pide hacer que Mango hable en voz alta?

        Devuelve un mensaje de negativa, o None si está permitido.
        """
        if not self.bot.config.voice_say_public:
            es_dueno = False
            with contextlib.suppress(Exception):
                es_dueno = await self.bot.is_owner(self.member)
            if not es_dueno:
                return (
                    "Eso solo lo puede pedir el dueño del bot "
                    "(o activar VOICE_SAY_PUBLIC=true en el .env)."
                )
        return self._solo_oyentes()

    async def _say(self, texto: str = "") -> str:
        """Dice en voz alta el texto indicado (como un locutor)."""
        limpio = " ".join((texto or "").split())
        if not limpio:
            return "Me falta el texto que quieres que diga."

        negativa = await self._decir_permitido()
        if negativa:
            return negativa

        cog = self.bot.get_cog("AIVoice")
        if cog is None or not hasattr(cog, "speak_text"):
            return "Ahora mismo no puedo hablar por voz."

        hablado = await cog.speak_text(self.player, limpio[:300])
        if not hablado:
            return "No me salió la voz; prueba otra vez."
        # Ya lo dijo en voz alta: el modelo no tiene que repetirlo por texto.
        self.handled_reply = True
        return "Dicho en voz alta."

    async def _join_voice(self) -> str:
        """Entra (o se cambia) al canal de voz del usuario."""
        canal = getattr(getattr(self.member, "voice", None), "channel", None)
        if canal is None:
            canal = self.voice_channel
        if canal is None:
            return (
                "El usuario no está en ningún canal de voz, así que no sé a "
                "dónde ir. Pídele que entre a uno y lo repita."
            )

        player = self.player
        if player.connected and player.channel == canal:
            return f"Ya estoy en «{canal.name}», te escucho."

        try:
            await player.connect(canal)
        except Exception as exc:  # VoiceError del handshake
            log.warning("join_voice: no pude entrar a %s: %s", canal, exc)
            return f"No pude entrar al canal: {exc}"

        return f"Ya estoy en «{canal.name}»; te escucho."

    async def _leave_voice(self) -> str:
        """Se despide hablando y sale del canal (lo pide el usuario)."""
        player = self.player
        negativa = self._solo_oyentes()
        if negativa:
            return negativa

        with contextlib.suppress(Exception):
            if getattr(self.bot, "tts", None) is not None:
                pcm = await self.bot.tts.synthesize(
                    "Vale, me salgo del canal. ¡Hasta luego!"
                )
                player.speak(pcm)

        asyncio.create_task(self._salir_al_terminar(player))
        return "Me estoy despidiendo y salgo del canal de voz."

    @staticmethod
    async def _salir_al_terminar(player) -> None:
        """Espera a que acabe la despedida y desconecta."""
        await asyncio.sleep(0.5)
        for _ in range(60):
            if not player.is_speaking:
                break
            await asyncio.sleep(0.2)
        with contextlib.suppress(Exception):
            await player.disconnect()

    async def _lyrics(self, song: str = "") -> str:
        player = self.player
        query = (song or "").strip()
        if not query and isinstance(player.current, Track):
            query = player.current.title
        if not query:
            return "Necesito el nombre de una canción."

        if not getattr(self.bot, "lyrics", None) or not self.bot.lyrics.enabled:
            return "El módulo de letras está desactivado en este bot."

        try:
            result = await self.bot.lyrics.fetch(query)
        except Exception:
            log.exception("Fallo buscando letras")
            return "No pude consultar Genius ahora mismo."

        if result is None:
            return f"No encontré la letra de «{query}»."
        title, text = result
        return f"Letra de «{title}»:\n{text[:900]}"
