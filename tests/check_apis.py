"""Comprueba que las APIs de Mango AI responden correctamente.

Uso:
    .venv/bin/python tests/check_apis.py          # chequeo rápido
    .venv/bin/python tests/check_apis.py --full   # prueba real de Whisper local

No muestra ni registra nunca las claves.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# load_config() exige token; aquí no se conecta a Discord.
os.environ.setdefault("DISCORD_TOKEN", "check-apis")

from mango.config import ConfigError, load_config  # noqa: E402
from mango.logging_setup import setup_logging  # noqa: E402

setup_logging("WARNING")

DEEP = "--full" in sys.argv
ok_count = 0
fail_count = 0


def report(success: bool, name: str, detail: str = "") -> None:
    global ok_count, fail_count
    if success:
        ok_count += 1
        print(f"[OK]    {name}{' · ' + detail if detail else ''}")
    else:
        fail_count += 1
        print(f"[FALLO] {name}{' · ' + detail if detail else ''}")


def info(name: str, detail: str = "") -> None:
    print(f"[info]  {name}{' · ' + detail if detail else ''}")


# ===============================
# Comprobaciones
# ===============================
async def check_llm(config) -> None:
    if not config.ai_enabled:
        report(False, "LLM", "falta LLM_API_KEY o LLM_MODEL en el .env")
        return

    from mango.services.llm import LLMService

    service = LLMService(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        temperature=0.0,
    )
    started = time.perf_counter()
    try:
        reply = await service.reply(
            history=[{"role": "user", "content": "Responde solo con la palabra: ok"}],
            max_chars=40,
        )
    except Exception as exc:  # noqa: BLE001 - queremos ver el motivo real
        report(False, "LLM", f"{type(exc).__name__}: {str(exc)[:180]}")
        return

    elapsed = time.perf_counter() - started
    report(True, "LLM", f"{config.llm_model} respondió en {elapsed:.2f}s → {reply[:40]!r}")


async def check_llm_fallback(config) -> None:
    if not config.llm_fallback_enabled:
        info("LLM respaldo", "no configurado (opcional)")
        return

    from mango.services.llm import LLMService

    service = LLMService(
        base_url=config.llm_fallback_base_url,
        api_key=config.llm_fallback_api_key,
        model=config.llm_fallback_model,
        temperature=0.0,
    )
    started = time.perf_counter()
    try:
        reply = await service.reply(
            history=[{"role": "user", "content": "Responde solo con la palabra: ok"}],
            max_chars=40,
        )
    except Exception as exc:  # noqa: BLE001
        report(
            False,
            f"LLM respaldo ({config.llm_fallback_model})",
            f"{type(exc).__name__}: {str(exc)[:140]}",
        )
        return

    report(
        True,
        f"LLM respaldo ({config.llm_fallback_model})",
        f"respondió en {time.perf_counter() - started:.2f}s → {reply[:30]!r}",
    )


async def check_stt(config) -> None:
    from mango.services.stt import build_stt

    service = build_stt(config)
    if service is None:
        report(False, "STT", "no se pudo construir (revisa STT_*)")
        return

    label = getattr(service, "label", config.stt_provider)
    if config.stt_provider == "local" and not DEEP:
        report(True, "STT", f"{label} listo (usa --full para transcribir de verdad)")
        return

    # Un segundo de silencio: valida claves y modelo sin necesitar micrófono.
    silence = b"\x00" * (48000 * 2 * 2)
    started = time.perf_counter()
    try:
        text = await service.transcribe(silence)
    except Exception as exc:  # noqa: BLE001
        report(False, "STT", f"{type(exc).__name__}: {str(exc)[:180]}")
        return

    elapsed = time.perf_counter() - started
    report(True, "STT", f"{label} transcribió en {elapsed:.2f}s → {text!r}")


async def check_tts(config) -> None:
    from mango.services.tts import build_tts

    service = build_tts(config)
    if service is None:
        report(False, "TTS", "no se pudo construir (revisa TTS_*)")
        return

    started = time.perf_counter()
    try:
        pcm = await service.synthesize("Hola, soy Mango. Buen gusto verte por aquí.")
    except Exception as exc:  # noqa: BLE001
        report(False, "TTS", f"{type(exc).__name__}: {str(exc)[:180]}")
        return

    elapsed = time.perf_counter() - started
    seconds = len(pcm) / (48000 * 2 * 2)
    if seconds < 0.3:
        report(False, "TTS", f"audio demasiado corto ({seconds:.2f}s)")
        return
    label = getattr(service, "label", config.tts_provider)
    report(True, "TTS", f"{label}: {seconds:.2f}s de audio en {elapsed:.2f}s")


def check_optional(config) -> None:
    info("AI_CHANNEL_ID", str(config.ai_channel_id or "vacío (opcional)"))
    info("AI_VOICE_CHANNEL_ID", str(config.ai_voice_channel_id or "vacío (opcional)"))


async def check_spotify(config) -> None:
    if not config.spotify_enabled:
        info("Spotify", "sin credenciales (opcional)")
        return

    import base64

    import aiohttp

    credentials = base64.b64encode(
        f"{config.spotify_client_id}:{config.spotify_client_secret}".encode()
    ).decode()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {credentials}"},
                timeout=20,
            ) as response:
                token = (await response.json(content_type=None)).get("access_token")

            if not token:
                report(False, "Spotify", "no obtuve access_token")
                return

            async with session.get(
                "https://api.spotify.com/v1/search",
                params={"q": "daft punk", "type": "track", "limit": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            ) as response:
                status = response.status
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        report(False, "Spotify", f"{type(exc).__name__}: {str(exc)[:120]}")
        return

    items = payload.get("tracks", {}).get("items", []) if status == 200 else []
    if not items:
        report(False, "Spotify", f"la búsqueda falló ({status})")
        return
    report(True, "Spotify", f"credenciales OK · prueba: «{items[0]['name']}»")


async def check_genius(config) -> None:
    if not config.lyrics_enabled:
        info("Genius", "sin credenciales (opcional)")
        return

    from mango.services.lyrics import LyricsError, LyricsService

    service = LyricsService(
        config.genius_token,
        client_id=config.genius_client_id,
        client_secret=config.genius_client_secret,
    )
    try:
        result = await asyncio.wait_for(
            service.fetch("Daft Punk Instant Crush"), timeout=60
        )
    except LyricsError as exc:
        report(False, "Genius", str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        report(False, "Genius", f"{type(exc).__name__}: {str(exc)[:120]}")
        return

    if result is None:
        report(True, service.label, "autenticado (sin resultados de prueba)")
        return

    title, text = result
    report(True, service.label, f"«{title}» ({len(text)} caracteres)")


def audit_env() -> None:
    """Lista qué variables del .env están puestas y cuáles faltan (sin mostrar valores)."""
    from dotenv import dotenv_values

    raiz = ROOT / ".env"
    if not raiz.is_file():
        info("`.env`", "no existe: copia .env.example y rellénalo")
        return

    valores = dotenv_values(raiz)
    criticas = ("DISCORD_TOKEN", "OWNER_IDS", "LLM_API_KEY", "LLM_MODEL")
    opcionales = (
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "GENIUS_CLIENT_ID",
        "GENIUS_CLIENT_SECRET",
        "AI_CHANNEL_ID",
        "AI_VOICE_CHANNEL_ID",
    )

    print("\n── Estado del .env ──")
    for clave in criticas:
        valor = valores.get(clave) or ""
        estado = f"OK (len={len(valor)})" if valor else "VACÍA ← rellénala"
        print(f"  [{'OK' if valor else 'FALTA':5}] {clave:24} {estado}")
    for clave in opcionales:
        valor = valores.get(clave) or ""
        if valor:
            print(f"  [OK   ] {clave:24} OK (len={len(valor)})")

    vacias = [c for c in (*criticas, *opcionales) if not (valores.get(c) or "")]
    if len(vacias) == len(criticas) + len(opcionales):
        print("  ⚠️  El .env está vacío: parece copiado de .env.example sin rellenar")


# ===============================
# Main
# ===============================
async def main() -> int:
    print("── Verificación de APIs de Mango AI ──")
    audit_env()
    print()
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[FALLO] Configuración: {exc}")
        return 1

    if not (ROOT / ".env").is_file():
        print("⚠️  No hay archivo .env: se usan solo las variables del sistema.\n")

    await check_llm(config)
    await check_llm_fallback(config)
    await check_stt(config)
    await check_tts(config)
    await check_spotify(config)
    await check_genius(config)
    check_optional(config)

    print("\n── Resumen ──")
    print(f"{ok_count} correctas · {fail_count} con problemas")
    if fail_count:
        print("\nRevisa el .env. Endpoints válidos para LLM:")
        print("  OpenAI → https://api.openai.com/v1 · gpt-4o-mini")
        print("  Groq   → https://api.groq.com/openai/v1 · llama-3.3-70b-versatile")
        print("  Ollama → http://localhost:11434/v1 · qwen2.5:7b (LLM_API_KEY=ollama)")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
