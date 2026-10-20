#!/usr/bin/env bash
# Startet das Backend (Linux/macOS – z. B. für Entwicklung). Unter Windows: scripts/start.ps1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$ROOT/.venv" ] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
cd "$ROOT/backend" && exec "$ROOT/.venv/bin/python" -m jarvis --print-admin-token "$@"
