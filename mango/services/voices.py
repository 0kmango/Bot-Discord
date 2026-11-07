"""Voces locales gratis (Piper y Kokoro) para el TTS del bot.

Uso:
    ./run.sh --voices                 # descarga Piper (es-ES) + Kokoro
    ./run.sh --voices piper-es-mx     # solo una voz concreta
    python -m mango.services.voices   # lo mismo, directamente

Los modelos se guardan en ``models/`` (ignorada por git).
"""

from __future__ import annotations

import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(message)s")

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"

_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
_KOKORO = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)

# nombre corto -> ficheros a descargar
MODELOS: dict[str, tuple[str, ...]] = {
    "piper-es-es": (
        f"{_PIPER}/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        f"{_PIPER}/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json",
    ),
    "piper-es-es-sharvard": (
        f"{_PIPER}/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx",
        f"{_PIPER}/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json",
    ),
    # México, femenina, calidad «high»: la voz por defecto (rápida y cálida)
    "piper-es-mx-claude": (
        f"{_PIPER}/es/es_MX/claude/high/es_MX-claude-high.onnx",
        f"{_PIPER}/es/es_MX/claude/high/es_MX-claude-high.onnx.json",
    ),
    # México, masculina
    "piper-es-mx": (
        f"{_PIPER}/es/es_MX/ald/medium/es_MX-ald-medium.onnx",
        f"{_PIPER}/es/es_MX/ald/medium/es_MX-ald-medium.onnx.json",
    ),
    # Argentina, femenina (calidad «high» pero muy lenta en CPU)
    "piper-es-ar": (
        f"{_PIPER}/es/es_AR/daniela/high/es_AR-daniela-high.onnx",
        f"{_PIPER}/es/es_AR/daniela/high/es_AR-daniela-high.onnx.json",
    ),
    "kokoro": (
        f"{_KOKORO}/kokoro-v1.0.onnx",
        f"{_KOKORO}/voices-v1.0.bin",
    ),
}

POR_DEFECTO = ("piper-es-mx-claude",)


class DescargaError(RuntimeError):
    """No se pudo descargar un modelo de voz."""


def _descargar_archivo(url: str, destino: Path) -> None:
    temporal = destino.with_name(destino.name + ".parcial")
    try:
        with urllib.request.urlopen(url, timeout=120) as respuesta:
            total = int(respuesta.headers.get("Content-Length") or 0)
            leidos = 0
            with temporal.open("wb") as salida:
                while True:
                    bloque = respuesta.read(1 << 16)
                    if not bloque:
                        break
                    salida.write(bloque)
                    leidos += len(bloque)
                    if total:
                        print(
                            f"\r   {leidos / 1048576:5.1f} / {total / 1048576:.1f} MB",
                            end="",
                            flush=True,
                        )
        print()
    except (urllib.error.URLError, OSError) as exc:
        temporal.unlink(missing_ok=True)
        raise DescargaError(f"No pude descargar {url}: {exc}") from exc
    temporal.replace(destino)


def descargar(nombre: str, destino: Path = MODELS_DIR) -> list[Path]:
    """Descarga los ficheros de una voz (omite los que ya están)."""
    if nombre not in MODELOS:
        raise DescargaError(
            f"Voz desconocida: {nombre}. Disponibles: {', '.join(MODELOS)}"
        )

    destino.mkdir(parents=True, exist_ok=True)
    rutas: list[Path] = []
    for url in MODELOS[nombre]:
        archivo = destino / url.rsplit("/", 1)[-1]
        if archivo.is_file() and archivo.stat().st_size > 1024:
            print(f"✓ ya está: {archivo.name}")
        else:
            print(f"⬇️  {archivo.name}")
            _descargar_archivo(url, archivo)
        rutas.append(archivo)
    return rutas


def main(argv: list[str] | None = None) -> int:
    nombres = list(argv or sys.argv[1:]) or list(POR_DEFECTO)
    for nombre in nombres:
        print(f"── {nombre} ──")
        try:
            descargar(nombre)
        except DescargaError as exc:
            print(f"❌ {exc}")
            return 1
    print(
        "\nListo 🥭. En tu .env:\n"
        "  TTS_PROVIDER=piper      # la más rápida (gratis, offline)\n"
        "  TTS_PROVIDER=kokoro     # algo más natural pero más lenta en CPU\n"
        "  TTS_PROVIDER=local      # elige sola la mejor disponible"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
