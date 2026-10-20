#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$ROOT/.venv" ] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/backend/requirements-dev.txt"
cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m pytest -o addopts="" -q "$@"
if command -v flutter >/dev/null; then (cd "$ROOT/apps/jarvis_app" && flutter analyze && flutter test); fi
