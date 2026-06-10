@echo off
chcp 65001 >nul
REM Обёртка для Windows: при первом запуске готовит .venv и зависимости, затем запускает normalize_fs.py.
setlocal
set "fold=%~dp0"
set "pyex=%fold%.venv\Scripts\python.exe"

if not exist "%pyex%" goto setup
"%pyex%" -c "import unidecode" 1>nul 2>nul
if errorlevel 1 goto setup
goto run

:setup
echo Подготовка окружения (.venv)...
if exist "%fold%.venv" rmdir /s /q "%fold%.venv"
python -m venv "%fold%.venv"
if errorlevel 1 goto venvfail
"%pyex%" -m pip install -r "%fold%requirements.txt"
if errorlevel 1 goto pipfail
goto run

:venvfail
echo Не удалось создать .venv (возможно, временный сбой сети). Повторите запуск.
if exist "%fold%.venv" rmdir /s /q "%fold%.venv"
goto end

:pipfail
echo Не удалось установить зависимости (возможно, временный сбой сети). Повторите запуск.
if exist "%fold%.venv" rmdir /s /q "%fold%.venv"
goto end

:run
"%pyex%" "%fold%normalize_fs.py" %*

:end
pause
