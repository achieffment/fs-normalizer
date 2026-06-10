"""Обход файловой системы и применение переименований."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from .ignore import FsIgnore
from .name import NameNormalizer


class FilesystemNormalizer:
    """Сбор путей (с обрезкой скрытых) и переименование deepest-first."""

    def __init__(
        self,
        normalizer: NameNormalizer,
        ignorer: FsIgnore | None = None,
    ):
        self.normalizer = normalizer
        self.ignorer = ignorer

    @staticmethod
    def _hidden(name: str) -> bool:
        return name.startswith(".")

    def _skip(self, path: Path, root: Path, is_dir: bool) -> bool:
        """Пропустить ли объект: совпал ли его путь (ОТНОСИТЕЛЬНО root) с .fs-ignore.

        Override-правила (`!`) учитываются движком pathspec по порядку строк
        (выигрывает последняя совпавшая), поэтому здесь достаточно одного вызова.
        """
        if self.ignorer is None:
            return False
        return self.ignorer.matches(path.relative_to(root), is_dir)

    def _collect(self, root: Path) -> list[Path]:
        # При наличии override-правил (`!`) нельзя обрезать исключённые каталоги:
        # внутри могут быть возвращённые потомки, до которых надо дойти. Тогда
        # заходим во все нескрытые каталоги, а skip/normalize решаем по объекту.
        probe = self.ignorer is not None and self.ignorer.has_negation
        items: list[Path] = []
        for dirpath, foldnames, filenames in os.walk(root, topdown=True, followlinks=False):
            base = Path(dirpath)
            kept_folds: list[str] = []
            for name in foldnames:
                if self._hidden(name):
                    continue                          # скрытые не обходим
                skip = self._skip(base / name, root, is_dir=True)
                if skip and not probe:
                    continue                          # обрезаем исключённое поддерево
                kept_folds.append(name)               # заходим внутрь
                if not skip:
                    items.append(base / name)
            foldnames[:] = kept_folds
            for name in filenames:
                if self._hidden(name):
                    continue
                if not self._skip(base / name, root, is_dir=False):
                    items.append(base / name)
        # Корневой каталог не добавляется (берём только его содержимое) -> не переименовывается.
        return items

    def apply(self, root: Path) -> tuple[int, int]:
        items = self._collect(root)
        # Самые вложенные — первыми: дети переименовываются раньше родителей.
        items.sort(key=lambda p: len(p.parts), reverse=True)
        renamed = 0
        skipped = 0
        for srcp in items:
            if not srcp.exists():
                skipped += 1
                continue
            name = self.normalizer.normalize(srcp.name, srcp.is_dir())
            if name == srcp.name:
                continue
            dest = srcp.parent / name
            case = srcp.name.casefold() == dest.name.casefold()
            try:
                # Конфликт — это занятость dest ДРУГИМ объектом. При case-only
                # переименовании на регистронезависимой ФС dest.exists() истинно,
                # но указывает на сам srcp (samefile), и конфликтом не является.
                if dest.exists() and not srcp.samefile(dest):
                    sys.stderr.write(f"Пропуск (конфликт): {srcp} -> {dest}\n")
                    skipped += 1
                    continue
                if case:
                    # На регистронезависимых ФС (Windows) — через временное имя.
                    temp = dest.parent / f".__normtmp_{uuid.uuid4().hex}"
                    os.rename(srcp, temp)
                    os.rename(temp, dest)
                else:
                    os.rename(srcp, dest)
                renamed += 1
            except OSError as exc:
                sys.stderr.write(f"Ошибка переименования {srcp} -> {dest}: {exc}\n")
                skipped += 1
        return renamed, skipped
