"""Guardián de secretos: impide subir claves al repositorio.

Comprueba dos cosas:

1. Que **ningún archivo del proyecto** (ni del historial de git) contenga algo
   con pinta de clave real.
2. Que los archivos que nunca deben publicarse (`.env`, `models/`, `data/`,
   logs...) **no estén rastreados** por git.

Uso:
    python tests/check_secrets.py          # devuelve 0 si todo está limpio
    ./run.sh --security                    # Linux/macOS
    run.bat --security                     # Windows

Se puede usar como paso previo a un `git push` (o en un hook pre-push):

    python tests/check_secrets.py || exit 1
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Extensiones que se revisan (texto). El resto se ignora.
SUFIJOS = {
    ".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml",
    ".sh", ".bat", ".ps1", ".example", ".env", ".properties",
}

# Carpetas que no se escanean (dependencias, modelos, datos, VCS).
EXCLUIDAS = {".venv", "venv", "models", "data", ".git", "__pycache__", ".cache", "node_modules"}

# Patrones de credenciales REALES (con longitud suficiente para no confundirlas
# con los marcadores de ejemplo).
PATRONES = [
    ("OpenAI", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("Groq", re.compile(r"gsk_[A-Za-z0-9]{40,}")),
    ("Token Harbor", re.compile(r"thk_live_[A-Za-z0-9_-]{20,}")),
    ("Google/Gemini", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Discord bot token", re.compile(r"[MN][A-Za-z0-9_-]{23,}\.[\w-]{6}\.[\w-]{27,}")),
    ("GitHub", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("AWS", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("ElevenLabs", re.compile(r"sk_[a-f0-9]{32,}")),
    ("Clave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    # Un .env pegado dentro de otro archivo
    ("Variable de .env con valor", re.compile(
        r"(?:DISCORD_TOKEN|LLM_API_KEY|STT_API_KEY|TTS_API_KEY|SPOTIFY_CLIENT_SECRET"
        r"|GENIUS_CLIENT_SECRET|GENIUS_TOKEN)\s*=\s*['\"]?[A-Za-z0-9_\-\.]{24,}"
    )),
]

# Marcadores que sí son aceptables (documentación y plantillas).
PERMITIDOS = (
    "...", "…", "xxxx", "XXXX", "tu_", "TU_", "PEGA", "pega", "aqui", "aquí",
    "example", "ejemplo", "cambia", "CAMBIAME", "placeholder", "your_", "YOUR_",
    "sk-...", "gsk_...", "thk_live_...", "AIza...", "tu_token", "TOKEN DISCORD",
)


def _archivos() -> list[Path]:
    """Archivos de texto que se subirían a git (el `.env` local NO se escanea:
    ahí es donde deben estar las claves; solo se comprueba que git no lo rastree).
    """
    encontrados: list[Path] = []
    for ruta in RAIZ.rglob("*"):
        if not ruta.is_file():
            continue
        if ruta.name == ".env":
            continue
        if any(parte in EXCLUIDAS for parte in ruta.relative_to(RAIZ).parts):
            continue
        if ruta.suffix.lower() in SUFIJOS or ruta.name in {".env.example", ".gitignore"}:
            encontrados.append(ruta)
    return encontrados


def _es_permitido(linea: str) -> bool:
    return any(marca in linea for marca in PERMITIDOS)


def _revisar_archivos() -> list[str]:
    problemas: list[str] = []
    for ruta in _archivos():
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for numero, linea in enumerate(texto.splitlines(), start=1):
            for nombre, patron in PATRONES:
                if not patron.search(linea):
                    continue
                if _es_permitido(linea):
                    continue
                relativa = ruta.relative_to(RAIZ)
                problemas.append(f"{relativa}:{numero}  ->  posible clave ({nombre})")
    return problemas


def _git(*args: str) -> str:
    try:
        salida = subprocess.run(
            ["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return salida.stdout if salida.returncode == 0 else ""


def _revisar_git() -> list[str]:
    """Que los archivos prohibidos no estén rastreados ni en el historial."""
    problemas: list[str] = []
    rastreados = _git("ls-files").splitlines()
    if not rastreados:
        return problemas  # no es un repositorio git (o no hay archivos)

    for archivo in rastreados:
        if archivo == ".env" or archivo.endswith(".env"):
            problemas.append(f"git rastrea {archivo!r}: los secretos no deben subirse")
        elif archivo.startswith(("models/", "data/")):
            problemas.append(f"git rastrea {archivo!r}: descárgalo aparte, no lo publiques")
        elif archivo.endswith(".log"):
            problemas.append(f"git rastrea {archivo!r}: los logs pueden filtrar datos")

    # Historial: alguna vez se subió una clave?
    historial = _git("log", "--all", "-p")
    for nombre, patron in PATRONES:
        for coincidencia in patron.finditer(historial):
            if not _es_permitido(coincidencia.group(0)):
                problemas.append(f"historial de git: posible clave ({nombre})")
                break

    return problemas


def main() -> int:
    print("🔐 Revisando que no haya claves en el proyecto...\n")

    problemas = _revisar_archivos()
    problemas += _revisar_git()

    if not problemas:
        print("✅ Limpio: no hay claves en el código ni archivos sensibles en git.")
        print("\nRecuerda: las claves viven SOLO en .env (ignorado por git).")
        return 0

    print(f"❌ {len(problemas)} problema(s) encontrado(s):\n")
    for problema in problemas:
        print(f"   · {problema}")
    print(
        "\nArréglalo así:\n"
        "  1. Mueve la clave a `.env` (que está en .gitignore).\n"
        "  2. Si ya se subió: cámbiala/revócala en el proveedor y reescribe el historial.\n"
        "  3. Vuelve a ejecutar esta comprobación."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
