"""Síntesis de voz (TTS) a PCM 48 kHz estéreo listo para Discord.

Proveedores:

* ``edge``   → edge-tts (voces neuronales de Microsoft, gratis y sin clave).
* ``openai`` → ``/audio/speech`` (OpenAI u otro compatible).

Ambos devuelven bytes PCM 16 bits 48 kHz estéreo, que es justo lo que
consume :class:`mango.services.audio.MixerSource`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import subprocess
import threading
import wave
from pathlib import Path
from typing import Any, Optional

from mango.services.audio import (
    CHANNELS,
    FRAME_BYTES,
    SAMPLE_RATE,
    bytes_to_48k_stereo_pcm,
)

log = logging.getLogger(__name__)

MAX_SPEECH_CHARS = 600
FFMPEG_TIMEOUT = 60

_MARKDOWN_RE = re.compile(r"[*_`>#]+")
_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff\u2190-\u21ff\u2b00-\u2bff\ufe0f]"
)


class TTSError(RuntimeError):
    """Fallo al sintetizar voz."""


# ===============================
# Limpieza del texto
# ===============================
def clean_for_speech(text: str, *, max_chars: int = MAX_SPEECH_CHARS) -> str:
    """Quita markdown, URLs y emojis; recorta en una frase completa."""
    cleaned = _URL_RE.sub("", text or "")
    cleaned = _MARKDOWN_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    # Espacios “invisibles” que emiten algunos modelos ( ,  , ​)
    # y que pueden dejar la síntesis sin audio: se normalizan.
    for raro in ("\u202f", "\u00a0", "\u200b", "\u200e", "\u200f"):
        cleaned = cleaned.replace(raro, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if len(cleaned) <= max_chars:
        return cleaned

    cut = cleaned[:max_chars]
    for separator in (". ", "? ", "! ", "; ", ", "):
        index = cut.rfind(separator)
        if index > max_chars * 0.4:
            return cut[: index + 1].strip()
    return cut.strip()


class SentenceChunker:
    """Acumula texto que llega por trozos y devuelve frases completas.

    Se usa con el streaming del LLM: en cuanto hay una frase cerrada, se
    sintetiza y se encola, sin esperar a que el modelo termine.
    """

    def __init__(self, *, min_len: int = 10, max_len: int = 90) -> None:
        self._buffer = ""
        self._min_len = min_len
        self._max_len = max_len

    def push(self, trozo: str) -> list[str]:
        """Añade texto y devuelve las frases ya completas."""
        self._buffer += trozo
        frases: list[str] = []
        while True:
            corte = self._buscar_corte()
            if corte <= 0:
                break
            frase = self._buffer[:corte].strip()
            self._buffer = self._buffer[corte:].lstrip()
            if frase:
                frases.append(frase)
        return frases

    def flush(self) -> list[str]:
        """Devuelve lo que quede pendiente (fin de la respuesta)."""
        resto = self._buffer.strip()
        self._buffer = ""
        return [resto] if resto else []

    def _buscar_corte(self) -> int:
        for indice, caracter in enumerate(self._buffer):
            if caracter in ".!?…\n" and indice + 1 >= self._min_len:
                return indice + 1
        if len(self._buffer) >= self._max_len:
            hueco = self._buffer.rfind(" ", 0, self._max_len)
            return hueco if hueco > 0 else self._max_len
        return 0


def split_sentences(text: str, *, max_len: int = 220) -> list[str]:
    """Parte un texto en frases cortas para sintetizar por streaming."""
    pieces = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if len(current) + len(piece) + 1 <= max_len:
            current = f"{current} {piece}".strip()
        else:
            if current:
                chunks.append(current)
            current = piece[:max_len]
    if current:
        chunks.append(current)
    return chunks


# ===============================
# Conversión a PCM de Discord
# ===============================
def ffmpeg_to_pcm(data: bytes, *, source_format: Optional[str] = None) -> bytes:
    """Decodifica audio (mp3/wav/...) a PCM s16 48 kHz estéreo con FFmpeg."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if source_format:
        command += ["-f", source_format]
    command += [
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "pipe:1",
    ]

    try:
        process = subprocess.run(
            command, input=data, capture_output=True, timeout=FFMPEG_TIMEOUT
        )
    except FileNotFoundError as exc:
        raise TTSError("FFmpeg no está instalado o no está en el PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise TTSError("FFmpeg tardó demasiado convirtiendo la voz.") from exc

    if process.returncode != 0 or not process.stdout:
        detail = process.stderr.decode("utf-8", "ignore").strip()[:200]
        raise TTSError(f"FFmpeg no pudo convertir la voz: {detail}")
    return process.stdout


# ===============================
# Proveedores
# ===============================
class EdgeTTS:
    """Voces neuronales gratuitas de Microsoft (edge-tts)."""

    def __init__(self, voice: str, rate: str = "+0%") -> None:
        self._voice = voice or "es-ES-AlvaroNeural"
        self._rate = rate or "+0%"

    @property
    def label(self) -> str:
        return f"edge-tts · {self._voice}"

    async def _ffmpeg_stream(self, spoken: str, rate: str):
        """MP3 de edge-tts -> PCM 48 kHz estéreo, en trozos, según llega."""
        import contextlib

        import edge_tts

        proceso = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def alimentar() -> None:
            try:
                async for trozo in edge_tts.Communicate(spoken, self._voice, rate=rate).stream():
                    if trozo.get("type") == "audio" and trozo.get("data"):
                        proceso.stdin.write(trozo["data"])  # type: ignore[union-attr]
                        await proceso.stdin.drain()  # type: ignore[union-attr]
            finally:
                with contextlib.suppress(Exception):
                    proceso.stdin.close()  # type: ignore[union-attr]

        tarea = asyncio.create_task(alimentar())
        try:
            while True:
                bloque = await proceso.stdout.read(FRAME_BYTES * 4)  # type: ignore[union-attr]
                if not bloque:
                    break
                yield bloque
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proceso.wait(), timeout=10)
            tarea.cancel()

    async def stream_pcm(self, text: str):
        """Voz en trozos PCM: se puede empezar a hablar antes de terminar."""
        spoken = clean_for_speech(text)
        if not spoken:
            return

        # edge-tts (servicio no oficial) falla de vez en cuando con
        # «No audio was received»: se reintenta, la segunda a ritmo normal.
        for intento, rate in enumerate((self._rate, "+0%")):
            emitido = False
            try:
                async for bloque in self._ffmpeg_stream(spoken, rate):
                    emitido = True
                    yield bloque
                return
            except Exception as exc:  # noqa: BLE001 - se reintenta
                if emitido:
                    log.warning("edge-tts se cortó a mitad: %s", exc)
                    return
                log.warning("edge-tts falló (intento %s/2, rate=%s): %s", intento + 1, rate, exc)
                await asyncio.sleep(0.35 * (intento + 1))
        raise TTSError("No pude generar la voz con edge-tts.")

    async def synthesize(self, text: str) -> bytes:
        trozos = bytearray()
        async for bloque in self.stream_pcm(text):
            trozos.extend(bloque)
        return bytes(trozos)

    async def warmup(self) -> None:
        return None


class OpenAITTS:
    """Voces de OpenAI (u otro endpoint compatible con /audio/speech)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        voice: str,
    ) -> None:
        from openai import AsyncOpenAI

        self._model = model or "gpt-4o-mini-tts"
        self._voice = voice or "alloy"
        self._client = AsyncOpenAI(
            base_url=base_url or None,
            api_key=api_key,
            timeout=45.0,
            max_retries=1,
        )

    @property
    def label(self) -> str:
        return f"OpenAI TTS · {self._model}/{self._voice}"

    async def synthesize(self, text: str) -> bytes:
        spoken = clean_for_speech(text)
        if not spoken:
            return b""

        try:
            response = await self._client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=spoken,
                response_format="wav",
            )
        except Exception as exc:
            log.exception("Error con OpenAI TTS")
            raise TTSError("No pude generar la voz con OpenAI.") from exc

        data = getattr(response, "content", None)
        if not isinstance(data, bytes):
            read = getattr(response, "aread", None)
            if read is None:
                raise TTSError("La API TTS devolvió una respuesta inesperada.")
            data = await read()

        if not data:
            raise TTSError("La API TTS devolvió audio vacío.")
        return await asyncio.to_thread(ffmpeg_to_pcm, data)

    async def warmup(self) -> None:
        return None


class ElevenLabsTTS:
    """Voces de ElevenLabs: las más humanas (prosodia y emoción).

    Usa por defecto ``eleven_flash_v2_5``, pensado para baja latencia.
    ``TTS_VOICE`` debe ser el ID de la voz (p. ej. la de tu biblioteca).
    """

    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"

    def __init__(self, *, api_key: str, voice: str, model: str) -> None:
        self._api_key = api_key
        self._voice = voice or "EXAVITQu4vr4xnSDxMaL"  # Sarah (multilingüe)
        self._model = model or "eleven_flash_v2_5"

    @property
    def label(self) -> str:
        return f"ElevenLabs · {self._model}"

    async def synthesize(self, text: str) -> bytes:
        import aiohttp

        spoken = clean_for_speech(text)
        if not spoken:
            return b""

        payload = {
            "text": spoken,
            "model_id": self._model,
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
        }
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        try:
            async with aiohttp.ClientSession() as session, session.post(
                self.URL.format(voice=self._voice),
                json=payload,
                headers=headers,
                timeout=45,
            ) as respuesta:
                if respuesta.status != 200:
                    detalle = (await respuesta.text())[:160]
                    raise TTSError(f"ElevenLabs respondió {respuesta.status}: {detalle}")
                datos = await respuesta.read()
        except aiohttp.ClientError as exc:
            raise TTSError("No pude conectar con ElevenLabs.") from exc

        if not datos:
            raise TTSError("ElevenLabs devolvió audio vacío.")
        return await asyncio.to_thread(ffmpeg_to_pcm, datos)

    async def warmup(self) -> None:
        return None


class GeminiTTS:
    """Voces de Google Gemini (muy naturales y con capa gratuita).

    ``TTS_VOICE`` es el nombre de la voz (Kore, Puck, Charon, Fenrir...).
    """

    URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent"
    )

    def __init__(self, *, api_key: str, voice: str, model: str) -> None:
        self._api_key = api_key
        self._voice = voice or "Kore"
        self._model = model or "gemini-2.5-flash-preview-tts"

    @property
    def label(self) -> str:
        return f"Gemini TTS · {self._model}/{self._voice}"

    async def synthesize(self, text: str) -> bytes:
        import base64

        import aiohttp

        spoken = clean_for_speech(text)
        if not spoken:
            return b""

        payload = {
            "contents": [{"parts": [{"text": spoken}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice}}
                },
            },
        }
        try:
            async with aiohttp.ClientSession() as session, session.post(
                self.URL.format(model=self._model),
                json=payload,
                headers={"x-goog-api-key": self._api_key},
                timeout=45,
            ) as respuesta:
                if respuesta.status != 200:
                    detalle = (await respuesta.text())[:160]
                    raise TTSError(f"Gemini respondió {respuesta.status}: {detalle}")
                datos = await respuesta.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise TTSError("No pude conectar con Gemini.") from exc

        try:
            partes = datos["candidates"][0]["content"]["parts"]
            audio_b64 = next(
                parte["inlineData"]["data"] for parte in partes if "inlineData" in parte
            )
            crudo = base64.b64decode(audio_b64)
        except Exception as exc:
            raise TTSError("Gemini no devolvió audio.") from exc

        # Gemini entrega PCM 24 kHz mono con cabecera de 44 bytes
        if crudo[:4] == b"RIFF":
            crudo = crudo[44:]
        return await asyncio.to_thread(
            bytes_to_48k_stereo_pcm, crudo, sample_rate=24000, channels=1
        )

    async def warmup(self) -> None:
        return None


# ===============================
# Voces locales (gratis, offline)
# ===============================
MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
# Voz por defecto: mexicana femenina (calidad «high», la más rápida: 0,16 s)
PIPER_DEFAULT = MODELS_DIR / "es_MX-claude-high.onnx"
KOKORO_DEFAULT_MODEL = MODELS_DIR / "kokoro-v1.0.onnx"
KOKORO_DEFAULT_VOICES = MODELS_DIR / "voices-v1.0.bin"


class PiperTTS:
    """Voz local con Piper (ONNX): gratis, offline y la más rápida.

    Medido: ~0,17 s por frase en CPU (9 veces más rápido que edge-tts).
    Descarga los modelos con `./run.sh --voices`.
    """

    def __init__(self, model_path: Path) -> None:
        self._path = Path(model_path)
        self._voice: Any = None
        self._lock = threading.Lock()

    @property
    def label(self) -> str:
        return f"Piper local · {self._path.stem}"

    def _cargar(self) -> Any:
        if self._voice is not None:
            return self._voice
        from piper import PiperVoice

        with self._lock:
            if self._voice is None:
                log.info("Cargando voz Piper '%s'…", self._path.name)
                self._voice = PiperVoice.load(str(self._path))
        return self._voice

    async def synthesize(self, text: str) -> bytes:
        spoken = clean_for_speech(text)
        if not spoken:
            return b""

        def run() -> bytes:
            voz = self._cargar()
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                voz.synthesize_wav(spoken, wav)
            return buffer.getvalue()

        try:
            wav = await asyncio.to_thread(run)
        except Exception as exc:
            raise TTSError(f"No pude sintetizar con Piper: {exc}") from exc
        if not wav:
            raise TTSError("Piper devolvió audio vacío.")
        return await asyncio.to_thread(ffmpeg_to_pcm, wav)

    async def warmup(self) -> None:
        await asyncio.to_thread(self._cargar)


class KokoroTTS:
    """Voz local con Kokoro-82M (ONNX): gratis, offline y muy natural.

    Más lenta que Piper en CPU (~2 s por frase), pero con mejor prosodia.
    """

    def __init__(self, model_path: Path, voices_path: Path, voice: str) -> None:
        self._model = Path(model_path)
        self._voices = Path(voices_path)
        self._voice = voice or "ef_dora"   # femenina en español
        self._kokoro: Any = None
        self._lock = threading.Lock()

    @property
    def label(self) -> str:
        return f"Kokoro local · {self._voice}"

    def _cargar(self) -> Any:
        if self._kokoro is not None:
            return self._kokoro
        from kokoro_onnx import Kokoro

        with self._lock:
            if self._kokoro is None:
                log.info("Cargando voz Kokoro '%s'…", self._voice)
                self._kokoro = Kokoro(str(self._model), str(self._voices))
        return self._kokoro

    async def synthesize(self, text: str) -> bytes:
        import numpy as np

        spoken = clean_for_speech(text)
        if not spoken:
            return b""

        def run() -> tuple[Any, int]:
            modelo = self._cargar()
            return modelo.create(spoken, voice=self._voice, lang="es", speed=1.05)

        try:
            muestras, frecuencia = await asyncio.to_thread(run)
        except Exception as exc:
            raise TTSError(f"No pude sintetizar con Kokoro: {exc}") from exc

        if muestras is None or len(muestras) == 0:
            raise TTSError("Kokoro devolvió audio vacío.")

        # float32 mono -> PCM 16 bits -> estéreo 48 kHz (sin pasar por FFmpeg)
        pcm16 = (np.clip(muestras, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        return await asyncio.to_thread(
            bytes_to_48k_stereo_pcm, pcm16, sample_rate=int(frecuencia), channels=1
        )

    async def warmup(self) -> None:
        await asyncio.to_thread(self._cargar)


class FallbackTTS:
    """Voz principal con respaldo local.

    edge-tts es un servicio no oficial y a veces devuelve «No audio was
    received». Si eso pasa, Mango sigue hablando con la voz local (Piper) en
    lugar de quedarse mudo.
    """

    def __init__(self, principal, respaldo) -> None:
        self._principal = principal
        self._respaldo = respaldo

    @property
    def label(self) -> str:
        return f"{self._principal.label} (respaldo: {self._respaldo.label})"

    async def stream_pcm(self, text: str):
        emitido = False
        try:
            async for bloque in self._principal.stream_pcm(text):
                emitido = True
                yield bloque
            return
        except Exception as exc:  # noqa: BLE001 - cualquier fallo activa el plan B
            if emitido:
                log.warning("La voz principal se cortó a mitad: %s", exc)
                return
            log.warning("La voz principal falló (%s); sigo con la local", exc)

        async for bloque in self._respaldo.stream_pcm(text):
            yield bloque

    async def synthesize(self, text: str) -> bytes:
        trozos = bytearray()
        async for bloque in self.stream_pcm(text):
            trozos.extend(bloque)
        return bytes(trozos)

    async def warmup(self) -> None:
        for servicio in (self._principal, self._respaldo):
            calentar = getattr(servicio, "warmup", None)
            if calentar is not None:
                try:
                    await calentar()
                except Exception:  # noqa: BLE001 - el precalentado es opcional
                    log.debug("Precalentado de %s falló", servicio, exc_info=True)


def _piper_local() -> Optional[object]:
    """Voz local de respaldo (Piper), o None si no está descargada.

    Se prefiere la masculina mexicana para que el cambio de voz no chirríe
    cuando el principal es una voz masculina.
    """
    candidatas = [
        MODELS_DIR / "es_MX-ald-medium.onnx",
        PIPER_DEFAULT,
        MODELS_DIR / "es_ES-davefx-medium.onnx",
    ]
    for ruta in candidatas:
        if not ruta.is_file():
            continue
        try:
            return PiperTTS(ruta)
        except Exception:  # noqa: BLE001 - se prueba la siguiente
            log.debug("No pude cargar la voz local %s", ruta, exc_info=True)
    return None


def build_tts(config) -> Optional[object]:
    """Crea el servicio de TTS según la configuración (o ``None``)."""
    principal = _build_primary_tts(config)
    if principal is None:
        return None
    # Si el principal es de red, se le pone la voz local detrás como red de
    # seguridad: nunca se queda mudo por un fallo de un servicio externo.
    if config.tts_provider not in {"local", "piper", "kokoro"}:
        respaldo = _piper_local()
        if respaldo is not None:
            return FallbackTTS(principal, respaldo)
    return principal


def _build_primary_tts(config) -> Optional[object]:
    """Crea el servicio de TTS según la configuración (o ``None``)."""
    if not config.tts_enabled:
        log.warning("TTS desactivado: falta TTS_API_KEY para el proveedor elegido")
        return None

    if config.tts_provider == "edge":
        try:
            import edge_tts  # noqa: F401
        except Exception:
            log.warning("edge-tts no está instalado: TTS desactivado")
            return None
        return EdgeTTS(config.tts_voice, config.tts_rate)

    if config.tts_provider == "elevenlabs":
        if not config.tts_api_key:
            log.warning("ElevenLabs sin clave (TTS_API_KEY): TTS desactivado")
            return None
        return ElevenLabsTTS(
            api_key=config.tts_api_key, voice=config.tts_voice, model=config.tts_model
        )

    if config.tts_provider == "gemini":
        if not config.tts_api_key:
            log.warning("Gemini sin clave (TTS_API_KEY): TTS desactivado")
            return None
        return GeminiTTS(
            api_key=config.tts_api_key, voice=config.tts_voice, model=config.tts_model
        )

    if config.tts_provider in {"local", "piper", "kokoro"}:
        elegido = config.tts_provider
        if elegido == "local":
            # Automático: Piper es el más rápido, Kokoro suena mejor.
            elegido = "piper" if PIPER_DEFAULT.is_file() else "kokoro"

        if elegido == "piper":
            ruta = PIPER_DEFAULT
            if config.tts_model.endswith(".onnx"):
                ruta = Path(config.tts_model)
                if not ruta.is_absolute() and not ruta.is_file():
                    ruta = MODELS_DIR / ruta.name
            if not ruta.is_file():
                log.warning(
                    "No encuentro la voz de Piper (%s). Descárgala con: ./run.sh --voices",
                    ruta,
                )
                return None
            return PiperTTS(ruta)

        modelo = KOKORO_DEFAULT_MODEL
        if config.tts_model.endswith(".onnx"):
            modelo = Path(config.tts_model)
            if not modelo.is_absolute() and not modelo.is_file():
                modelo = MODELS_DIR / modelo.name
        if not (modelo.is_file() and KOKORO_DEFAULT_VOICES.is_file()):
            log.warning(
                "Faltan los modelos de Kokoro en %s. Descárgalos con: ./run.sh --voices",
                MODELS_DIR,
            )
            return None
        return KokoroTTS(modelo, KOKORO_DEFAULT_VOICES, config.tts_voice)

    return OpenAITTS(
        api_key=config.tts_api_key,
        base_url=config.tts_base_url,
        model=config.tts_model,
        voice=config.tts_voice,
    )
