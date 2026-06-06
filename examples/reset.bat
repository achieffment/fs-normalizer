@echo off
chcp 65001 >nul
REM Откат прогона нормализатора к состоянию из git.
REM
REM Безопасность (см. также раздел в README):
REM  - работает ТОЛЬКО внутри каталога самого скрипта, не трогает файлы вне него;
REM  - отслеживаемые файлы лишь возвращаются к версии из git (восстановимо);
REM    сами reset-скрипты при этом не трогаются (исключены из восстановления),
REM    поэтому скрипт не перезаписывает себя на ходу;
REM  - неотслеживаемые объекты удаляются ТОЛЬКО после явного подтверждения.
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

REM 2. Неотслеживаемые объекты — только после подтверждения.
set "hasleft="
for /f "delims=" %%L in ('git clean -nd -e reset.sh -e reset.command -e reset.bat -- .') do set "hasleft=1"
if not defined hasleft (
    echo Готово: дерево уже соответствует git, удалять нечего.
    goto end
)

echo Будут удалены неотслеживаемые объекты ^(их НЕТ в git, восстановить нельзя^):
git clean -nd -e reset.sh -e reset.command -e reset.bat -- .
set "ans="
set /p "ans=Удалить перечисленное? [y/N]: "
if /i "%ans%"=="y" (
    git clean -fd -e reset.sh -e reset.command -e reset.bat -- .
    echo Готово: дерево возвращено к состоянию из git.
) else (
    echo Отменено: неотслеживаемые объекты сохранены ^(отслеживаемые уже восстановлены^).
)
goto end

:notgit
echo Это не git-репозиторий — откат через git недоступен.

:end
pause
