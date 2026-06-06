@echo off
chcp 65001 >nul
REM Откат прогона нормализатора к состоянию из git: восстанавливает отслеживаемые
REM файлы и удаляет неотслеживаемые объекты. Выполняется без запроса.
REM
REM Безопасность (см. также раздел в README):
REM  - работает ТОЛЬКО внутри каталога самого скрипта, не трогает файлы вне него.
setlocal
cd /d "%~dp0"

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto notgit

REM 1. Возвращаем отслеживаемые файлы к версии из git (только в этом каталоге).
git restore --staged --worktree -- . 2>nul
if errorlevel 1 (
    git reset -q -- .
    git checkout -- .
)

REM 2. Удаляем неотслеживаемые объекты (опустевшие нормализованные каталоги и пр.).
git clean -fd -- .

echo Готово: examples/ возвращён к состоянию из git.
goto end

:notgit
echo Это не git-репозиторий — откат через git недоступен.

:end
pause
