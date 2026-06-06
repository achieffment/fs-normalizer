#!/usr/bin/env bash
# Кликабельная обёртка для macOS (Finder): откат прогона нормализатора к
# состоянию из git — восстанавливает отслеживаемые файлы и удаляет
# неотслеживаемые объекты. Выполняется без запроса.
#
# Безопасность (см. также раздел в README):
#  - работает ТОЛЬКО внутри каталога самого скрипта (.), никогда не трогает
#    файлы вне него;
#  - сами reset-скрипты исключены и из восстановления, и из удаления, поэтому
#    скрипт не может перезаписать или удалить себя на ходу.
#
# Логика в функции main (вызов последней строкой): интерпретатор читает скрипт
# целиком до выполнения и не «дочитает» изменённую версию с диска.
set -euo pipefail

main() {
    local here
    here="$(cd -- "$(dirname -- "$0")" && pwd)"
    cd "$here"

    pause_exit() {
        echo
        read -n 1 -s -r -p "Нажмите любую клавишу для выхода..." || true
        echo
        exit "$1"
    }

    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "Это не git-репозиторий — откат через git недоступен." >&2
        pause_exit 1
    fi

    local keep=(':(exclude)reset.sh' ':(exclude)reset.command' ':(exclude)reset.bat')
    local excl=(-e reset.sh -e reset.command -e reset.bat)

    # 1. Возвращаем отслеживаемые файлы к версии из git (только в этом каталоге).
    if ! git restore --staged --worktree -- . "${keep[@]}" 2>/dev/null; then
        git reset -q -- . "${keep[@]}"
        git checkout -- . "${keep[@]}"
    fi

    # 2. Удаляем неотслеживаемые объекты (опустевшие нормализованные каталоги и пр.).
    git clean -fd "${excl[@]}" -- .

    echo "Готово: examples/ возвращён к состоянию из git." >&2
    pause_exit 0
}

main "$@"
