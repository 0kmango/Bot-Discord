"""Carga y validación de la configuración del bot.

Toda la configuración vive en variables de entorno (archivo ``.env``).
Así los tokens nunca se escriben en el código ni se suben al repositorio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv es opcional: si falta, se usan las variables del sistema
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class ConfigError(RuntimeError):
    """Error de configuración con un mensaje claro para quien ejecuta el bot."""


def _load_env_file() -> None:
    if ENV_FILE.is_file():
        if load_dotenv is None:
            raise ConfigError(
                "Falta el paquete python-dotenv. "
                "Instala las dependencias con: pip install -r requirements.txt"
            )
        load_dotenv(ENV_FILE)


def _raw(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _str(name: str, default: str = "") -> str:
    return _raw(name) or default


def _required(name: str) -> str:
    value = _raw(name)
    if not value:
        raise ConfigError(
            f"Falta la variable {name!r}. Copia .env.example a .env y rellénala."
        )
    return value


def _int(name: str, default: int, *, minimum: int = 1, maximum: int = 10**9) -> int:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name!r} debe ser un número entero (recibido: {raw!r}).") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name!r} debe estar entre {minimum} y {maximum} (recibido: {value}).")
    return value


def _float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 2.0) -> float:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = float(raw.replace(",", "."))
    except ValueError as exc:
        raise ConfigError(f"{name!r} debe ser un número (recibido: {raw!r}).") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name!r} debe estar entre {minimum} y {maximum} (recibido: {value}).")
    return value


def _int_or_none(name: str) -> int | None:
    raw = _raw(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name!r} debe ser un ID numérico (recibido: {raw!r}).") from exc


def _bool(name: str, default: bool = False) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on", "y"}


def _choice(name: str, default: str, options: set[str]) -> str:
    value = _str(name, default).lower()
    if value not in options:
        raise ConfigError(
            f"{name!r} debe ser uno de {sorted(options)} (recibido: {value!r})."
        )
    return value


def _id_set(name: str) -> frozenset[int]:
    raw = _raw(name)
    if raw is None:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(
                f"{name!r} debe contener IDs numéricos separados por comas "
                f"(valor inválido: {chunk!r})."
            ) from exc
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class Config:
    """Configuración inmutable del bot."""

    # Discord
    discord_token: str
    owner_ids: frozenset[int] = field(default_factory=frozenset)
    command_prefix: str = "!"

    # Comportamiento
    log_level: str = "INFO"
    idle_timeout: int = 0   # 0 = nunca desconectar por inactividad
    alone_grace: int = 20
    default_volume: float = 0.5
    max_queue: int = 100
    max_playlist_tracks: int = 50

    # Integraciones opcionales
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    genius_token: str = ""
    genius_client_id: str = ""
    genius_client_secret: str = ""
    ytdlp_cookies: str = ""

    # ---- Mango AI ----
    # LLM (cualquier API compatible con OpenAI: OpenAI, Groq, Ollama, OpenRouter)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_reasoning_effort: str = ""
    # Respaldo opcional: si el principal falla, se usa este proveedor
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    ai_history_limit: int = 20
    ai_max_reply_chars: int = 1500
    ai_channel_id: int | None = None

    # STT: "local" (faster-whisper, sin API) | "openai" | "groq"
    stt_provider: str = "local"
    stt_model: str = "small"
    stt_api_key: str = ""
    stt_base_url: str = ""
    stt_language: str = "es"

    # TTS: "edge" (gratis) | "openai"
    tts_provider: str = "edge"
    tts_voice: str = "es-ES-AlvaroNeural"
    tts_model: str = ""   # vacío = el que corresponda al proveedor
    tts_api_key: str = ""
    tts_base_url: str = ""
    tts_rate: str = "+10%"

    # Voz
    voice_dave: str = "auto"
    ai_voice_channel_id: int | None = None
    wake_words: str = "oye mango,hey mango,hola mango,escucha mango"
    voice_silence_ms: int = 500
    voice_min_speech_ms: int = 250
    voice_energy: float = 0.012
    # Umbral cuando hay música sonando: el micro del usuario puede captarla y
    # sin subirlo el detector daría la música por "voz" todo el rato.
    voice_energy_music: float = 0.03
    # Ganancia de la voz de Mango (1.0 = sin tocar). 1.5 la deja por encima de
    # la música sin distorsionar; se aplica al mezclar.
    tts_gain: float = 1.8
    # Filtro de conversación: con la ventana abierta, solo responde si la frase
    # va dirigida a él (evita meterse en la charla de otras personas).
    voice_conversation_filter: bool = True
    # ¿Puede cualquiera que esté escuchando pedir «!mango di <texto>»?
    # false = solo el dueño (recomendado: la voz del bot es su identidad).
    voice_say_public: bool = False
    # Borrar el historial de conversación de la IA al arrancar: el bot empieza
    # sin memoria (no «recuerda» canciones de la sesión anterior).
    clear_memory_on_start: bool = True
    # Segundos que la conversación queda abierta tras cada respuesta.
    # 0  = hay que decir «oye Mango» en CADA petición.
    # >0 = conversación fluida: sigue el hilo sin repetir la palabra clave, y
    #      con el filtro de intención ignora la charla que no va con él.
    voice_session_timeout: int = 30
    # Modelos: `tiny` solo para detectar la palabra clave (5× más rápido),
    # `STT_MODEL` para entender el comando ya dentro de la conversación.
    voice_wake_model: str = "tiny"
    # Audios más largos que esto no se transcriben si no hay conversación
    # (así la música o una charla larga no pasan por el reconocedor).
    voice_wake_max_seconds: int = 6
    # true = transcribir TODO lo que se dice (más lento y menos privado)
    voice_transcribe_all: bool = False
    # Mostrar en Discord el texto que se oyó (desactivado por defecto)
    voice_show_transcript: bool = False
    # Publicar en el canal de texto la respuesta que dio por voz
    # (desactivado: lo hablado no deja rastro en el chat)
    voice_post_replies: bool = False

    @property
    def spotify_enabled(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def lyrics_enabled(self) -> bool:
        return bool(
            self.genius_token or (self.genius_client_id and self.genius_client_secret)
        )

    @property
    def ai_enabled(self) -> bool:
        """Hay un LLM configurado (base para texto y voz)."""
        return bool(self.llm_api_key and self.llm_model)

    @property
    def llm_fallback_enabled(self) -> bool:
        return bool(
            self.llm_fallback_api_key
            and self.llm_fallback_model
            and self.llm_fallback_model != self.llm_model
        )

    @property
    def stt_enabled(self) -> bool:
        if self.stt_provider == "local":
            return True  # faster-whisper es local, no necesita clave
        return bool(self.stt_api_key)

    @property
    def tts_enabled(self) -> bool:
        # edge-tts y las voces locales (Piper/Kokoro) no necesitan clave.
        if self.tts_provider in {"edge", "local", "piper", "kokoro"}:
            return True
        return bool(self.tts_api_key)

    @property
    def voice_enabled(self) -> bool:
        """Se puede activar la charla por voz."""
        return self.ai_enabled and self.stt_enabled and self.tts_enabled

    @property
    def wake_word_list(self) -> tuple[str, ...]:
        return tuple(
            word.strip().lower() for word in self.wake_words.split(",") if word.strip()
        )

    @property
    def cookies_path(self) -> Path | None:
        if not self.ytdlp_cookies:
            return None
        path = Path(self.ytdlp_cookies)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path if path.is_file() else None


def load_config() -> Config:
    """Lee el entorno y devuelve una :class:`Config` validada."""

    _load_env_file()

    owner_ids = _id_set("OWNER_IDS") or _id_set("OWNER_ID")

    prefix = _str("COMMAND_PREFIX", "!")[:5] or "!"
    log_level = _str("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(
            "LOG_LEVEL debe ser DEBUG, INFO, WARNING, ERROR o CRITICAL "
            f"(recibido: {log_level!r})."
        )

    return Config(
        discord_token=_required("DISCORD_TOKEN"),
        owner_ids=owner_ids,
        command_prefix=prefix,
        log_level=log_level,
        idle_timeout=_int("IDLE_TIMEOUT", 0, minimum=0),
        alone_grace=_int("ALONE_GRACE", 20, minimum=0, maximum=600),
        default_volume=_float("DEFAULT_VOLUME", 0.5, minimum=0.0, maximum=2.0),
        max_queue=_int("MAX_QUEUE", 100, minimum=1, maximum=1000),
        max_playlist_tracks=_int("MAX_PLAYLIST_TRACKS", 50, minimum=1, maximum=200),
        spotify_client_id=_str("SPOTIFY_CLIENT_ID"),
        spotify_client_secret=_str("SPOTIFY_CLIENT_SECRET"),
        genius_token=_str("GENIUS_TOKEN"),
        genius_client_id=_str("GENIUS_CLIENT_ID"),
        genius_client_secret=_str("GENIUS_CLIENT_SECRET"),
        ytdlp_cookies=_str("YTDLP_COOKIES"),
        # ---- Mango AI ----
        llm_base_url=_str("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_api_key=_str("LLM_API_KEY"),
        llm_model=_str("LLM_MODEL", "gpt-4o-mini"),
        llm_temperature=_float("LLM_TEMPERATURE", 0.7, minimum=0.0, maximum=2.0),
        llm_reasoning_effort=_choice(
            "LLM_REASONING_EFFORT", "", {"", "low", "medium", "high"}
        ),
        llm_fallback_base_url=_str("LLM_FALLBACK_BASE_URL"),
        llm_fallback_api_key=_str("LLM_FALLBACK_API_KEY"),
        llm_fallback_model=_str("LLM_FALLBACK_MODEL"),
        ai_history_limit=_int("AI_HISTORY_LIMIT", 20, minimum=2, maximum=200),
        ai_max_reply_chars=_int("AI_MAX_REPLY_CHARS", 1500, minimum=80, maximum=4000),
        ai_channel_id=_int_or_none("AI_CHANNEL_ID"),
        stt_provider=_choice("STT_PROVIDER", "local", {"local", "openai", "groq"}),
        stt_model=_str("STT_MODEL", "small"),
        stt_api_key=_str("STT_API_KEY"),
        stt_base_url=_str("STT_BASE_URL"),
        stt_language=_str("STT_LANGUAGE", "es"),
        tts_provider=_choice(
            "TTS_PROVIDER",
            "edge",
            {"edge", "openai", "elevenlabs", "gemini", "local", "piper", "kokoro"},
        ),
        tts_voice=_str("TTS_VOICE", "es-ES-AlvaroNeural"),
        tts_model=_str("TTS_MODEL"),
        tts_api_key=_str("TTS_API_KEY"),
        tts_base_url=_str("TTS_BASE_URL"),
        tts_rate=_str("TTS_RATE", "+10%"),
        ai_voice_channel_id=_int_or_none("AI_VOICE_CHANNEL_ID"),
        voice_dave=_choice("VOICE_DAVE", "auto", {"auto", "off"}),
        voice_wake_model=_str("VOICE_WAKE_MODEL", "tiny"),
        voice_wake_max_seconds=_int(
            "VOICE_WAKE_MAX_SECONDS", 6, minimum=1, maximum=30
        ),
        voice_transcribe_all=_bool("VOICE_TRANSCRIBE_ALL", False),
        voice_show_transcript=_bool("VOICE_SHOW_TRANSCRIPT", False),
        voice_post_replies=_bool("VOICE_POST_REPLIES", False),
        wake_words=_str(
            "WAKE_WORDS", "oye mango,hey mango,hola mango,escucha mango"
        ),
        voice_silence_ms=_int("VOICE_SILENCE_MS", 500, minimum=200, maximum=3000),
        voice_min_speech_ms=_int("VOICE_MIN_SPEECH_MS", 350, minimum=100, maximum=2000),
        voice_energy=_float("VOICE_ENERGY", 0.012, minimum=0.0005, maximum=0.5),
        voice_energy_music=_float("VOICE_ENERGY_MUSIC", 0.03, minimum=0.0005, maximum=0.5),
        tts_gain=_float("TTS_GAIN", 1.8, minimum=1.0, maximum=3.0),
        voice_session_timeout=_int(
            "VOICE_SESSION_TIMEOUT", 30, minimum=0, maximum=600
        ),
        voice_conversation_filter=_bool("VOICE_CONVERSATION_FILTER", True),
        voice_say_public=_bool("VOICE_SAY_PUBLIC", False),
        clear_memory_on_start=_bool("CLEAR_MEMORY_ON_START", True),
    )
