@echo off
chcp 65001 >nul
REM Откат прогона нормализатора к состоянию из git: восстанавливает отслеживаемые
REM файлы и удаляет неотслеживаемые объекты. Выполняется без запроса.
REM
REM Безопасность (см. также раздел в README):
REM  - работает ТОЛЬКО внутри каталога самого скрипта, не трогает файлы вне него;
REM  - сами reset-скрипты исключены и из восстановления, и из удаления, поэтому
REM    скрипт не перезаписывает и не удаляет себя на ходу.
setlocal
cd /d "%~dp0"

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto notgit

REM 1. Возвращаем отслеживаемые файлы к версии из git (кроме самих reset-скриптов).
git restore --staged --worktree -- . ":(exclude)reset.sh" ":(exclude)reset.command" ":(exclude)reset.bat" 2>nul
if errorlevel 1 (
    git reset -q -- . ":(exclude)reset.sh" ":(exclude)reset.command" ":(exclude)reset.bat"
    git checkout -- . ":(exclude)reset.sh" ":(exclude)reset.command" ":(exclude)reset.bat"
)

REM 2. Удаляем неотслеживаемые объекты (опустевшие нормализованные каталоги и пр.).
git clean -fd -e reset.sh -e reset.command -e reset.bat -- .

echo Готово: examples/ возвращён к состоянию из git.
goto end

:notgit
echo Это не git-репозиторий — откат через git недоступен.

:end
pause
