#!/usr/bin/env bash
# Кликабельная обёртка для macOS (Finder): при первом запуске готовит .venv и зависимости, затем запускает normalize_fs.py.
set -euo pipefail

fold="$(cd -- "$(dirname -- "$0")" && pwd)"
venv="$fold/.venv"
pyex="$venv/bin/python"

pause_exit() {
    echo
    read -n 1 -s -r -p "Нажмите любую клавишу для выхода..." || true
    echo
    exit "$1"
}

# Списки путей exclude/include: если файла нет, создаём пустой (проверки выключены).
[ -e "$fold/exclude.txt" ] || : > "$fold/exclude.txt"
[ -e "$fold/include.txt" ] || : > "$fold/include.txt"

if [ ! -x "$pyex" ] || ! "$pyex" -c "import unidecode" >/dev/null 2>&1; then
    echo "Подготовка окружения (.venv)..." >&2
    rm -rf "$venv"
    if ! python3 -m venv "$venv"; then
        echo "Не удалось создать .venv (возможно, временный сбой сети). Повторите запуск." >&2
        rm -rf "$venv"
        pause_exit 1
    fi
    if ! "$pyex" -m pip install -r "$fold/requirements.txt"; then
        echo "Не удалось установить зависимости (возможно, временный сбой сети). Повторите запуск." >&2
        rm -rf "$venv"
        pause_exit 1
    fi
fi

stat=0
"$pyex" "$fold/normalize_fs.py" "$@" || stat=$?
pause_exit "$stat"
