#!/usr/bin/env python3
"""Punto de entrada de Mango Bot.

Uso (Linux/macOS):
    cp .env.example .env      # rellena DISCORD_TOKEN y OWNER_IDS
    ./run.sh                  # o: python bot.py

Uso (Windows):
    copy .env.example .env
    run.bat                   # o: py bot.py

Si lanzas este archivo con el Python del sistema (sin las dependencias),
el script se vuelve a ejecutar automáticamente con el intérprete del `.venv`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ES_WINDOWS = os.name == "nt"
VENV_CANDIDATES = (
    BASE_DIR / ".venv" / "Scripts" / "python.exe",   # Windows
    BASE_DIR / ".venv" / "bin" / "python",           # Linux y macOS
)


def _ayuda_venv() -> str:
    """Instrucciones de creación del entorno, según el sistema."""
    if ES_WINDOWS:
        return (
            "   Créalo así (PowerShell o CMD):\n"
            "     py -3.12 -m venv .venv\n"
            "     .venv\\Scripts\\pip install -r requirements.txt\n"
            "   O usa directamente:  run.bat"
        )
    return (
        "   Créalo así:\n"
        "     python3 -m venv .venv\n"
        "     .venv/bin/pip install -r requirements.txt\n"
        "   O usa directamente:  ./run.sh"
    )


def _ensure_venv() -> int | None:
    """Garantiza que estamos ejecutando con las dependencias instaladas.

    Devuelve un código de salida si hay que terminar (solo en Windows, donde
    el proceso hijo devuelve su resultado) o ``None`` para continuar.
    """
    try:
        import discord  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return None

    # `sys.prefix != sys.base_prefix` indica que ya estamos dentro de un venv.
    # (Comparar rutas no sirve: .venv/bin/python suele ser un symlink al sistema.)
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        print(
            "❌ Estás dentro de un entorno virtual, pero falta `discord.py`.\n"
            "   Instala las dependencias:  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    # Si ya nos relanzamos una vez y `discord` sigue sin aparecer, el entorno
    # está roto: mejor decirlo que entrar en un bucle de relanzamientos.
    reintento = os.environ.get("MANGO_RELAUNCHED") == "1"

    for candidate in VENV_CANDIDATES:
        if not candidate.is_file():
            continue
        if reintento:
            break
        print(f"🔁 Re-lanzando con el entorno virtual: {candidate}", file=sys.stderr)
        argumentos = [str(candidate), str(BASE_DIR / "bot.py"), *sys.argv[1:]]
        os.environ["MANGO_RELAUNCHED"] = "1"
        if ES_WINDOWS:
            # En Windows `execv` no sustituye el proceso de forma fiable:
            # se lanza como hijo y se devuelve su código de salida.
            import subprocess

            return subprocess.call(argumentos, env=os.environ)
        os.execv(str(candidate), argumentos)

    if reintento:
        print(
            "❌ El entorno virtual existe, pero no tiene las dependencias.\n"
            "   Reinstálalas dentro de él:\n"
            + _ayuda_venv(),
            file=sys.stderr,
        )
        return 1

    print(
        "❌ No encuentro el entorno virtual con las dependencias.\n" + _ayuda_venv(),
        file=sys.stderr,
    )
    return 1


if _ensure_venv():
    raise SystemExit(1)

import discord  # noqa: E402

from mango.config import ConfigError, load_config  # noqa: E402
from mango.core import MangoBot  # noqa: E402
from mango.logging_setup import setup_logging  # noqa: E402


def _ignorar_sighup() -> None:
    """Cerrar la terminal ya no apaga el bot.

    Por defecto, cerrar la sesión manda SIGHUP y el proceso muere: era la
    causa de que el bot «se apagara sin razón» tras unos minutos.
    """
    if os.name != "posix":
        return
    import signal

    signal.signal(signal.SIGHUP, signal.SIG_IGN)


def main() -> int:
    _ignorar_sighup()
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"❌ Configuración inválida: {exc}", file=sys.stderr)
        return 1

    setup_logging(config.log_level)
    bot = MangoBot(config)

    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.LoginFailure:
        print(
            "❌ Discord rechazó el token. Revisa DISCORD_TOKEN en tu archivo .env.",
            file=sys.stderr,
        )
        return 1
    except discord.PrivilegedIntentsRequired:
        print(
            "❌ Faltan intents privilegiados.\n"
            "   Activa 'MESSAGE CONTENT INTENT' en "
            "https://discord.com/developers/applications → tu app → Bot.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\n👋 Mango apagado a mano. Hasta la próxima.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
