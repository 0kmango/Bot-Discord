"""Configuración centralizada de logging."""

from __future__ import annotations

import contextlib
import logging
import os
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configura logging legible para consola y archivo ``mango.log``."""

    resolved = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(resolved)
    root.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(resolved)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        file_handler = logging.FileHandler("mango.log", encoding="utf-8")
    except OSError:  # por ejemplo, directorio de solo lectura
        file_handler = None
    if file_handler is not None:
        file_handler.setLevel(max(resolved, logging.INFO))
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        # El log puede contener lo que se dice por voz: solo el dueño debe leerlo.
        with contextlib.suppress(OSError):
            os.chmod("mango.log", 0o600)

    # Librerías ruidosas: solo lo importante
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("yt_dlp").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("spotipy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("edge_tts").setLevel(logging.WARNING)

    logging.getLogger(__name__).debug("Logging configurado en nivel %s", level.upper())
