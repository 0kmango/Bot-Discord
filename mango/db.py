"""Memoria de conversación en SQLite.

Se guarda **solo texto** (nunca audio). Cada conversación se aísla por
``scope``: un canal de texto o un usuario dentro de un canal de voz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "mango.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_scope ON ai_messages(scope, id);
"""


class MemoryStore:
    """Historial de conversación persistente y seguro entre hilos."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()
        self._restringir_permisos()

    def _restringir_permisos(self) -> None:
        """La conversación es privada: solo el usuario del bot debe poder leerla.

        Sin esto, el `.db` (y su WAL) se crean con 0644 y cualquier otra cuenta
        de la máquina puede leer todo lo que se ha hablado con Mango.
        En Windows `chmod` solo alterna el bit de escritura: no rompe nada.
        """
        with contextlib.suppress(OSError):
            os.chmod(self.path.parent, 0o700)
        for archivo in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            with contextlib.suppress(OSError):
                if archivo.exists():
                    os.chmod(archivo, 0o600)

    # ---------------------------------------------------------
    # API asíncrona
    # ---------------------------------------------------------
    async def add(self, scope: str, role: str, content: str) -> None:
        if not content:
            return
        await asyncio.to_thread(self._add_sync, scope, role, content)

    async def history(self, scope: str, limit: int = 20) -> list[dict[str, str]]:
        return await asyncio.to_thread(self._history_sync, scope, limit)

    async def clear(self, scope: str) -> int:
        return await asyncio.to_thread(self._clear_sync, scope)

    async def clear_all(self) -> int:
        """Borra **todo** el historial de conversación (al arrancar, por ejemplo)."""
        return await asyncio.to_thread(self._clear_all_sync)

    async def purge_older_than(self, days: int) -> int:
        cutoff = time.time() - days * 86400
        return await asyncio.to_thread(self._purge_sync, cutoff)

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except Exception:
                logger.debug("No pude cerrar la base de datos", exc_info=True)

    # ---------------------------------------------------------
    # Implementación síncrona
    # ---------------------------------------------------------
    def _add_sync(self, scope: str, role: str, content: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO ai_messages (scope, role, content, created_at) VALUES (?, ?, ?, ?)",
                (scope, role, content[:4000], time.time()),
            )
            self._connection.commit()

    def _history_sync(self, scope: str, limit: int) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT role, content FROM ai_messages WHERE scope = ? ORDER BY id DESC LIMIT ?",
                (scope, max(1, limit)),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def _clear_sync(self, scope: str) -> int:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM ai_messages WHERE scope = ?", (scope,)
            )
            self._connection.commit()
        return cursor.rowcount or 0

    def _clear_all_sync(self) -> int:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM ai_messages")
            self._connection.commit()
            with contextlib.suppress(Exception):
                self._connection.execute("VACUUM")
        return cursor.rowcount or 0

    def _purge_sync(self, cutoff: float) -> int:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM ai_messages WHERE created_at < ?", (cutoff,)
            )
            self._connection.commit()
        return cursor.rowcount or 0
