#!/usr/bin/env bash
# Кликабельная обёртка для macOS (Finder): откат прогона нормализатора к
# состоянию из git.
#
# Безопасность (см. также раздел в README):
#  - работает ТОЛЬКО внутри каталога самого скрипта (.), никогда не трогает
#    файлы вне него;
#  - отслеживаемые файлы лишь возвращаются к версии из git (восстановимо); сами
#    reset-скрипты при этом не трогаются;
#  - неотслеживаемые объекты удаляются ТОЛЬКО после явного подтверждения.
#
# Логика в функции main (вызов последней строкой): интерпретатор читает скрипт
# целиком до выполнения и не «дочитает» изменённую версию с диска.
set -euo pipefail

main() {
    local here ans leftovers
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

    # 1. Возвращаем ОТСЛЕЖИВАЕМЫЕ файлы к версии из git (только в этом каталоге).
    if ! git restore --staged --worktree -- . "${keep[@]}" 2>/dev/null; then
        git reset -q -- . "${keep[@]}"
        git checkout -- . "${keep[@]}"
    fi

    # 2. Неотслеживаемые объекты — только после подтверждения.
    leftovers="$(git clean -nd "${excl[@]}" -- . | sed 's/^Would remove //')"
    if [ -z "$leftovers" ]; then
        echo "Готово: дерево уже соответствует git, удалять нечего." >&2
        pause_exit 0
    fi

    echo "Будут удалены неотслеживаемые объекты (их НЕТ в git, восстановить нельзя):" >&2
    printf '%s\n' "$leftovers" | sed 's/^/  /' >&2
    printf "Удалить перечисленное? [y/N]: " >&2
    read -r ans || ans=""
    case "$ans" in
        [yYдД]*)
            git clean -fd "${excl[@]}" -- .
            echo "Готово: дерево возвращено к состоянию из git." >&2
            ;;
        *)
            echo "Отменено: неотслеживаемые объекты сохранены (отслеживаемые уже восстановлены)." >&2
            ;;
    esac

    pause_exit 0
}

main "$@"
