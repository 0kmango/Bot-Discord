#!/usr/bin/env bash
# Lanza Mango Bot con comprobaciones previas.
#
#   ./run.sh              arranca el bot (Ctrl+C para parar)
#   ./run.sh --background lo deja en segundo plano (sobrevive al cerrar la terminal)
#   ./run.sh --stop       detiene el bot
#   ./run.sh --voices     descarga las voces locales gratis (Piper + Kokoro)
#   ./run.sh --check      comprueba configuración y APIs
#   ./run.sh --security   comprueba que no haya claves en el proyecto
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"

case "${1:-}" in
  --help|-h)
    sed -n '2,8p' "$0"
    exit 0
    ;;
  --stop)
    if pkill -f "bot.py"; then
      echo "👋 Mango Bot detenido."
    else
      echo "No había ningún bot corriendo."
    fi
    exit 0
    ;;
  --voices)
    exec "$PY" -m mango.services.voices
    ;;
  --check|-c)
    exec "$PY" tests/check_apis.py
    ;;
  --security|-s)
    exec "$PY" tests/check_secrets.py
    ;;
  --background|-b)
    nohup "$PY" bot.py >> mango.log 2>&1 &
    echo "🥭 Mango Bot en segundo plano (PID $!)."
    echo "   Logs:  tail -f mango.log"
    echo "   Parar: ./run.sh --stop"
    exit 0
    ;;
esac

if [[ ! -x "$PY" ]]; then
  echo "❌ No encuentro el entorno virtual .venv"
  echo "   Créalo así:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "❌ Falta el archivo .env (cópialo de .env.example y rellénalo)"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️  FFmpeg no está en el PATH: no habrá música."
fi

echo "🥭 Arrancando Mango Bot… (Ctrl+C para parar)"
exec "$PY" bot.py