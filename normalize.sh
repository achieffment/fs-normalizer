#!/usr/bin/env bash
# Обёртка для Linux/macOS: при первом запуске готовит .venv и зависимости, затем запускает normalize_fs.py.
set -euo pipefail

fold="$(cd -- "$(dirname -- "$0")" && pwd)"
venv="$fold/.venv"
pyex="$venv/bin/python"

if [ ! -x "$pyex" ] || ! "$pyex" -c "import unidecode" >/dev/null 2>&1; then
    echo "Подготовка окружения (.venv)..." >&2
    rm -rf "$venv"
    if ! python3 -m venv "$venv"; then
        echo "Не удалось создать .venv (возможно, временный сбой сети). Повторите запуск." >&2
        rm -rf "$venv"
        exit 1
    fi
    if ! "$pyex" -m pip install -r "$fold/requirements.txt"; then
        echo "Не удалось установить зависимости (возможно, временный сбой сети). Повторите запуск." >&2
        rm -rf "$venv"
        exit 1
    fi
fi

exec "$pyex" "$fold/normalize_fs.py" "$@"
