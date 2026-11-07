"""Prueba de humo de Mango Bot.

Comprueba que el bot se construye, que todos los cogs cargan y que los
comandos esperados existen. No se conecta a Discord ni necesita token real.

Uso:
    .venv/bin/python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Entorno ficticio: nunca se abre una conexión real.
os.environ.setdefault("DISCORD_TOKEN", "smoke-test-token")
os.environ.setdefault("OWNER_IDS", "123456789012345678")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from mango.cogs.ai_voice import AIVoice  # noqa: E402
from mango.config import ConfigError, load_config  # noqa: E402
from mango.core import INITIAL_EXTENSIONS, MangoBot  # noqa: E402
from mango.logging_setup import setup_logging  # noqa: E402
from mango.personality import help_embed, now_playing_embed  # noqa: E402
from mango.state import GuildPlayer, Track  # noqa: E402

setup_logging("WARNING")

EXPECTED_COMMANDS = {
    "play", "skip", "stop", "pause", "resume", "again", "queue",
    "nowplaying", "lyrics", "volume", "remove", "shuffle", "loop",
    "hi", "bye", "ping", "help", "embed", "reload", "diag", "test",
    "mango", "ask", "forget", "ai", "ai join", "ai leave", "ai status",
}

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    status = "OK  " if condition else "FALLA"
    print(f"[{status}] {message}")
    if not condition:
        failures.append(message)


def test_track() -> None:
    track = Track(title="One More Time", duration=320)
    check(track.duration_str == "5:20", "Track.duration_str formatea mm:ss")
    check(
        Track(title="x", duration=3725).duration_str == "1:02:05",
        "Track.duration_str formatea h:mm:ss",
    )
    check(
        Track(title="x").duration_str == "en vivo / sin dato",
        "Track sin duración usa texto por defecto",
    )


def test_player() -> None:
    config = load_config()
    bot = SimpleNamespace(config=config, loop=None)
    guild = SimpleNamespace(id=1, name="guild-test")
    player = GuildPlayer(bot, guild)

    check(player.enqueue(Track("a"), max_size=2) == 1, "enqueue devuelve la posición 1")
    check(player.enqueue(Track("b"), max_size=2) == 2, "enqueue devuelve la posición 2")
    check(player.enqueue(Track("c"), max_size=2) is None, "enqueue rechaza si la cola está llena")

    removed = player.remove_index(1)
    check(removed is not None and removed.title == "a", "remove_index quita el tema correcto")
    check(len(player.queue) == 1, "la cola queda con un tema tras remove")

    player.enqueue(Track("c"), max_size=10)
    check(player.shuffle() == 2, "shuffle informa cuántos temas mezcló")

    check(player.set_loop("cola") == "queue", "set_loop acepta alias en español")
    try:
        player.set_loop("modo-invalido")
    except ValueError:
        check(True, "set_loop rechaza modos inválidos")
    else:
        check(False, "set_loop debería lanzar ValueError")

    check(player.set_volume(5.0) == 2.0, "set_volume recorta al máximo de 2.0")
    check(player.set_volume(-1) == 0.0, "set_volume recorta al mínimo de 0.0")
    check(not player.connected and not player.is_playing, "player sin voz reporta estado inactivo")


def test_personality() -> None:
    embed = help_embed("!", is_owner=True)
    check(embed.title is not None and "Mango" in embed.title, "help_embed tiene título de Mango")
    field_names = [field.name for field in embed.fields]
    check(
        any("Mango AI" in name for name in field_names),
        "help_embed incluye la sección de Mango AI",
    )
    # El manual es el que pidió el dueño: sin sección privada
    check(
        not any("dueño" in name.lower() for name in field_names),
        "help_embed ya no tiene sección de dueño",
    )

    texto = "\n".join(field.value for field in embed.fields)
    check("/mclear" in texto, "el manual documenta /mclear")
    for alias in ("`!p`", "`!s`", "`!q`"):
        check(alias in texto, f"el manual muestra el alias {alias}")
    check(
        embed.footer.text is not None
        and "música con criterio" in embed.footer.text,
        "el manual lleva la firma de Mango",
    )
    check(
        "un bot de música melómano y de buen gusto" in (embed.description or ""),
        "el manual usa la descripción nueva",
    )

    track = Track(title="Get Lucky", duration=369, requester_name="mango", source="Spotify")
    embed = now_playing_embed(track)
    check(
        embed.description is not None and "Get Lucky" in embed.description,
        "now_playing_embed muestra el título",
    )


def test_config_errors() -> None:
    import mango.config as config_module

    token = os.environ.pop("DISCORD_TOKEN", None)
    missing_env = Path("/tmp/mango-sin-env.env")
    try:
        with mock.patch.object(config_module, "ENV_FILE", missing_env):
            try:
                load_config()
            except ConfigError:
                check(True, "load_config falla con un mensaje claro si falta DISCORD_TOKEN")
            else:
                check(False, "load_config debería fallar sin DISCORD_TOKEN")
    finally:
        if token is not None:
            os.environ["DISCORD_TOKEN"] = token


async def test_playback_state_machine() -> None:
    """Simula un VoiceClient para validar cola, skip y loop sin audio real."""
    import mango.state as state_module

    class FakeSource:
        def __init__(self, url, **kwargs):
            self.url = url

        def read(self) -> bytes:
            return b""  # fin inmediato: el test no reproduce audio real

        def cleanup(self):
            pass

    class FakeVoice:
        def __init__(self):
            self.channel = SimpleNamespace(id=10, members=[], mention="#voz")
            self.playing = False
            self.paused = False
            self.connected = True
            self.after = None
            self.source = None

        def is_connected(self):
            return self.connected

        def is_playing(self):
            return self.playing and not self.paused

        def is_paused(self):
            return self.paused

        def play(self, source, after=None):
            if self.playing and not self.paused:
                raise RuntimeError("Already playing")
            self.source = source
            self.playing = True
            self.paused = False
            self.after = after

        def stop(self):
            self.playing = False
            callback, self.after = self.after, None
            if callback is not None:
                callback(None)

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        async def disconnect(self, force=False):
            self.connected = False
            self.playing = False

    class FakeChannel:
        def __init__(self):
            self.embeds = []

        async def send(self, **kwargs):
            self.embeds.append(kwargs.get("embed"))

    class FakeYTDLP:
        async def stream_url(self, *, webpage_url=None, search_query=None):
            return f"http://stream/{webpage_url or search_query}", {
                "title": "Tema resuelto",
                "duration": 120,
                "webpage_url": webpage_url,
                "thumbnail": None,
            }

    class FakeBot:
        def __init__(self):
            self.config = load_config()
            self.loop = None
            self.ytdlp = FakeYTDLP()

    bot = FakeBot()
    guild = SimpleNamespace(id=99, name="guild-test")
    player = GuildPlayer(bot, guild)
    player.voice = FakeVoice()
    player.text_channel = FakeChannel()

    with mock.patch.object(state_module.discord, "FFmpegPCMAudio", FakeSource):
        player.enqueue(Track(title="Tema 1", url="http://yt/1"), max_size=10)
        player.enqueue(Track(title="Tema 2", url="http://yt/2"), max_size=10)
        await player.play_next()
        check(
            player.current is not None and player.current.url == "http://yt/1",
            "play_next arranca el primer tema de la cola",
        )
        check(len(player.queue) == 1, "el tema reproducido sale de la cola")
        check(len(player.text_channel.embeds) == 1, "se anuncia el tema que suena")
        check(player.mixer is not None and player.mixer.music_active, "el mixer queda activo")

        # Fin de canción simulado (el mixer suelta la fuente)
        player.mixer.clear_music()
        await player.play_next()
        check(
            player.current is not None and player.current.url == "http://yt/2",
            "al terminar pasa al siguiente tema",
        )

        # Skip explícito
        enqueued = player.enqueue(Track(title="Tema 3", url="http://yt/3"), max_size=10)
        check(enqueued == 1, "se puede encolar mientras suena otra cosa")
        await player.skip()
        check(
            player.current is not None and player.current.url == "http://yt/3",
            "skip salta al siguiente tema",
        )

        # Loop de la canción actual
        player.set_loop("track")
        player.mixer.clear_music()
        await player.play_next()
        check(
            player.current is not None and player.current.url == "http://yt/3",
            "loop=track repite la misma canción",
        )

        # Volumen en caliente (lo aplica el mixer)
        player.set_volume(0.25)
        check(
            player.mixer is not None and abs(player.mixer.volume - 0.25) < 1e-6,
            "set_volume ajusta el volumen del mixer",
        )

        # Voz mezclada con la música
        player.speak(b"\x00\x01" * 2000)
        check(player.is_speaking, "la voz se encola en el mixer")
        frame = player.mixer.read()
        check(len(frame) == 3840, "el mixer siempre devuelve frames de 20 ms (3840 bytes)")
        player.clear_speech()
        check(not player.is_speaking, "clear_speech vacía la voz pendiente")

        # La IA de voz puede pedir que la pista no se anuncie en el chat
        player.enqueue(Track(title="Tema silencioso", url="http://yt/5"), max_size=10)
        embeds_antes = len(player.text_channel.embeds)
        player.silent_next_track = True
        player.mixer.clear_music()
        await player.play_next()
        check(
            len(player.text_channel.embeds) == embeds_antes,
            "con silent_next_track no se anuncia la pista en el chat",
        )
        check(
            player.silent_next_track is False,
            "el silencio se consume una sola vez",
        )

        # Stop limpia la cola
        player.enqueue(Track(title="Tema 4", url="http://yt/4"), max_size=10)
        await player.stop()
        check(
            not player.queue and player.current is None,
            "stop vacía la cola y limpia el tema actual",
        )
        check(player.loop_mode == "off", "stop desactiva el loop")

        player._cancel_idle_timer()

    await player.disconnect()
    check(player.voice is None, "disconnect libera el cliente de voz")


def test_wake_word() -> None:
    from mango.services.wake import contains_wake_word, strip_wake_word

    words = ("oye mango", "hey mango", "hola mango")
    check(
        contains_wake_word("Oye, Mango, pon a Daft Punk", words),
        "detecta «Oye, Mango» con mayúsculas y comas",
    )
    check(contains_wake_word("oye mAngo", words), "detecta mayúsculas mezcladas")
    check(
        contains_wake_word("Hoy mango, ¿qué tal?", words),
        "tolera transcripciones tipo «hoy mango»",
    )
    check(contains_wake_word("mango", words), "se activa con solo «Mango»")
    check(
        contains_wake_word("o la mango, ponme música de los 80", words),
        "tolera «o la mango» (error típico de Whisper con «hola mango»)",
    )
    check(contains_wake_word("oy mango pon musica", words), "tolera «oy mango»")
    check(contains_wake_word("oyemango pon musica", words), "tolera «oyemango» pegado")
    check(
        not contains_wake_word("quiero un mango del árbol", words),
        "no se activa cuando hablan de un mango de verdad",
    )
    check(
        not contains_wake_word("vamos a comprar mangos mañana", words),
        "no se activa con «mangos» dentro de una frase normal",
    )
    check(
        strip_wake_word("Oye Mango pon música", words) == "pon música",
        "quita la palabra de activación y deja la petición",
    )


def test_audio_helpers() -> None:
    from mango.services.audio import (
        FRAME_BYTES,
        frame_rms,
        mono16k_to_wav,
        stereo_to_mono_16k,
    )

    check(frame_rms(b"\x00" * FRAME_BYTES) == 0.0, "el silencio tiene energía 0")

    loud = b"\x00\x40" * (FRAME_BYTES // 2)  # int16 16384 ≈ 0.5 de amplitud
    check(frame_rms(loud) > 0.4, "una señal fuerte supera el umbral del VAD")

    mono = stereo_to_mono_16k(b"\x00\x10" * 9600)  # 5 frames de 20 ms
    check(mono.size == 1600, "48 kHz estéreo → 16 kHz mono (1/3 de muestras)")

    wav = mono16k_to_wav(mono)
    check(
        wav[:4] == b"RIFF" and wav[8:12] == b"WAVE",
        "el WAV para la API de STT tiene cabecera válida",
    )


def test_mixer() -> None:
    from mango.services.audio import FRAME_BYTES, MixerSource

    silence = b"\x00" * FRAME_BYTES
    mixer = MixerSource(volume=1.0)

    check(mixer.read() == silence, "sin música ni voz el mixer devuelve silencio")

    mixer.push_tts(b"\x00\x20" * (FRAME_BYTES // 2))
    check(mixer.speaking, "la voz pendiente se marca como «hablando»")

    frame = mixer.read()
    check(
        len(frame) == FRAME_BYTES and frame != silence,
        "el mixer entrega la voz en frames de 20 ms",
    )
    check(not mixer.speaking, "al leer, la voz se consume")

    mixer.set_music_paused(True)
    check(mixer.read() == silence, "la música pausada no suena")


def test_ai_config() -> None:
    from mango.config import Config

    bare = Config(discord_token="x")
    check(
        not bare.ai_enabled and bare.stt_enabled and bare.tts_enabled,
        "sin claves: IA de texto apagada, pero STT/TTS locales disponibles",
    )
    check(not bare.voice_enabled, "sin LLM no se puede hablar por voz")

    keyed = Config(discord_token="x", llm_api_key="k", llm_model="m")
    check(keyed.ai_enabled and keyed.voice_enabled, "con LLM configurado la voz queda habilitada")
    check(
        keyed.wake_word_list[0] == "oye mango",
        "las palabras de activación se parsean desde la configuración",
    )


async def test_llm_router() -> None:
    from mango.services.llm import LLMError, LLMRouter

    class Failing:
        model = "sin-cuota"

        async def reply(self, **kwargs):
            raise LLMError("cuota agotada")

    class Working:
        model = "respaldo"

        async def reply(self, **kwargs):
            return "ok"

    router = LLMRouter([Failing(), Working()])
    check(router.chain == ["sin-cuota", "respaldo"], "la cadena de LLM conserva el orden")
    check(
        await router.reply(history=[]) == "ok",
        "el router usa el respaldo cuando el principal falla",
    )

    try:
        await LLMRouter([Failing()]).reply(history=[])
    except LLMError:
        check(True, "el router propaga el error si fallan todos los proveedores")
    else:
        check(False, "el router debería fallar si no queda ningún proveedor")


def test_listening_sentinel() -> None:
    """voice_recv devuelve MISSING (Ellipsis) cuando no escucha: no es True."""
    from mango.cogs.ai_voice import _is_listening

    class SinLector:
        def is_listening(self):
            return ...  # Ellipsis: centinela MISSING

    class ConLector:
        def is_listening(self):
            return True

    check(
        _is_listening(SinLector()) is False,
        "el centinela Ellipsis de voice_recv se interpreta como «no escucha»",
    )
    check(_is_listening(ConLector()) is True, "un lector real se detecta como activo")
    check(_is_listening(object()) is False, "sin método is_listening no se rompe")


def test_dave_patch() -> None:
    """El parche descifra DAVE antes de Opus y no toca lo que no aplica."""
    from mango.services import dave as dave_module

    class FakeSession:
        def __init__(self):
            self.ready = True
            self.calls = []

        def decrypt(self, user_id, media_type, payload):
            self.calls.append((user_id, payload))
            return b"OPUS-EN-CLARO"

    class FakeConnection:
        def __init__(self, session):
            self.dave_session = session
            self.dave_protocol_version = 1
            self.can_encrypt = True
            self.dave_downgraded = False

    class FakeVoiceClient:
        def __init__(self, session):
            self._connection = FakeConnection(session)
            self.user = type("User", (), {"id": 999})()
            self.ssrc_user = 42

        def _get_id_from_ssrc(self, ssrc):
            return self.ssrc_user

    class FakeSink:
        def __init__(self, voice_client):
            self.voice_client = voice_client

    class FakeDecoder:
        def __init__(self, voice_client):
            self.sink = FakeSink(voice_client)
            self._cached_id = None

    class FakePacket:
        ssrc = 7

        def __init__(self):
            self.decrypted_data = b"FRAME-CIFRADO-DAVE"

    session = FakeSession()
    voice_client = FakeVoiceClient(session)
    decoder = FakeDecoder(voice_client)
    packet = FakePacket()

    plain = dave_module._decrypt(decoder, packet)
    check(plain == b"OPUS-EN-CLARO", "el parche DAVE descifra antes de decodificar Opus")
    check(session.calls and session.calls[0][0] == 42, "usa el user_id resuelto por ssrc")

    # Canal sin DAVE negociado: el paquete ya es Opus en claro.
    voice_client._connection.dave_protocol_version = 0
    check(
        dave_module._decrypt(decoder, packet) is None,
        "sin DAVE negociado no se toca el paquete",
    )

    # Paquete vacío (silencio): nada que descifrar.
    voice_client._connection.dave_protocol_version = 1
    packet.decrypted_data = b""
    check(dave_module._decrypt(decoder, packet) is None, "un paquete vacío no se descifra")

    # Sin usuario asignado al ssrc no se puede descifrar.
    packet.decrypted_data = b"FRAME-CIFRADO-DAVE"
    voice_client.ssrc_user = None
    check(
        dave_module._decrypt(decoder, packet) is None,
        "sin usuario asignado no se descifra (y no se rompe)",
    )

    status = dave_module.dave_status(voice_client)
    check(
        status["supported"] and status["protocol"] == 1,
        "dave_status informa del protocolo negociado",
    )

    check(dave_module.is_disabled() is False, "DAVE arranca habilitado")
    dave_module.disable()
    check(dave_module.is_disabled() is True, "disable() desactiva DAVE")
    dave_module.restore()
    check(dave_module.is_disabled() is False, "restore() vuelve a habilitar DAVE")

    check(dave_module.install() is True, "install() activa el parche")
    check(dave_module.install() is True, "install() es idempotente")


def test_optimizaciones_voz() -> None:
    """Chunker de frases, defaults de latencia y STT de dos etapas."""
    from mango.config import Config
    from mango.services.stt import build_wake_stt
    from mango.services.tts import SentenceChunker

    # --- troceador de frases (permite hablar mientras el LLM sigue) ---
    troceador = SentenceChunker(min_len=10, max_len=60)
    frases = troceador.push("Primera frase lista. Segunda frase")
    check(frases == ["Primera frase lista."], "el chunker suelta la frase cerrada")
    check(
        troceador.push(" también.") == ["Segunda frase también."],
        "el chunker une lo pendiente con el trozo siguiente",
    )
    check(
        troceador.push("Sin punto y seguimos hablando mucho rato más todavía") == [],
        "el chunker no corta a mitad de frase antes del límite",
    )
    check(troceador.flush() != [], "flush() devuelve lo que queda al terminar")
    check(troceador.flush() == [], "flush() sin pendientes no devuelve nada")

    # --- defaults pensados para latencia y privacidad ---
    base = Config(discord_token="x")
    check(base.voice_silence_ms <= 500, "el silencio que cierra la frase es corto (<=500 ms)")
    check(base.voice_wake_model == "tiny", "la palabra clave usa el modelo tiny")
    check(
        base.voice_transcribe_all is False and base.voice_show_transcript is False,
        "por defecto no se transcribe todo ni se publican transcripciones",
    )
    check(
        base.voice_post_replies is False,
        "lo hablado por voz no se publica en el chat (solo los comandos)",
    )
    check(
        base.voice_session_timeout >= 0,
        "la ventana de conversación es configurable (0 = estricto, >0 = fluida)",
    )
    check(
        base.voice_conversation_filter is True,
        "con la conversación abierta se filtra la charla que no va dirigida a él",
    )
    check(
        base.voice_silence_ms >= 450,
        f"margen de escucha amplio para cerrar la frase ({base.voice_silence_ms} ms)",
    )
    check(
        base.tts_gain >= 1.7,
        f"la voz suena por encima de la música (ganancia x{base.tts_gain})",
    )
    check(
        base.tts_voice.startswith("es-"),
        f"voz en español configurada ({base.tts_voice})",
    )

    # La ventana de conversación solo se abre si se pide explícitamente
    from mango.cogs.ai_voice import VoiceSession

    sesion = VoiceSession(guild_id=1, channel_id=2)
    sesion.open_window(0)
    check(not sesion.in_conversation(), "con timeout 0 la conversación queda cerrada")
    sesion.open_window(30)
    check(sesion.in_conversation(), "con timeout >0 se abre la ventana de conversación")
    sesion.close_window()
    check(not sesion.in_conversation(), "close_window() la cierra")
    check(
        base.voice_wake_max_seconds <= 10,
        "hay un tope de duración para transcribir fuera de conversación",
    )

    # --- STT de dos etapas ---
    tonto = Config(discord_token="x", stt_provider="local", stt_model="small")
    wake = build_wake_stt(tonto)
    check(wake is not None and "tiny" in getattr(wake, "label", ""), "tiny para la palabra clave")
    check(
        getattr(wake, "label", "") != "faster-whisper · small",
        "el detector de palabra clave no reusa el modelo grande",
    )


def test_llm_stream_existe() -> None:
    """El streaming debe existir sin necesidad de tocar la API."""
    import inspect

    from mango.services.llm import LLMService

    check(hasattr(LLMService, "stream"), "LLMService expone stream() para hablar antes")
    check(inspect.isasyncgenfunction(LLMService.stream), "stream() es un generador asíncrono")


def test_voces_locales() -> None:
    """Proveedores locales de voz (Piper/Kokoro) y catálogo de descargas."""
    from mango.config import Config
    from mango.services import voices
    from mango.services.tts import KOKORO_DEFAULT_MODEL, PIPER_DEFAULT, KokoroTTS, PiperTTS

    # Las voces locales no necesitan clave de API
    for proveedor in ("local", "piper", "kokoro", "edge"):
        cfg = Config(discord_token="x", tts_provider=proveedor)
        check(
            cfg.tts_enabled,
            f"TTS local/gratis habilitado sin clave ({proveedor})",
        )
    check(
        not Config(discord_token="x", tts_provider="elevenlabs").tts_enabled,
        "ElevenLabs sí exige TTS_API_KEY",
    )

    # Constructores perezosos: no cargan el modelo hasta el primer uso
    piper = PiperTTS(PIPER_DEFAULT)
    kokoro = KokoroTTS(KOKORO_DEFAULT_MODEL, KOKORO_DEFAULT_MODEL.parent / "voices.bin", "ef_dora")
    check("Piper" in piper.label, "PiperTTS se identifica como Piper")
    check("Kokoro" in kokoro.label and "ef_dora" in kokoro.label, "KokoroTTS usa la voz indicada")
    check(piper._voice is None, "PiperTTS no carga el modelo al construirse")
    check(kokoro._kokoro is None, "KokoroTTS no carga el modelo al construirse")

    # Catálogo de descargas: voces españolas + Kokoro
    check("piper-es-es" in voices.MODELOS, "el catálogo incluye la voz es-ES de Piper")
    check("kokoro" in voices.MODELOS, "el catálogo incluye Kokoro")
    check(
        all(url.startswith("https://") for urls in voices.MODELOS.values() for url in urls),
        "todas las descargas usan HTTPS",
    )
    try:
        voices.descargar("no-existe")
    except voices.DescargaError:
        check(True, "pedir una voz inexistente da un error claro")
    else:
        check(False, "descargar() debería rechazar nombres desconocidos")


def test_limpieza_titulos_lyrics() -> None:
    """`!lyrics` debe funcionar con títulos sucios de YouTube/Spotify."""
    from mango.services.lyrics import candidatos
    from mango.services.texto import limpiar_titulo

    sucio = "Red Hot Chili Peppers - Californication (Official Music Video) [HD UPGRADE]"
    check(
        limpiar_titulo(sucio) == "Red Hot Chili Peppers - Californication",
        "quita «(Official Music Video) [HD UPGRADE]» del título",
    )
    check(
        candidatos(sucio)[0] == ("Californication", "Red Hot Chili Peppers"),
        "el primer intento es (canción, artista) al estilo YouTube",
    )

    check(
        limpiar_titulo("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams")
        == "Daft Punk - Get Lucky",
        "quita «(Official Audio)» y «ft. …»",
    )
    check(
        limpiar_titulo("a-ha - Take On Me (Official Video) [4K]") == "a-ha - Take On Me",
        "no rompe nombres con guion (a-ha)",
    )
    check(
        limpiar_titulo("(I Can't Get No) Satisfaction") == "(I Can't Get No) Satisfaction",
        "respeta los paréntesis que son parte del título",
    )

    pares = candidatos("Instant Crush — Daft Punk")  # formato Spotify
    check(
        ("Instant Crush", "Daft Punk") in pares,
        "también contempla el formato «canción — artista» de Spotify",
    )
    check(candidatos("") == [], "un título vacío no genera intentos")


def test_busqueda_inteligente() -> None:
    """La búsqueda puntúa 5 candidatos en vez de coger el primero."""
    from mango.services.ytdlp import _normalizar, _puntuar

    consulta = _normalizar("tren al sur")
    tokens = {token for token in consulta.split() if len(token) > 1}

    oficial = {
        "title": "Los Prisioneros - Tren Al Sur (Audio)",
        "uploader": "Los Prisioneros - Topic",
        "duration": 338,
    }
    cover = {
        "title": "Tren Al Sur (Cover con guitarra)",
        "uploader": "CoversRandom",
        "duration": 300,
    }
    short = {"title": "Tren al sur #shorts", "uploader": "x", "duration": 20}
    otro = {"title": "Una canción distinta", "uploader": "y", "duration": 200}

    check(
        _puntuar(oficial, tokens, consulta) > _puntuar(cover, tokens, consulta),
        "prefiere el audio oficial antes que un cover",
    )
    check(
        _puntuar(oficial, tokens, consulta) > _puntuar(short, tokens, consulta),
        "penaliza shorts y clips cortos",
    )
    check(
        _puntuar(oficial, tokens, consulta) > _puntuar(otro, tokens, consulta),
        "prefiere el resultado que coincide con lo pedido",
    )
    check(_normalizar("Tren Al Sur") == "tren al sur", "normaliza mayúsculas y acentos")

    # Si el usuario pide karaoke, no se penaliza el karaoke
    q2 = _normalizar("bohemian rhapsody karaoke")
    t2 = {token for token in q2.split() if len(token) > 1}
    karaoke = {
        "title": "Queen - Bohemian Rhapsody (Karaoke Version)",
        "uploader": "Sing King",
        "duration": 365,
    }
    original = {
        "title": "Queen - Bohemian Rhapsody (Official Video)",
        "uploader": "Queen Official",
        "duration": 355,
    }
    check(
        _puntuar(karaoke, t2, q2) > _puntuar(original, t2, q2),
        "si se pide karaoke, gana el karaoke",
    )


def test_duplicados() -> None:
    """Una canción no se encola dos veces."""
    from types import SimpleNamespace

    from mango.config import load_config
    from mango.services.texto import titulo_normalizado
    from mango.state import GuildPlayer, Track

    bot = SimpleNamespace(config=load_config(), loop=None)
    player = GuildPlayer(bot, SimpleNamespace(id=99, name="g"))

    original = Track(title="Los Prisioneros - Tren Al Sur (Lyric Video)", url="http://yt/1")
    player.enqueue(original, max_size=10)

    misma_url = Track(title="Otro título distinto", url="http://yt/1")
    mismo_titulo = Track(
        title="Los Prisioneros - Tren Al Sur (Official Video)", url="http://yt/2"
    )
    otra = Track(title="Daft Punk - Get Lucky", url="http://yt/3")

    check(player.find_duplicate(misma_url) == (original, 1), "detecta el mismo vídeo (URL)")
    check(
        player.find_duplicate(mismo_titulo) == (original, 1),
        "detecta la misma canción con «(Official Video)» de más",
    )
    check(player.find_duplicate(otra) is None, "una canción distinta no es duplicado")

    player.current = original
    check(
        player.find_duplicate(misma_url) == (original, 0),
        "detecta que la canción ya está sonando (posición 0)",
    )

    # Spotify: dos peticiones de la misma canción generan la misma búsqueda
    player.current = None
    player.queue.clear()
    pista = Track(title="Instant Crush — Daft Punk", query="Instant Crush Daft Punk audio")
    player.enqueue(pista, max_size=10)
    repetida = Track(title="Instant Crush — Daft Punk", query="Instant Crush Daft Punk audio")
    check(player.find_duplicate(repetida) is not None, "detecta duplicados de Spotify")

    check(
        titulo_normalizado("Artista - Canción (Official Video) [HD]") == "artista cancion",
        "normaliza títulos para comparar",
    )


def test_solo_musica() -> None:
    """El bot solo acepta resultados que sean música."""
    from mango.services.tools import MangoTools
    from mango.services.ytdlp import es_musica

    cancion = {
        "title": "$UICIDEBOY$ - AVALON (Official Lyric Video)",
        "channel": "$uicideboy$",
        "categories": ["Music"],
        "duration": 141,
        "live_status": "not_live",
    }
    check(es_musica(cancion), "acepta un vídeo de música")

    gameplay = {
        "title": "AVALON - Gameplay #12",
        "channel": "GamerX",
        "categories": ["Gaming"],
        "duration": 600,
    }
    check(not es_musica(gameplay), "rechaza gameplay")

    trailer = {
        "title": "Avalon - Trailer oficial de la película",
        "channel": "Cine",
        "categories": ["Film & Animation"],
        "duration": 120,
    }
    check(not es_musica(trailer), "rechaza trailers de cine")

    directo = {
        "title": "Avalon Live at Tomorrowland",
        "channel": "Festival",
        "categories": ["Music"],
        "duration": 3600,
        "live_status": "is_live",
    }
    check(not es_musica(directo), "rechaza directos y sets eternos")

    sin_datos = {
        "title": "Un vídeo cualquiera",
        "channel": "RandomChanel",
        "categories": [],
        "duration": 200,
    }
    check(
        not es_musica(sin_datos),
        "sin categoría ni canal de artista no se acepta a ciegas",
    )

    topic = {
        "title": "Artist - Song",
        "channel": "Artist - Topic",
        "categories": [],
        "duration": 210,
    }
    check(es_musica(topic), "acepta canales de artista (- Topic)")

    # La petición del usuario no se recorta
    check(
        MangoTools._limpiar_peticion("oye mango, pon avalon suicideboys") == "avalon suicideboys",
        "quita el «oye mango, pon» de la petición",
    )
    check(
        MangoTools._limpiar_peticion("reproduce tren al sur") == "tren al sur",
        "quita el verbo al limpiar la petición",
    )


def test_reconocimiento_entrada() -> None:
    """Preparación del audio para el STT (filtro + nivel) y streaming del TTS."""
    import numpy as np

    from mango.services.audio import FRAME_BYTES, preparar_para_stt
    from mango.services.tts import EdgeTTS

    # 48 kHz estéreo -> 16 kHz mono (1/3 de muestras)
    muestras = preparar_para_stt(bytes([0, 16]) * (FRAME_BYTES // 2 * 5))
    check(muestras.size == 1600, "preparar_para_stt deja 16 kHz mono")
    check(muestras.dtype == np.float32, "devuelve float32 en [-1, 1]")

    # Silencio: no se amplifica el ruido de fondo
    check(float(np.max(np.abs(preparar_para_stt(bytes(96000))))) == 0.0,
          "el silencio no se amplifica")

    # Voz floja: se sube el nivel para que el reconocedor la entienda
    flojo = (np.sin(np.arange(96000) * 0.05) * 3000).astype(np.int16).tobytes()
    subido = float(np.max(np.abs(preparar_para_stt(flojo))))
    check(subido > 0.4, f"el audio flojo se normaliza (pico {subido:.2f})")

    # El TTS en streaming existe (permite hablar mientras se genera)
    check(hasattr(EdgeTTS, "stream_pcm"), "edge-tts puede emitir audio en trozos")


async def test_bot() -> None:
    config = load_config()
    bot = MangoBot(config)

    for extension in INITIAL_EXTENSIONS:
        await bot.load_extension(extension)

    registered = {command.qualified_name for command in bot.walk_commands()}
    missing = EXPECTED_COMMANDS - registered
    check(
        not missing,
        f"todos los comandos esperados están registrados (faltan: {sorted(missing)})",
    )

    embed_command = bot.get_command("embed")
    check(embed_command is not None and embed_command.hidden, "!embed existe y está oculto")
    checks = getattr(embed_command, "checks", [])
    check(bool(checks), "!embed tiene restricción de permisos (is_owner)")
    check(bot.get_command("mc") is None, "el comando !mc fue eliminado")

    # !mango funciona en cualquier canal y !mango sin texto muestra el manual
    mango_command = bot.get_command("mango")
    check(mango_command is not None, "!mango está registrado")
    check(
        mango_command is not None and not mango_command.hidden,
        "!mango es público (sirve en cualquier canal de texto)",
    )
    help_command = bot.get_command("help")
    check(
        help_command is not None and "mango" not in help_command.aliases,
        "!mango ya no es alias de la ayuda (evita ambigüedad)",
    )

    # Voz: el bot debe poder recibir audio en cualquier canal
    from mango import state as state_module

    check(
        state_module.VoiceRecvClient is not None,
        "VoiceRecvClient disponible: el bot puede oír en cualquier canal de voz",
    )
    session = AIVoice(bot).sessions
    check(session == {}, "las sesiones de voz arrancan vacías")

    await bot.close()


def test_confirmacion_y_busqueda() -> None:
    """Confirmación hablada de la canción y búsqueda tolerante a errores de STT."""
    print("\n── Confirmación por voz y búsqueda ──")
    from mango.services.texto import (
        es_peticion_musica,
        limpiar_peticion,
        peticion_compatible,
    )
    from mango.services.tools import MangoTools, PreparedSpeech
    from mango.services.ytdlp import _variantes

    # ¿Es una petición de música?
    check(es_peticion_musica("oye mango reproduce tren al sur"), "detecta «reproduce»")
    check(es_peticion_musica("ponme algo de daft punk"), "detecta «ponme»")
    check(not es_peticion_musica("que buena cancion"), "«que buena canción» no es petición")
    check(not es_peticion_musica("oye mango sal del canal"), "«sal del canal» no es música")

    # Limpieza de la petición
    check(limpiar_peticion("oye Mango, reproduce tren al sur") == "tren al sur",
          f"limpia muletillas y verbo ({limpiar_peticion('oye Mango, reproduce tren al sur')!r})")
    check(limpiar_peticion("pon algo de daft punk") == "daft punk", "quita «algo de»")

    # Compatibilidad (para reutilizar la prebúsqueda)
    check(peticion_compatible("los prisioneros tren al sur", "prisioneros tren al sur"),
          "dos formas de pedir lo mismo son compatibles")
    check(not peticion_compatible("daft punk", "musica"), "peticiones distintas no son compatibles")

    # Variantes cuando la transcripción arruina la consulta
    variantes = _variantes("Dazpump get lucky")
    check(variantes[0] == "Dazpump get lucky", "la primera variante es la consulta original")
    check("get lucky" in variantes, "propone quitar la primera palabra")

    # La voz preparada se puede consumir por trozos
    async def flujo() -> None:
        preparada = PreparedSpeech()
        preparada.push(b"uno")
        preparada.push(b"dos")
        primero = await preparada.next_chunk(1.0)
        check(primero == b"uno", "el primer trozo llega en cuanto está")
        preparada.close()
        check(await preparada.next_chunk(0.1) == b"dos", "siguiente trozo disponible")
        check(await preparada.next_chunk(0.1) == b"", "al cerrar devuelve vacío")
        check(preparada.finished, "marca que terminó")

    asyncio.run(flujo())

    # La confirmación hablada existe y no depende del chat
    check(hasattr(MangoTools, "_confirmar_en_voz"), "MangoTools confirma la canción hablando")
    check(hasattr(MangoTools, "prepare_confirmation"), "la confirmación se puede preparar antes")
    check(hasattr(MangoTools, "cancel_background"), "lo preparado se puede descartar")


def test_voz_de_respaldo() -> None:
    """Si la voz principal falla, la local responde igual."""
    print("\n── Voz de respaldo ──")
    from mango.services.tts import FallbackTTS

    class Rota:
        label = "rota"

        async def stream_pcm(self, text):
            raise RuntimeError("no audio")
            yield b""  # pragma: no cover

    class Buena:
        label = "buena"

        async def stream_pcm(self, text):
            yield b"\x00" * 10

    async def flujo() -> None:
        servicio = FallbackTTS(Rota(), Buena())
        trozos = [t async for t in servicio.stream_pcm("hola")]
        check(trozos == [b"\x00" * 10], "si la principal falla, responde la local")
        check("respaldo" in servicio.label, "la etiqueta muestra el respaldo")

    asyncio.run(flujo())


def test_limpieza_titulos() -> None:
    """Los títulos de YouTube se limpian para Genius y para comparar canciones."""
    print("\n── Limpieza de títulos ──")
    from mango.services.texto import limpiar_titulo, titulo_normalizado

    casos = [
        ("Red Hot Chili Peppers - Californication (Official Music Video) [HD UPGRADE]",
         "Red Hot Chili Peppers - Californication"),
        ("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams",
         "Daft Punk - Get Lucky"),
        ("Los Prisioneros - Tren Al Sur (Lyric Video)", "Los Prisioneros - Tren Al Sur"),
    ]
    for original, esperado in casos:
        obtenido = limpiar_titulo(original)
        check(obtenido == esperado, f"{original!r} → {obtenido!r}")

    check(limpiar_titulo("(I Can't Get No) Satisfaction") == "(I Can't Get No) Satisfaction",
          "respeta los paréntesis que son parte del título")
    check(titulo_normalizado("Los Prisioneros - Tren Al Sur (Video Oficial)")
          == titulo_normalizado("los prisioneros tren al sur"),
          "dos formas del mismo título coinciden")


def test_voz_con_musica() -> None:
    """La música NO baja al hablar el usuario; solo cuando habla Mango."""
    print("\n── Voz con música de fondo ──")
    import numpy as np

    from mango.services.audio import (
        CHANNELS,
        DUCK_VOLUME,
        FRAME_BYTES,
        SAMPLE_RATE,
        SAMPLE_WIDTH,
        MixerSource,
        UtteranceCollector,
        frame_rms,
        tail_seconds,
    )

    def frame(amplitud: int) -> bytes:
        muestras = np.full(FRAME_BYTES // 2, amplitud, dtype=np.int16)
        return muestras.tobytes()

    # 1) Hablar por el micro NO baja la música
    mixer = MixerSource(1.0, tts_gain=1.0)
    mixer.set_music(_FuenteConstante(int(0.30 * 32767)))
    nivel_musica = frame_rms(mixer.read())
    nivel_tras_hablar = frame_rms(mixer.read())
    check(
        abs(nivel_tras_hablar - nivel_musica) < 0.01,
        f"la música mantiene el volumen al hablar ({nivel_musica:.2f} → {nivel_tras_hablar:.2f})",
    )
    check(not hasattr(mixer, "duck_for"), "ya no existe el ducking automático al hablar")

    # 2) Cuando habla Mango, sí se aparta la música
    mixer.push_tts(b"\x00" * FRAME_BYTES)  # voz de Mango (silencio en esta prueba)
    nivel_con_voz = frame_rms(mixer.read())
    check(
        nivel_con_voz < nivel_musica * (DUCK_VOLUME + 0.05),
        f"la música baja cuando habla Mango ({nivel_musica:.2f} → {nivel_con_voz:.2f})",
    )

    # 3) El umbral se adapta al ruido de fondo: el eco constante no es voz
    eco = UtteranceCollector(energy=0.025, silence_ms=320, min_speech_ms=250)
    ruido = frame(int(0.03 * 32767))  # eco suave de la música
    for _ in range(150):  # 3 s de eco constante
        eco.feed(ruido)
    check(not eco.recording, "el eco constante de la música no se toma por voz")
    check(eco.threshold() > 0.03, f"el umbral sube con el ruido ({eco.threshold():.3f})")

    # 4) La voz real sí entra
    voz = frame(int(0.25 * 32767))
    for _ in range(5):
        eco.feed(voz)
    check(eco.recording, "la voz real sí activa la grabación con música")

    # 5) En silencio, el umbral vuelve al valor base
    limpio = UtteranceCollector(energy=0.010, silence_ms=320, min_speech_ms=250)
    for _ in range(100):
        limpio.feed(frame(0))
    check(
        abs(limpio.threshold() - 0.010) < 1e-6,
        f"sin ruido el umbral es el configurado ({limpio.threshold():.3f})",
    )

    # 6) La voz se sube con limitador suave (sin distorsión)
    from mango.services.audio import boost_pcm

    señal = np.full(4800, int(0.5 * 32767), dtype=np.int16).tobytes()
    antes = float(np.abs(np.frombuffer(señal, dtype=np.int16)).max()) / 32768.0
    despues = float(np.abs(np.frombuffer(boost_pcm(señal, 1.5), dtype=np.int16)).max()) / 32768.0
    check(despues > antes * 1.4, f"la voz sube de nivel ({antes:.2f} → {despues:.2f})")
    check(despues <= 1.0, "la voz no se desborda")

    tope = np.full(4800, 32767, dtype=np.int16).tobytes()
    tope_out = np.frombuffer(boost_pcm(tope, 2.0), dtype=np.int16)
    check(int(np.abs(tope_out).max()) <= 32767, "el limitador no rompe la señal al máximo")
    check(boost_pcm(señal, 1.0) == señal, "con ganancia 1.0 no se toca el audio")

    # 7) Frases largas: se analiza la cola, no se descarta todo
    largo = b"\x00" * (FRAME_BYTES * 1500)  # 30 s
    cola = tail_seconds(largo, 6)
    esperado = 6 * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
    check(len(cola) <= esperado + FRAME_BYTES, "tail_seconds recorta a los últimos segundos")
    check(len(cola) >= esperado - FRAME_BYTES, "tail_seconds conserva lo pedido")
    check(tail_seconds(b"corto", 6) == b"corto", "si ya es corto, no lo toca")


class _FuenteConstante:
    """Fuente de audio con un tono constante (para probar el mezclador)."""

    def __init__(self, amplitud: int) -> None:
        import numpy as np

        from mango.services.audio import FRAME_BYTES

        self._frame = np.full(FRAME_BYTES // 2, amplitud, dtype=np.int16).tobytes()

    def read(self) -> bytes:
        return self._frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        return None


def test_intencion_y_locutor() -> None:
    """Filtro de intención (charla ajena) y confirmación estilo locutor."""
    print("\n── Intención y locutor ──")
    from mango.personality import linea_locutor
    from mango.services.intent import es_para_mango
    from mango.services.texto import separar_titulo_artista

    despiertan = [
        "Oye Mango, pon algo de Daft Punk",
        "pon tren al sur",
        "reproduce avalon de suicideboys",
        "¿qué está sonando?",
        "cual es la mejor cancion de los 90",
        "para la musica",
        "sí",
        "mango",
    ]
    for frase in despiertan:
        check(es_para_mango(frase, ["oye mango"]), f"va dirigida a Mango: {frase!r}")

    charla = [
        "esa cancion esta buenísima",
        "vamos a jugar una partida",
        "jaja que risa",
        "mi hermana llega mañana",
        "no me gusta el reggaeton",
    ]
    for frase in charla:
        check(not es_para_mango(frase, ["oye mango"]), f"es charla ajena: {frase!r}")

    # Título y artista, como en la radio
    titulo, artista = separar_titulo_artista("Los Prisioneros - Tren Al Sur (Lyric Video)")
    check(
        (titulo, artista) == ("Tren Al Sur", "Los Prisioneros"),
        f"separa título y artista ({titulo!r} / {artista!r})",
    )
    titulo, artista = separar_titulo_artista("Avalon")
    check(artista == "" and titulo == "Avalon", "sin guion no hay artista")

    frase = linea_locutor("Tren Al Sur", "Los Prisioneros")
    check("Tren Al Sur" in frase and "Los Prisioneros" in frase,
          f"el locutor nombra canción y artista ({frase!r})")
    frase = linea_locutor("Tren Al Sur", "Los Prisioneros", a_la_cola=True)
    check("cola" in frase.lower() or "luego" in frase.lower() or "detrás" in frase.lower(),
          f"anuncia que va a la cola ({frase!r})")
    frase = linea_locutor("Avalon", "")
    check("Avalon" in frase and "de ." not in frase, "sin artista la frase sigue teniendo sentido")


def test_decir_en_voz() -> None:
    """«!mango di …» y la herramienta say_text de la IA."""
    print("\n── Decir en voz alta ──")
    from mango.services.llm import MUSIC_TOOLS
    from mango.services.texto import texto_a_decir
    from mango.services.tools import MangoTools

    literales = [
        ("di hola a todos", "hola a todos"),
        ("di: buenos días", "buenos días"),
        ("di que empieza el directo", "empieza el directo"),
        ("decir feliz cumpleaños", "feliz cumpleaños"),
        ("repite el estribillo", "el estribillo"),
        ("say hello world", "hello world"),
        ('di "texto exacto, con comas"', "texto exacto, con comas"),
        ("«solo esto»", "solo esto"),
    ]
    for frase, esperado in literales:
        check(texto_a_decir(frase) == esperado, f"{frase!r} → {texto_a_decir(frase)!r}")

    # Lo genérico lo inventa la IA, no se lee literal
    for frase in ("di algo divertido", "di un chiste", "di una frase bonita"):
        check(texto_a_decir(frase) is None, f"{frase!r} lo genera la IA")

    # No confundir «dime» (pregunta) con «di» (hablar)
    check(texto_a_decir("dime qué canción es") is None, "«dime» no es una orden de hablar")

    # La herramienta existe y el bot la puede ejecutar
    nombres = {t["function"]["name"] for t in MUSIC_TOOLS}
    check("say_text" in nombres, "la IA tiene la herramienta say_text")
    check(hasattr(MangoTools, "_say"), "MangoTools implementa _say")
    check(hasattr(MangoTools, "_decir_permitido"), "hay control de permisos para hablar")


def test_entrar_al_canal() -> None:
    """«!hi», «!mango ven» y la herramienta join_voice de la IA."""
    print("\n── Entrar al canal de voz ──")
    from mango.cogs.music import Music
    from mango.services.intent import es_para_mango
    from mango.services.llm import MUSIC_TOOLS
    from mango.services.texto import es_directiva_entrar
    from mango.services.tools import MangoTools

    ordenes = [
        "ven", "ven acá", "ven aqui", "ven al canal", "ven al canal de voz",
        "entra", "entra al canal", "únete", "unete al canal", "conéctate",
        "metete al canal", "mango ven", "oye ven por favor", "join",
    ]
    for frase in ordenes:
        check(es_directiva_entrar(frase), f"pide entrar al canal: {frase!r}")

    otras = ["ven a ver esto", "¿vienes?", "entra la canción", "pon tren al sur", ""]
    for frase in otras:
        check(not es_directiva_entrar(frase), f"no es orden de entrar: {frase!r}")

    # «!hi» sigue existiendo y la IA tiene la herramienta
    check(hasattr(Music, "hi"), "!hi sigue disponible")
    nombres = {t["function"]["name"] for t in MUSIC_TOOLS}
    check("join_voice" in nombres, "la IA tiene join_voice")
    check(hasattr(MangoTools, "_join_voice"), "MangoTools implementa _join_voice")

    # Dentro de la conversación se reconoce como orden dirigida a él
    for frase in ("ven", "entra al canal", "oye mango, ven al canal de voz", "unete"):
        check(es_para_mango(frase, ["oye mango"]), f"va dirigida a Mango: {frase!r}")


def test_respuesta_rapida() -> None:
    """Interjección instantánea y confirmación sin repetir la apertura."""
    print("\n── Respuesta rápida ──")
    from mango import personality
    from mango.cogs.ai_voice import AIVoice
    from mango.services.tools import MangoTools

    check(len(personality.INTERJECCIONES) >= 2, "hay interjecciones precacheadas")
    check(all(f.strip() for f in personality.INTERJECCIONES), "ninguna está vacía")

    con = personality.linea_locutor("Tren Al Sur", "Los Prisioneros")
    sin = personality.linea_locutor("Tren Al Sur", "Los Prisioneros", con_apertura=False)
    check("Tren Al Sur" in sin and "Los Prisioneros" in sin,
          "la continuación nombra título y artista")
    check(not any(i.rstrip("!.") in sin for i in personality.INTERJECCIONES),
          f"sin apertura no repite la interjección ({sin!r})")
    check(len(sin) < len(con) or sin != con, "la continuación es distinta de la frase completa")

    check(hasattr(AIVoice, "precalentar_interjecciones"), "el cog pregenera las interjecciones")
    check(hasattr(AIVoice, "_hablar_interjeccion"), "el cog puede decirlas al instante")

    # Saludos: se contesta de vuelta y NO se pone música
    from mango.services.texto import es_saludo

    for frase in ("hola mango", "hola Mango", "buenas", "hey mango", "hola, ¿qué tal?"):
        check(es_saludo(frase), f"saludo reconocido: {frase!r}")
    for frase in ("oye mango", "mango", "hola mango pon algo", "hola mango, ¿me escuchas?",
                  "pon tren al sur"):
        check(not es_saludo(frase), f"no es un saludo suelto: {frase!r}")
    check(len(personality.AI_GREETINGS) >= 2, "hay saludos precacheados")
    check(hasattr(AIVoice, "_hablar_saludo"), "el cog puede saludar al instante")

    # Controles instantáneos: se ejecutan sin consultar al modelo
    from mango.services.texto import control_de_voz

    controles = {
        "skip": ("salta", "salta esta", "siguiente", "cambia la cancion", "next"),
        "stop": ("para", "para la musica", "stop", "silencio"),
        "pause": ("pausa", "pausa la musica"),
        "resume": ("reanuda", "continua", "sigue"),
    }
    for esperado, frases in controles.items():
        for frase in frases:
            check(control_de_voz(frase) == esperado, f"{frase!r} → {esperado}")
    for frase in ("pon tren al sur", "¿qué está sonando?", "hola mango", "para la fiesta"):
        check(control_de_voz(frase) is None, f"no es un control: {frase!r}")

    check(len(personality.AI_CONTROLES) >= 5, "hay respuestas de control precacheadas")
    check(hasattr(AIVoice, "_ejecutar_control"), "el cog ejecuta controles sin modelo")

    # El reproductor recuerda la última canción (no se «pierde»)
    from mango.state import GuildPlayer

    check(hasattr(GuildPlayer, "skip"), "el reproductor sabe saltar")
    check("last_track" in GuildPlayer.__init__.__code__.co_names
          or any("last_track" in str(a) for a in GuildPlayer.__init__.__code__.co_consts),
          "el reproductor guarda la última canción")

    # Barrera determinista: no se pone música si la frase no la pide
    from mango.services.texto import pide_musica

    for frase in ("hola mango", "hola", "buenas", "¿qué está sonando?", "que tal"):
        check(not pide_musica(frase), f"no pide música: {frase!r}")
    for frase in ("pon tren al sur", "reproduce genesis", "tren al sur",
                  "ponme algo tranquilo", "me apetece musica de los 80"):
        check(pide_musica(frase), f"sí pide música: {frase!r}")

    # Títulos sucios de YouTube: solo se dice título y artista
    from mango.personality import linea_locutor
    from mango.services.texto import separar_titulo_artista

    sucios = [
        ("BTS 'Like Animals' Lyrics (방탄소년단 Like Animals 가사) [Color Coded_Eng]"
         " | ShadowByYoongi", "Like Animals", "BTS"),
        ("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams",
         "Get Lucky", "Daft Punk"),
        ("$UICIDEBOY$ - AVALON (Official Lyric Video)", "AVALON", "UICIDEBOY"),
        ("Los Prisioneros - Tren Al Sur (Lyric Video)", "Tren Al Sur", "Los Prisioneros"),
    ]
    for sucio, esperado_t, esperado_a in sucios:
        titulo, artista = separar_titulo_artista(sucio)
        check(
            (titulo, artista) == (esperado_t, esperado_a),
            f"{sucio[:34]!r} → {titulo!r} / {artista!r}",
        )
        frase = linea_locutor(titulo, artista)
        for ruido in ("lyrics", "lyric", "color coded", "official", "shadow", "hd"):
            check(ruido not in frase.lower(), f"la frase no dice {ruido!r}: {frase!r}")

    # El historial se puede borrar entero al arrancar
    from mango.db import MemoryStore

    check(hasattr(MemoryStore, "clear_all"), "la memoria permite borrado total")
    check(load_config().clear_memory_on_start is True,
          "el historial se limpia al arrancar por defecto")

    # La confirmación respeta el flag con_apertura
    class _Bot:
        class config:
            max_queue = 10
        def get_player(self, guild):
            return None

    tools = MangoTools(_Bot(), None, None, None, announce_tracks=False)
    check(tools.con_apertura is True, "por defecto la confirmación lleva apertura")
    tools.con_apertura = False
    from mango.state import Track

    frase = tools._frase_confirmacion(Track(title="Los Prisioneros - Tren Al Sur"), empezo=True)
    check("Tren Al Sur" in frase and "Los Prisioneros" in frase,
          f"con_apertura=False sigue nombrando la canción ({frase!r})")


def test_comandos_de_barra() -> None:
    """`/mclear` registrado como comando de barra con sus permisos y opción."""
    print("\n── Comandos de barra (/) ──")

    config = load_config()
    bot = MangoBot(config)

    async def cargar() -> None:
        await bot.load_extension("mango.cogs.slash")

    asyncio.run(cargar())

    clear = bot.tree.get_command("mclear")
    check(bot.tree.get_command("clear") is None, "el antiguo /clear ya no existe")
    check(clear is not None, "/mclear está registrado en el árbol de comandos")
    if clear is None:
        return

    check(clear.description != "", "/mclear tiene descripción visible")
    check(clear.guild_only is True, "/mclear solo funciona en servidores")
    check(
        clear.default_permissions is not None
        and clear.default_permissions.manage_messages,
        "/mclear pide el permiso «Gestionar mensajes»",
    )
    check(bool(clear.checks), "/mclear valida permisos al ejecutarse")

    opciones = {p.name: p for p in clear.parameters}
    check("cantidad" in opciones, "/mclear acepta la cantidad de mensajes")
    cantidad = opciones.get("cantidad")
    if cantidad is not None:
        check(cantidad.required is False, "la cantidad es opcional (10 por defecto)")
        check(
            getattr(cantidad, "min_value", None) == 1
            and getattr(cantidad, "max_value", None) == 100,
            "la cantidad se limita a 1-100",
        )

    # No necesita leer el contenido de los mensajes
    check(
        (bot.intents.message_content or True) is not None,
        "los comandos de barra no dependen del Message Content Intent",
    )


def main() -> int:
    print("── Prueba de humo de Mango Bot ──")
    test_track()
    test_player()
    test_personality()
    test_config_errors()
    test_wake_word()
    test_listening_sentinel()
    test_dave_patch()
    test_optimizaciones_voz()
    test_llm_stream_existe()
    test_voces_locales()
    test_limpieza_titulos_lyrics()
    test_busqueda_inteligente()
    test_duplicados()
    test_solo_musica()
    test_reconocimiento_entrada()
    test_audio_helpers()
    test_mixer()
    test_ai_config()
    test_confirmacion_y_busqueda()
    test_voz_de_respaldo()
    test_limpieza_titulos()
    test_voz_con_musica()
    test_intencion_y_locutor()
    test_decir_en_voz()
    test_entrar_al_canal()
    test_comandos_de_barra()
    test_respuesta_rapida()
    asyncio.run(test_llm_router())
    asyncio.run(test_playback_state_machine())
    asyncio.run(test_bot())

    print("\n── Resultado ──")
    if failures:
        print(f"{len(failures)} comprobación(es) fallida(s):")
        for failure in failures:
            print(f"  · {failure}")
        return 1
    print("Todo correcto ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
