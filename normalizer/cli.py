"""CLI: разбор аргументов и сценарий запуска."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .filesystem import FilesystemNormalizer
from .name import build_normalizer

# PowerShell-скрипт с C#-блоком IFileOpenDialog (нативный выбор папки Windows).
_PICK_FOLDER_PS1 = Path(__file__).with_name("pick_folder.ps1")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Нормализатор имён файлов и папок (рекурсивно). Каталог выбирается интерактивно при запуске (диалог проводника на Windows и в WSL, диалог macOS, либо ввод пути в терминале на обычном Linux).")
    return parser.parse_args(argv)


def _prompt_directory(reason: str, default: str = "") -> str:
    """Ввод пути в терминале (для обычного Linux или когда проводник недоступен). При пустом вводе возвращается default (если задан)."""
    sys.stderr.write(f"{reason}\n")
    if default:
        sys.stderr.write(f"Введите путь к каталогу [{default}]: ")
    else:
        sys.stderr.write("Введите путь к каталогу: ")
    sys.stderr.flush()
    try:
        value = input().strip()
    except EOFError:
        return ""
    return value or default


def _is_win() -> bool:
    return os.name == "nt"


def _is_mac() -> bool:
    return sys.platform == "darwin"


def _is_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return bool(os.environ.get("WSL_DISTRO_NAME"))


def _win_folder_dialog(initial: str | None = None) -> str | None:
    """Нативный диалог выбора папки Windows (pick_folder.ps1, IFileOpenDialog).

    Стартовая папка и заголовок передаются через env (FSNORM_INITIAL, FSNORM_TITLE),
    чтобы не экранировать их в команде. Имена переменных добавляются в WSLENV — иначе
    из-под WSL они не доходят до powershell.exe.

    Возвращает выбранный Windows-путь, "" при отмене (скрипт завершается с кодом 0
    и пустым выводом) или None, если powershell.exe/скрипт недоступен либо вызов
    завершился с ненулевым кодом (откат на ввод в терминале).
    """
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return None
    try:
        script = _PICK_FOLDER_PS1.read_text(encoding="utf-8")
    except OSError:
        return None
    env = os.environ.copy()
    env["FSNORM_TITLE"] = "Выберите каталог для нормализации"
    if initial:
        env["FSNORM_INITIAL"] = initial
    else:
        env.pop("FSNORM_INITIAL", None)
    # В WSL пользовательские переменные окружения не попадают в Windows-процессы
    # (powershell.exe), пока они не перечислены в WSLENV. Без флага значение
    # передаётся как есть — UNC-путь уже в Windows-формате, переводить его не нужно.
    shar = ["FSNORM_TITLE"] + (["FSNORM_INITIAL"] if initial else [])
    mang = {"FSNORM_TITLE", "FSNORM_INITIAL"}
    kept = [e for e in env.get("WSLENV", "").split(":") if e and e.split("/", 1)[0] not in mang]
    env["WSLENV"] = ":".join(kept + shar)
    try:
        dialog = subprocess.run(
            [powershell, "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if dialog.returncode != 0:
        return None  # ошибка скрипта (отмена даёт код 0); откат на терминал
    return dialog.stdout.strip()  # "" при отмене


def _mac_folder_dialog(initial: str | None = None) -> str | None:
    """Нативный диалог выбора папки macOS через osascript.
    initial — POSIX-путь предвыбранной папки (передаётся через env, чтобы
    не экранировать путь в строке скрипта).
    Возвращает POSIX-путь, "" при отмене или None, если osascript недоступен/ошибка.
    """
    osascript = shutil.which("osascript")
    if not osascript:
        return None
    prompt = "Выберите каталог для нормализации"
    script = (
        'set p to (system attribute "FSNORM_INITIAL")\n'
        'if p is not "" then\n'
        f'  POSIX path of (choose folder with prompt "{prompt}" default location (POSIX file p))\n'
        "else\n"
        f'  POSIX path of (choose folder with prompt "{prompt}")\n'
        "end if"
    )
    env = os.environ.copy()
    if initial:
        env["FSNORM_INITIAL"] = initial
    else:
        env.pop("FSNORM_INITIAL", None)  # не подхватывать устаревшее значение
    try:
        dialog = subprocess.run(
            [osascript, "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if dialog.returncode != 0:
        return ""  # отмена (-128) или ошибка диалога
    return dialog.stdout.strip()


def _to_win_path(unix_path: str) -> str | None:
    """Переводит путь WSL в Windows-путь через wslpath. None при ошибке/пустом выводе."""
    wslpath = shutil.which("wslpath")
    if not wslpath:
        return None
    try:
        converted = subprocess.run(
            [wslpath, "-w", unix_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return converted.stdout.strip() or None


def _to_wsl_path(win_path: str) -> str | None:
    """Переводит Windows-путь в путь WSL через wslpath. None при ошибке."""
    wslpath = shutil.which("wslpath")
    if not wslpath:
        return None
    try:
        converted = subprocess.run(
            [wslpath, "-u", win_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return converted.stdout.strip() or None


def _pick_directory() -> str:
    """Windows/WSL — нативный проводник Windows (IFileOpenDialog); macOS — osascript;
    обычный Linux — ввод в терминале. Папка по умолчанию везде — рабочий каталог
    (os.getcwd()): для alias/консоли это каталог вызова, для ярлыка/двойного клика
    на .bat — его «Рабочая папка» (обычно каталог проекта). В WSL путь дополнительно
    переводится в Windows-формат (wslpath) для диалога, а выбранный путь — обратно
    в путь WSL.
    """
    cwd = os.getcwd()
    if _is_win():
        path = _win_folder_dialog(cwd)
        if path is None:
            return _prompt_directory("Проводник Windows недоступен.", default=cwd)
        return path  # путь или "" (отмена)
    if _is_mac():
        path = _mac_folder_dialog(cwd)
        if path is None:
            return _prompt_directory("Стандартный диалог macOS недоступен.", default=cwd)
        return path  # путь или "" (отмена)
    if _is_wsl():
        # Каталог вызова (WSL-путь) -> Windows-путь (UNC) для InitialDirectory диалога.
        # Если конвертация не удалась (None), диалог откроется без стартовой папки.
        win_init = _to_win_path(cwd)
        win_path = _win_folder_dialog(win_init)
        if win_path is None:
            return _prompt_directory("Проводник Windows недоступен.", default=cwd)
        if not win_path:
            return ""  # пользователь отменил выбор
        con = _to_wsl_path(win_path)
        if con is None:
            return _prompt_directory("Не удалось преобразовать путь Windows.", default=cwd)
        return con
    # Обычный Linux: ввод пути в терминале с дефолтом = каталог вызова.
    return _prompt_directory("Укажите каталог для нормализации.", default=cwd)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    targ = _pick_directory()
    if not targ:
        sys.stderr.write("Каталог не выбран.\n")
        return 1
    root = Path(targ).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError:
        sys.stderr.write(f"Ошибка: каталог не найден: {targ}\n")
        return 1
    if not root.is_dir():
        sys.stderr.write(f"Ошибка: каталог не является каталогом: {root}\n")
        return 1
    fsnm = FilesystemNormalizer(build_normalizer())
    print(f"Каталог: {root}")
    renamed, skipped = fsnm.apply(root)
    print(f"Готово. Переименовано: {renamed}, пропущено: {skipped}.")
    return 0
