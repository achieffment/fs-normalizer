@echo off
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
python -m venv "%fold%.venv"
"%pyex%" -m pip install -r "%fold%requirements.txt"

:run
"%pyex%" "%fold%normalize_fs.py" %*
