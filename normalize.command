#!/usr/bin/env bash
# Кликабельная обёртка для macOS (Finder): при первом запуске готовит .venv и зависимости, затем запускает normalize_fs.py.
set -euo pipefail

fold="$(cd -- "$(dirname -- "$0")" && pwd)"
venv="$fold/.venv"
pyex="$venv/bin/python"

if [ ! -x "$pyex" ] || ! "$pyex" -c "import unidecode" >/dev/null 2>&1; then
    echo "Подготовка окружения (.venv)..." >&2
    python3 -m venv "$venv"
    "$pyex" -m pip install -r "$fold/requirements.txt"
fi

exec "$pyex" "$fold/normalize_fs.py" "$@"
