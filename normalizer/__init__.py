"""Пакет нормализации имён файлов и папок.

Публичное API: импортируйте отсюда, а не из подмодулей напрямую.
"""
from __future__ import annotations

from .cli import main
from .exclude import PathExcluder, PathIncluder, load_excluder, load_includer
from .filesystem import FilesystemNormalizer
from .name import NameNormalizer, build_normalizer
from .rules import (
    BracketsRule,
    CaseRule,
    DateRule,
    LeadingZeroRule,
    Rule,
    SpaceToDashRule,
    TransliterationRule,
    TrimEdgeRule,
)

__all__ = [
    "main",
    "FilesystemNormalizer",
    "PathExcluder",
    "PathIncluder",
    "load_excluder",
    "load_includer",
    "NameNormalizer",
    "build_normalizer",
    "Rule",
    "TransliterationRule",
    "BracketsRule",
    "DateRule",
    "LeadingZeroRule",
    "CaseRule",
    "SpaceToDashRule",
    "TrimEdgeRule",
]
