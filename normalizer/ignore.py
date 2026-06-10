"""Единый фильтр путей в стиле .gitignore (файл .fs-ignore в нормализуемом каталоге).

Семантика — настоящая gitignore (движок `pathspec`; фабрика паттернов выбирается
`_factory_name()`: `gitignore`, иначе устаревший `gitwildmatch`). Обычная строка
исключает объект из нормализации, строка с ведущим `!` — возвращает (override).
Порядок строк важен: выигрывает ПОСЛЕДНЯЯ совпавшая (как в git). Полный набор
метасимволов gitignore активен: `*` (в пределах сегмента), `**` (cross-segment),
`?` (один символ), `[abc]`/`[a-z]` (класс), завершающий `/` (только каталоги),
ведущий/срединный `/` (якорь к корню). Литеральные `[`, `]`, `?` экранируются `\\`
(`Файл \\[1\\]`). Разделитель — только `/` (как в gitignore); `\\` — экранирование.
Префикс `./` НЕ поддерживается (`.` — обычный сегмент, паттерн молча не совпадёт):
пишите `foo` (basename) или `/foo` (якорь). Комментарий — только ведущий `#`
(срединный литерален, `C#/Projects` валиден); литеральный ведущий `#` — как `\\#`.

Файл .fs-ignore лежит в нормализуемом каталоге (корне `apply`) и читается из него,
как `.gitignore` в корне репозитория. Матчинг ОТНОСИТЕЛЬНЫЙ к этому же каталогу:
ведущий/срединный `/` якорит к его верхушке (см. FilesystemNormalizer). Поэтому
паттерны кросс-платформенны без указания диска. Сам файл .fs-ignore скрыт (имя на
`.`), при обходе пропускается и при сопоставлении НЕ изменяется (только чтение).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pathspec
from pathspec.util import lookup_pattern


def _factory_name() -> str:
    """Имя фабрики gitignore-паттернов, доступной в установленной pathspec.

    В новых версиях алиас 'gitwildmatch' объявлен устаревшим в пользу 'gitignore',
    а в pathspec<0.12-совместимых сборках есть только 'gitwildmatch'. Берём первое
    доступное, чтобы не привязываться к версии и не плодить DeprecationWarning.
    """
    for name in ("gitignore", "gitwildmatch"):
        try:
            lookup_pattern(name)
        except LookupError:
            continue
        return name
    return "gitwildmatch"


_FACTORY = _factory_name()


class FsIgnore:
    """Обёртка над pathspec.PathSpec: матчинг пути относительно корня нормализации.

    `incl` — есть ли в списке хотя бы одно правило-override (`!...`). При его
    наличии обход не обрезает исключённые каталоги (внутри возможны возвращённые
    потомки); см. FilesystemNormalizer.
    """

    def __init__(self, spec: pathspec.PathSpec[Any], incl: bool):
        self._spec = spec
        self.incl = incl

    def matches(self, rel: Path, is_dir: bool) -> bool:
        """Сопоставляет путь, заданный ОТНОСИТЕЛЬНО корня нормализации.

        Путь приводится к posix (`/` как разделитель на всех ОС); каталогам
        добавляется завершающий `/`, чтобы работали dir-only паттерны (`build/`).
        """
        text = rel.as_posix()
        if is_dir:
            text += "/"
        return self._spec.match_file(text)


def load_fs_ignore(root: Path) -> FsIgnore | None:
    """Читает .fs-ignore из нормализуемого каталога. Нет файла -> None (выключен).

    `root` — корень нормализации (выбранный каталог): паттерны и якорь `/` будут
    отсчитываться от него же. Пустой файл (или из комментариев/пустых строк) даёт
    FsIgnore без правил — ничего не исключает. Файл не изменяется (чтение `utf-8-sig`).
    """
    path = root / ".fs-ignore"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    spec = pathspec.PathSpec.from_lines(_FACTORY, raw.splitlines())
    incl = any(p.include is False for p in spec.patterns)
    return FsIgnore(spec, incl)
