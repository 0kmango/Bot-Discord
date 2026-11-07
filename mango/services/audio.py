"""Audio: PCM de Discord, detección de voz y mezclador música + voz.

Discord exige que cada lectura de un ``AudioSource`` devuelva exactamente
20 ms de PCM 16 bits 48 kHz estéreo (3 840 bytes). El :class:`MixerSource`
siempre los devuelve, y va mezclando la música con la voz de Mango AI:
cuando Mango habla, la música baja a :data:`DUCK_VOLUME` en lugar de cortarse.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from collections import deque
from collections.abc import Callable
from typing import Optional

import discord
import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000        # 960
FRAME_BYTES = FRAME_SAMPLES * CHANNELS * SAMPLE_WIDTH  # 3840

SILENCE_FRAME = b"\x00" * FRAME_BYTES
# Cuando habla Mango, la música se aparta (así se distingue su voz). Al hablar
# el usuario NO se toca el volumen: la música sigue igual.
DUCK_VOLUME = 0.12
STT_RATE = 16000

# Ganancia de la voz y limitador suave: sube el nivel sin distorsionar. Los
# proveedores no entregan el mismo nivel (edge ~0.53 de pico, Piper ~0.71), así
# que se sube con margen y se recorta de forma suave a partir de este límite.
VOICE_GAIN = 1.5
LIMITE_SUAVE = 0.9

# Detección de voz adaptativa: se estima el ruido de fondo con el nivel mínimo
# de los últimos 2 s y se exige superarlo por un margen. Así el eco de la música
# no se confunde con voz y no hay que bajar el volumen de la canción.
RUDEZA_WINDOW = 100          # frames de 20 ms (2 s)
RUIDO_MARGEN = 1.8           # ≈ 5 dB por encima del ruido de fondo
TECHO_RUIDO = 0.10           # el umbral adaptativo nunca pasa de aquí


def boost_pcm(pcm: bytes, gain: float = VOICE_GAIN) -> bytes:
    """Sube el nivel de la voz con un limitador suave (sin clipping duro)."""
    if not pcm or gain <= 1.0:
        return pcm

    muestras = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    salida = muestras * float(gain)
    exceso = np.abs(salida) > LIMITE_SUAVE
    if exceso.any():
        signo = np.sign(salida[exceso])
        sobra = (np.abs(salida[exceso]) - LIMITE_SUAVE) / (1.0 - LIMITE_SUAVE)
        salida[exceso] = signo * (LIMITE_SUAVE + (1.0 - LIMITE_SUAVE) * np.tanh(sobra))
    return np.clip(salida * 32767.0, -32768, 32767).astype(np.int16).tobytes()


# ===============================
# Utilidades PCM
# ===============================
def frame_rms(frame: bytes) -> float:
    """Energía (RMS) normalizada de un frame, en el rango 0..1."""
    usable = len(frame) - (len(frame) % (SAMPLE_WIDTH * CHANNELS))
    if usable <= 0:
        return 0.0
    samples = np.frombuffer(frame[:usable], dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2)))


def tail_seconds(pcm: bytes, seconds: float) -> bytes:
    """Se queda con los últimos ``seconds`` de audio (para analizar la cola)."""
    limite = int(max(0.5, seconds) * SAMPLE_RATE) * CHANNELS * SAMPLE_WIDTH
    if len(pcm) <= limite:
        return pcm
    return pcm[-limite:]


def stereo_to_mono_16k(pcm: bytes) -> np.ndarray:
    """Convierte PCM 48 kHz estéreo s16 a mono 16 kHz float32 (para Whisper)."""
    usable = len(pcm) - (len(pcm) % (SAMPLE_WIDTH * CHANNELS))
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)

    data = (
        np.frombuffer(pcm[:usable], dtype=np.int16).reshape(-1, CHANNELS).astype(np.float32)
        / 32768.0
    )
    mono = data.mean(axis=1)

    target = mono.size // 3  # 48 kHz -> 16 kHz
    if target == 0:
        return np.zeros(0, dtype=np.float32)
    return mono[: target * 3].reshape(target, 3).mean(axis=1).astype(np.float32)


def _fir_paso_bajo(taps: int = 31, corte: float = 7400.0) -> np.ndarray:
    """Filtro FIR (ventana de Hamming) para bajar de 48 kHz a 16 kHz sin aliasing."""
    centro = (taps - 1) / 2
    indices = np.arange(taps)
    h = np.sinc(2 * corte / SAMPLE_RATE * (indices - centro)) * np.hamming(taps)
    return h / h.sum()


_LPF_48K = _fir_paso_bajo()


def preparar_para_stt(pcm48_estereo: bytes, *, ganancia_max: float = 12.0) -> np.ndarray:
    """Convierte el audio de Discord a lo que mejor entiende Whisper.

    48 kHz estéreo → mono con filtro paso-bajo → 16 kHz, y **se sube el nivel**
    si la persona habló flojo (un AGC sencillo). Se nota bastante en la
    transcripción: micrófonos bajos o gente que susurra ahora se entienden.
    """
    usable = len(pcm48_estereo) - (len(pcm48_estereo) % (SAMPLE_WIDTH * CHANNELS))
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)

    datos = (
        np.frombuffer(pcm48_estereo[:usable], dtype=np.int16)
        .reshape(-1, CHANNELS)
        .astype(np.float32)
        / 32768.0
    )
    mono = datos.mean(axis=1)

    # Filtro antes de diezmar (evita que las frecuencias altas se confundan)
    if mono.size > len(_LPF_48K):
        mono = np.convolve(mono, _LPF_48K, mode="same")

    objetivo = mono.size // 3
    if objetivo == 0:
        return np.zeros(0, dtype=np.float32)
    muestras = mono[: objetivo * 3].reshape(objetivo, 3).mean(axis=1)

    # AGC: solo si hay voz y llega flojita
    pico = float(np.max(np.abs(muestras))) if muestras.size else 0.0
    rms = float(np.sqrt(np.mean(muestras ** 2))) if muestras.size else 0.0
    if rms > 0.005 and 0 < pico < 0.4:
        ganancia = min(0.9 / pico, ganancia_max)
        muestras = np.clip(muestras * ganancia, -1.0, 1.0)

    return muestras.astype(np.float32)


def mono16k_to_wav(samples: np.ndarray) -> bytes:
    """Empaqueta muestras mono 16 kHz float32 como WAV 16 bits."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16).tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(STT_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


def bytes_to_48k_stereo_pcm(raw: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Convierte PCM crudo (cualquier rate/canales) a 48 kHz estéreo s16."""
    usable = len(raw) - (len(raw) % (SAMPLE_WIDTH * channels))
    if usable <= 0:
        return b""

    data = np.frombuffer(raw[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    if sample_rate != SAMPLE_RATE and data.size > 1:
        target = int(round(data.size * SAMPLE_RATE / sample_rate))
        if target <= 0:
            return b""
        positions = np.linspace(0, data.size - 1, target)
        data = np.interp(positions, np.arange(data.size), data)

    stereo = np.repeat(data, CHANNELS)
    return np.clip(stereo * 32767.0, -32768, 32767).astype(np.int16).tobytes()


# ===============================
# Mezclador
# ===============================
class MixerSource(discord.AudioSource):
    """Fuente permanente del canal: música + voz mezcladas.

    Se instala una sola vez con ``voice.play(mixer)``. Después, la música
    se cambia con :meth:`set_music` y la voz se encola con :meth:`push_tts`,
    sin cortar nunca la reproducción.
    """

    def __init__(self, volume: float = 0.5, *, tts_gain: float = VOICE_GAIN) -> None:
        self._music: Optional[discord.AudioSource] = None
        self._on_music_end: Optional[Callable[[], None]] = None
        self._music_active = False
        self._music_paused = False
        self._volume = float(volume)
        # Nivel de la voz (se sube con limitador suave para que no suene baja
        # frente a la música).
        self._tts_gain = max(1.0, min(3.0, float(tts_gain)))

        self._tts: deque[bytes] = deque()
        self._tts_partial = bytearray()
        self._lock = threading.Lock()

        # Estadísticas para diagnóstico (!diag)
        self._frames_served = 0
        self._track_frames = 0
        self._track_peak = 0.0

    # ---- API desde el event loop ----
    def set_music(
        self,
        source: Optional[discord.AudioSource],
        *,
        on_end: Optional[Callable[[], None]] = None,
    ) -> None:
        with self._lock:
            old, self._music = self._music, source
            self._on_music_end = on_end
            self._music_active = source is not None
            self._track_frames = 0
            self._track_peak = 0.0
        if old is not None and old is not source:
            self._cleanup_source(old)

    def clear_music(self) -> None:
        with self._lock:
            old, self._music = self._music, None
            self._on_music_end = None
            self._music_active = False
        if old is not None:
            self._cleanup_source(old)

    @property
    def music_active(self) -> bool:
        return self._music_active

    @property
    def music_paused(self) -> bool:
        return self._music_paused

    def set_music_paused(self, paused: bool) -> None:
        self._music_paused = paused

    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, volume: float) -> float:
        self._volume = max(0.0, min(2.0, float(volume)))
        return self._volume

    def push_tts(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            self._tts.append(pcm)

    def clear_tts(self) -> None:
        with self._lock:
            self._tts.clear()
            self._tts_partial.clear()

    @property
    def speaking(self) -> bool:
        """True mientras queden frames de voz por reproducir."""
        with self._lock:
            return bool(self._tts or self._tts_partial)

    def is_opus(self) -> bool:
        return False

    # ---- Hilo de audio de Discord ----
    def read(self) -> bytes:
        music = self._read_music()
        tts = self._read_tts()
        if tts is not None:
            tts = boost_pcm(tts, self._tts_gain)

        if tts is None:
            out = self._apply_volume(music)
        elif music == SILENCE_FRAME:
            out = tts
        else:
            out = self._mix(music, tts)

        self._frames_served += 1
        if self._music_active and music != SILENCE_FRAME:
            self._track_frames += 1
            peak = float(np.abs(np.frombuffer(out, dtype=np.int16)).max()) / 32768.0
            if peak > self._track_peak:
                self._track_peak = peak
        return out

    # ---- Diagnóstico ----
    @property
    def stats(self) -> dict[str, float]:
        """Estado del mezclador para `!diag`."""
        return {
            "frames_served": float(self._frames_served),
            "track_frames": float(self._track_frames),
            "track_seconds": self._track_frames * FRAME_MS / 1000.0,
            "track_peak": self._track_peak,
            "music_active": float(self._music_active),
            "music_paused": float(self._music_paused),
            "speaking": float(self.speaking),
            "volume": self._volume,
            "tts_gain": self._tts_gain,
        }

    def _read_music(self) -> bytes:
        if self._music_paused:
            return SILENCE_FRAME

        with self._lock:
            source = self._music
            callback = self._on_music_end
        if source is None:
            return SILENCE_FRAME

        try:
            frame = source.read()
        except Exception:
            log.exception("Error leyendo la fuente de música")
            frame = b""

        if not frame:
            with self._lock:
                old, self._music = self._music, None
                self._on_music_end = None
                self._music_active = False
            if old is not None:
                self._cleanup_source(old)
            if callback is not None:
                try:
                    callback()
                except Exception:
                    log.exception("Error en el callback de fin de canción")
            return SILENCE_FRAME

        if len(frame) < FRAME_BYTES:
            frame += SILENCE_FRAME[: FRAME_BYTES - len(frame)]
        elif len(frame) > FRAME_BYTES:
            frame = frame[:FRAME_BYTES]
        return frame

    def _read_tts(self) -> Optional[bytes]:
        with self._lock:
            while len(self._tts_partial) < FRAME_BYTES and self._tts:
                self._tts_partial.extend(self._tts.popleft())

            if len(self._tts_partial) >= FRAME_BYTES:
                out = bytes(self._tts_partial[:FRAME_BYTES])
                del self._tts_partial[:FRAME_BYTES]
                return out

            if self._tts_partial:  # último frame corto: rellenar con silencio
                out = bytes(self._tts_partial)
                out += SILENCE_FRAME[: FRAME_BYTES - len(out)]
                self._tts_partial.clear()
                return out
        return None

    def _apply_volume(self, frame: bytes) -> bytes:
        factor = self._volume
        if factor == 1.0 or frame == SILENCE_FRAME:
            return frame
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return np.clip(samples * factor, -32768, 32767).astype(np.int16).tobytes()

    def _mix(self, music: bytes, tts: bytes) -> bytes:
        music_samples = np.frombuffer(music, dtype=np.int16).astype(np.int32)
        tts_samples = np.frombuffer(tts, dtype=np.int16).astype(np.int32)
        size = min(music_samples.size, tts_samples.size)
        if size == 0:
            return tts
        mixed = music_samples[:size] * (self._volume * DUCK_VOLUME) + tts_samples[:size]
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()

    @staticmethod
    def _cleanup_source(source: discord.AudioSource) -> None:
        try:
            source.cleanup()
        except Exception:
            log.debug("No pude limpiar la fuente de audio", exc_info=True)


# ===============================
# Detección de voz (VAD por energía)
# ===============================
class UtteranceCollector:
    """Acumula frames de un usuario y devuelve frases completas.

    VAD sencillo por energía con histéresis:
      · guarda un pequeño preroll para no cortar el inicio de la frase,
      · espera ``silence_ms`` de silencio para cerrar la frase,
      · descarta fragmentos más cortos que ``min_speech_ms``.

    El umbral se **adapta al ruido de fondo** (la música que el micro del
    usuario capta, el ventilador, etc.): se mide el nivel mínimo de los últimos
    2 s y se exige estar por encima de él. Así el eco constante no se confunde
    con voz y **no hace falta bajar la música** cuando alguien habla.
    """

    def __init__(
        self,
        *,
        energy: float,
        silence_ms: int,
        min_speech_ms: int,
        max_ms: int = 15000,
        preroll_frames: int = 16,
    ) -> None:
        self._energy = float(energy)
        self._silence_frames = max(1, int(silence_ms / FRAME_MS))
        self._min_frames = max(1, int(min_speech_ms / FRAME_MS))
        self._max_bytes = max(1, int(max_ms / FRAME_MS)) * FRAME_BYTES

        self._preroll: deque[bytes] = deque(maxlen=max(0, preroll_frames))
        self._buffer = bytearray()
        self._speech_frames = 0
        self._silent_run = 0
        self._recording = False
        # Niveles recientes para estimar el ruido de fondo (2 s).
        self._levels: deque[float] = deque(maxlen=RUDEZA_WINDOW)

    @property
    def recording(self) -> bool:
        return self._recording

    def threshold(self) -> float:
        """Umbral efectivo: el fijo, o el ruido de fondo + margen si es mayor."""
        if not self._levels:
            return self._energy
        fondo = min(self._levels) * RUIDO_MARGEN
        return max(self._energy, min(fondo, TECHO_RUIDO))

    def feed(self, frame: bytes) -> Optional[bytes]:
        """Añade un frame; devuelve la frase completa cuando termina."""
        if not frame:
            return None

        level = frame_rms(frame)
        self._levels.append(level)
        umbral = self.threshold()

        if not self._recording:
            if self._preroll.maxlen:
                self._preroll.append(frame)
            if level >= umbral:
                self._recording = True
                self._buffer = bytearray(b"".join(self._preroll))
                self._preroll.clear()
                self._speech_frames = 1
                self._silent_run = 0
            return None

        self._buffer.extend(frame)
        if level >= umbral:
            self._speech_frames += 1
            self._silent_run = 0
        else:
            self._silent_run += 1

        if self._silent_run >= self._silence_frames or len(self._buffer) >= self._max_bytes:
            return self._finish()
        return None

    def reset(self) -> None:
        self._buffer = bytearray()
        self._preroll.clear()
        self._speech_frames = 0
        self._silent_run = 0
        self._recording = False

    def set_energy(self, energy: float) -> None:
        """Cambia el umbral en caliente (con música sonando se sube)."""
        self._energy = max(0.0005, float(energy))

    def _finish(self) -> Optional[bytes]:
        speech_frames = self._speech_frames
        # recorta el silencio final, dejando 60 ms de cola
        trim_frames = max(0, self._silent_run - 3)
        usable = len(self._buffer) - trim_frames * FRAME_BYTES
        audio = bytes(self._buffer[: max(0, usable)])
        self.reset()

        if speech_frames < self._min_frames or len(audio) < FRAME_BYTES:
            return None
        return audio
