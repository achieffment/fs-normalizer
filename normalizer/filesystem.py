"""Обход файловой системы и применение переименований."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from .exclude import PathExcluder, PathIncluder
from .name import NameNormalizer


class FilesystemNormalizer:
    """Сбор путей (с обрезкой скрытых) и переименование deepest-first."""

    def __init__(
        self,
        normalizer: NameNormalizer,
        excluder: PathExcluder | None = None,
        includer: PathIncluder | None = None,
    ):
        self.normalizer = normalizer
        self.excluder = excluder
        self.includer = includer

    @staticmethod
    def _hidden(name: str) -> bool:
        return name.startswith(".")

    def _skip(self, path: Path) -> bool:
        """Пропустить ли объект: исключён exclude и не возвращён include.

        Конфликт решается по глубине последнего совпавшего сегмента: include
        побеждает, если совпал не мельче exclude (ничья — в пользу include).
        """
        if self.excluder is None:
            return False
        excl = self.excluder.deepest_match(path)
        if excl < 0:
            return False
        if self.includer is None:
            return True
        return self.includer.deepest_match(path) < excl

    def _collect(self, root: Path) -> list[Path]:
        # Когда include задан, нельзя обрезать исключённые каталоги: внутри могут
        # быть повторно включённые потомки, до которых надо дойти. Тогда заходим
        # во все нескрытые каталоги, а решение skip/normalize принимаем по объекту.
        probe = self.includer is not None and bool(self.includer.patterns)
        items: list[Path] = []
        for dirpath, foldnames, filenames in os.walk(root, topdown=True, followlinks=False):
            base = Path(dirpath)
            kept_folds: list[str] = []
            for name in foldnames:
                if self._hidden(name):
                    continue                          # скрытые не обходим
                skip = self._skip(base / name)
                if skip and not probe:
                    continue                          # обрезаем исключённое поддерево
                kept_folds.append(name)               # заходим внутрь
                if not skip:
                    items.append(base / name)
            foldnames[:] = kept_folds
            for name in filenames:
                if self._hidden(name):
                    continue
                if not self._skip(base / name):
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
