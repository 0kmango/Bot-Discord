"""Soporte de descifrado DAVE/E2EE para la **recepción** de voz.

Problema: ``discord-ext-voice-recv`` solo quita el cifrado de transporte.
En canales con DAVE (E2EE) el payload sigue cifrado, el decodificador Opus
recibe basura y lanza ``OpusError: corrupted stream``; eso mata el hilo del
router y el bot se queda sordo.

Solución: parchear ``PacketDecoder._process_packet`` para descifrar el frame
con ``davey`` (el mismo motor que usa discord.py para enviar) antes de que
Opus lo decodifique.

El parche es idempotente y no hace nada si DAVE no está activo o la sesión
no está lista (en ese caso el comportamiento es el de siempre).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

_installed = False
stats = {"decrypted": 0, "failed": 0, "no_user": 0, "opus_errors": 0}
_original_max_dave = None


def dave_status(voice_client: Any) -> dict[str, Any]:
    """Estado DAVE de una conexión de voz (para ``!diag``)."""
    state = getattr(voice_client, "_connection", None)
    if state is None:
        return {"supported": False}

    session = getattr(state, "dave_session", None)
    return {
        "supported": True,
        "protocol": int(getattr(state, "dave_protocol_version", 0) or 0),
        "ready": bool(getattr(session, "ready", False)) if session is not None else False,
        "can_encrypt": bool(getattr(state, "can_encrypt", False)),
        "downgraded": bool(getattr(state, "dave_downgraded", False)),
        "session": type(session).__name__ if session is not None else None,
    }


def _decrypt(decoder: Any, packet: Any) -> Optional[bytes]:
    """Descifra el frame DAVE del paquete (None si no aplica o falla)."""
    voice_client = getattr(getattr(decoder, "sink", None), "voice_client", None)
    if voice_client is None:
        return None

    state = getattr(voice_client, "_connection", None)
    session = getattr(state, "dave_session", None)
    if session is None:
        return None

    # Si el canal no negoció DAVE, el paquete ya es Opus en claro.
    if int(getattr(state, "dave_protocol_version", 0) or 0) <= 0:
        return None

    payload = getattr(packet, "decrypted_data", None)
    # Los paquetes de silencio/vacíos no llevan audio que descifrar.
    if not payload or len(payload) <= 3:
        return None

    try:
        import davey
    except Exception:  # pragma: no cover - davey viene con discord.py[voice]
        return None

    # El decodificador ya conoce al emisor; si no, se resuelve por SSRC.
    user_id = getattr(decoder, "_cached_id", None)
    if not user_id:
        try:
            user_id = voice_client._get_id_from_ssrc(packet.ssrc)
        except Exception:
            user_id = None
    if not user_id:
        stats["no_user"] += 1
        if stats["no_user"] in (1, 10, 100):
            log.warning(
                "DAVE: paquete sin usuario asignado (ssrc=%s); no puedo descifrarlo",
                getattr(packet, "ssrc", "?"),
            )
        return None

    user_id = int(user_id)

    # Durante una transición el emisor puede mandar audio sin cifrar.
    try:
        if session.can_passthrough(user_id):
            return None
    except Exception:
        pass

    try:
        plain = session.decrypt(user_id, davey.MediaType.audio, payload)
    except Exception as exc:
        # Durante una transición el emisor manda audio sin cifrar: davey lo
        # avisa con "UnencryptedWhenPassthroughDisabled". El paquete YA es Opus
        # en claro, así que se sigue con él (es normal, no es un fallo).
        if "UnencryptedWhenPassthrough" in str(exc):
            stats["plain_frames"] = stats.get("plain_frames", 0) + 1
            return None
        stats["failed"] += 1
        if stats["failed"] in (1, 10, 50, 100) or stats["failed"] % 500 == 0:
            log.warning(
                "DAVE: no pude descifrar el audio de %s (%r). Fallos: %s",
                user_id,
                exc,
                stats["failed"],
            )
        return None

    if plain:
        stats["decrypted"] += 1
        return plain
    return None


def disable() -> bool:
    """Hace que el cliente NO anuncie soporte DAVE (fallback a transporte).

    Ojo: si Discord **exige** E2EE en el canal (cierre 4017), esto no conecta;
    en ese caso el bot reactiva DAVE automáticamente al detectarlo.
    """
    global _original_max_dave
    try:
        from discord.voice_state import VoiceConnectionState
    except Exception:
        log.debug("No pude importar VoiceConnectionState para desactivar DAVE")
        return False

    if _original_max_dave is not None:
        return True

    _original_max_dave = VoiceConnectionState.__dict__.get("max_dave_protocol_version")

    def _zero(self: Any) -> int:
        return 0

    VoiceConnectionState.max_dave_protocol_version = property(_zero)
    log.warning(
        "DAVE desactivado a petición (VOICE_DAVE=off): solo cifrado de transporte"
    )
    return True


def is_disabled() -> bool:
    """¿Está DAVE desactivado por configuración?"""
    return _original_max_dave is not None


def restore() -> bool:
    """Vuelve a habilitar DAVE (necesario si el servidor exige E2EE)."""
    global _original_max_dave
    if _original_max_dave is None:
        return False

    from discord.voice_state import VoiceConnectionState

    VoiceConnectionState.max_dave_protocol_version = _original_max_dave
    _original_max_dave = None
    log.warning("DAVE reactivado: el canal exige cifrado E2EE")
    return True

def install() -> bool:
    """Instala el parche (idempotente). Devuelve si quedó activo."""
    global _installed
    if _installed:
        return True

    try:
        from discord.ext.voice_recv.opus import PacketDecoder
    except Exception:
        log.debug("voice_recv no está disponible: sin parche DAVE")
        return False

    original = PacketDecoder._process_packet

    def patched(self: Any, packet: Any) -> Any:
        plain = _decrypt(self, packet)
        if plain is not None:
            packet.decrypted_data = plain
        return original(self, packet)

    patched._mango_dave = True  # type: ignore[attr-defined]
    PacketDecoder._process_packet = patched
    _install_opus_guard()
    _installed = True
    log.info("Parche DAVE activo: la voz entrante se descifra antes de Opus")
    return True


def _install_opus_guard() -> None:
    """Evita que un paquete indescifrable mate el lector de voz.

    Si Opus recibe basura lanza ``OpusError``; el router lo considera fatal y
    detiene la escucha. Aquí devolvemos un frame de silencio en su lugar para
    que el lector siga vivo y aproveche el resto de paquetes.
    """
    try:
        from discord.ext.voice_recv.opus import Decoder
    except Exception:
        return

    if getattr(Decoder.decode, "_mango_guard", False):
        return

    original = Decoder.decode
    silence = b"\x00" * (Decoder.FRAME_SIZE * Decoder.CHANNELS * Decoder.SAMPLE_SIZE)

    def safe_decode(self: Any, data: bytes, *, fec: bool = False) -> bytes:
        try:
            return original(self, data, fec=fec)
        except Exception as exc:
            stats["opus_errors"] += 1
            if stats["opus_errors"] in (1, 10, 100):
                log.warning(
                    "Paquete de voz ilegible (%s); sigo escuchando. Total: %s",
                    exc,
                    stats["opus_errors"],
                )
            return silence

    safe_decode._mango_guard = True  # type: ignore[attr-defined]
    Decoder.decode = safe_decode
