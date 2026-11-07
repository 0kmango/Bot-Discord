"""Reconocimiento de voz (STT).

Dos proveedores:

* ``local``  → faster-whisper en CPU (sin API, gratis, privado).
* ``openai`` / ``groq`` → endpoint compatible con OpenAI ``/audio/transcriptions``.

La entrada es siempre PCM 48 kHz estéreo de Discord; se convierte a mono
16 kHz antes de transcribir.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from mango.services.audio import STT_RATE, mono16k_to_wav, preparar_para_stt

log = logging.getLogger(__name__)

LOCAL_MODELS = {
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v1",
    "large-v2",
    "large-v3",
    "distil-large-v3",
}

DEFAULT_API_MODELS = {
    # Medido en esta máquina: large-v3 tarda lo mismo que turbo (≈0,5 s) y
    # transcribe mejor (mayúsculas, títulos y nombres propios).
    "groq": "whisper-large-v3",
    "openai": "whisper-1",
}


class STTError(RuntimeError):
    """Fallo al transcribir."""


# Prompts guía: sesgan el reconocedor hacia el vocabulario del bot. Mejoran
# mucho la precisión con nombres de canciones sin costar tiempo extra.
WAKE_PROMPT = "Oye mango. Hey mango. Hola mango. Escucha mango."
COMMAND_PROMPT = (
    "Oye mango, pon música, reproduce, siguiente canción, salta, para, "
    "sube el volumen, baja el volumen, qué está sonando, la letra de."
)
# Para la API se manda uno solo (cubre las dos fases) y con nombres propios
# frecuentes: ayuda con artistas y títulos.
PROMPT_API = (
    "Oye mango. Hola mango. Hey mango. Escucha mango. Pon música, reproduce, "
    "siguiente canción, sube el volumen, qué está sonando, la letra de, añade "
    "a la cola. Daft Punk, Los Prisioneros, Bad Bunny, $uicideboy$, "
    "Roxy Music, Red Hot Chili Peppers, Nirvana, Avalon, Californication."
)


class LocalWhisperSTT:
    """faster-whisper cargado de forma perezosa (la primera vez tarda)."""

    def __init__(self, model_size: str, language: str, *, prompt: str = "") -> None:
        self._model_size = model_size or "small"
        self._language = language or None
        self._prompt = prompt or None
        self._model = None
        self._lock = asyncio.Lock()

    @property
    def label(self) -> str:
        return f"faster-whisper · {self._model_size}"

    async def _ensure_model(self):
        if self._model is not None:
            return self._model

        async with self._lock:
            if self._model is not None:
                return self._model
            log.info("Cargando modelo Whisper local '%s'…", self._model_size)

            def load():
                from faster_whisper import WhisperModel

                return WhisperModel(self._model_size, device="cpu", compute_type="int8")

            self._model = await asyncio.to_thread(load)
            log.info("Modelo Whisper listo")
        return self._model

    async def transcribe(self, pcm48_stereo: bytes) -> str:
        samples = preparar_para_stt(pcm48_stereo)
        if samples.size < STT_RATE * 0.2:  # menos de 200 ms: ruido
            return ""

        model = await self._ensure_model()

        def run() -> str:
            segments, _info = model.transcribe(
                samples,
                language=self._language,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt=self._prompt,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

        try:
            return await asyncio.to_thread(run)
        except Exception as exc:
            log.exception("Error transcribiendo en local")
            raise STTError("No pude transcribir el audio.") from exc

    async def warmup(self) -> None:
        await self._ensure_model()


class APIWhisperSTT:
    """Transcripción vía API compatible con OpenAI (OpenAI, Groq, etc.)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        language: str,
        prompt: str = "",
    ) -> None:
        from openai import AsyncOpenAI

        self._model = model
        self._language = language or None
        # Contexto para el reconocedor: mejora nombres propios y jerga musical.
        self._prompt = prompt or None
        self._client = AsyncOpenAI(
            base_url=base_url or None,
            api_key=api_key,
            timeout=30.0,
            max_retries=1,
        )

    @property
    def label(self) -> str:
        return f"API · {self._model}"

    async def transcribe(self, pcm48_stereo: bytes) -> str:
        samples = preparar_para_stt(pcm48_stereo)
        if samples.size < STT_RATE * 0.2:
            return ""

        wav = mono16k_to_wav(samples)
        try:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=("mango.wav", wav, "audio/wav"),
                language=self._language,
                response_format="text",
                prompt=self._prompt,
            )
        except Exception as exc:
            log.exception("Error transcribiendo por API")
            raise STTError("El servicio de transcripción no respondió.") from exc

        if isinstance(response, str):
            return response.strip()
        return str(getattr(response, "text", "") or "").strip()

    async def warmup(self) -> None:
        return None


def build_wake_stt(config, main: Optional[object] = None) -> Optional[object]:
    """STT rápido solo para detectar la palabra clave.

    Con ``STT_PROVIDER=local`` usa un modelo pequeño (``tiny``/``base``), unas
    5 veces más rápido que ``small``: la frase «oye Mango» es corta y el
    comparador difuso tolera sus errores. El comando completo se transcribe
    después con el modelo bueno (``build_stt``).
    """
    if config.stt_provider != "local":
        # Con API se reutiliza el MISMO servicio: así una frase activada no se
        # transcribe dos veces (una llamada, no dos).
        return main if main is not None else build_stt(config)

    if not config.stt_enabled:
        return None

    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return build_stt(config)

    modelo = config.voice_wake_model if config.voice_wake_model in LOCAL_MODELS else "tiny"
    if modelo == config.stt_model:
        return build_stt(config)
    return LocalWhisperSTT(modelo, config.stt_language, prompt=WAKE_PROMPT)


def build_stt(config) -> Optional[object]:
    """Crea el servicio de STT según la configuración (o ``None``)."""
    if not config.stt_enabled:
        log.warning("STT desactivado: falta STT_API_KEY para el proveedor elegido")
        return None

    if config.stt_provider == "local":
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            log.warning("faster-whisper no está instalado: STT local desactivado")
            return None
        model = config.stt_model if config.stt_model in LOCAL_MODELS else "small"
        return LocalWhisperSTT(model, config.stt_language, prompt=COMMAND_PROMPT)

    provider = config.stt_provider
    base_url = config.stt_base_url or (
        "https://api.groq.com/openai/v1"
        if provider == "groq"
        else "https://api.openai.com/v1"
    )
    model = config.stt_model
    if model in LOCAL_MODELS or not model:
        model = DEFAULT_API_MODELS.get(provider, "whisper-1")

    return APIWhisperSTT(
        base_url=base_url,
        api_key=config.stt_api_key,
        model=model,
        language=config.stt_language,
        prompt=PROMPT_API,
    )
