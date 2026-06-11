"""Обрезка не буквенно-цифровых символов по краям имени."""
from __future__ import annotations

import re

from .base import Rule


class TrimEdgeRule(Rule):
    """Обрезает не буквенно-цифровые символы по краям имени.

    '+' и '#' считаются символами имени (а не кромочным мусором) и сохраняются по
    обоим краям: это значимые символы в названиях вроде 'C#', 'C++', 'F#',
    'notepad++'. Иначе хвостовые '#'/'++' срезались бы, и 'C#'/'C++' схлопывались
    бы в 'C' (коллизия). Прочий не буквенно-цифровой мусор ('!', ',', '.', '@',
    '-') по-прежнему срезается. Барьеры безопасности не затрагиваются: '+'/'#' не
    разделители пути и не запрещены на Windows (см. safety.py).

    Исключение — парная скобка на краю: у 'inn-(...-net)' (или '[...]') концевую
    ')'/']' не срезаем, если есть непарная открывающая (симметрично для ведущей).
    Числовые скобки к этому моменту уже убраны BracketsRule.
    """

    _LE = re.compile(r"^[^0-9A-Za-z+#]+")
    _TE = re.compile(r"[^0-9A-Za-z+#]+$")
    # Ведущие '_' сохраняем и у файлов, и у папок (например, _private,
    # __init__), обрезаем только остальной «мусор» по краям.
    _LEAD_US = re.compile(r"^_+")
    _PR = (("(", ")"), ("[", "]"))

    def apply(self, stem: str, is_dir: bool) -> str:
        lead = ""
        m = self._LEAD_US.match(stem)
        if m:
            lead = m.group(0)
            stem = stem[len(lead):]
        stem = self._trim_leadin(stem)
        stem = self._trim_traili(stem)
        return lead + stem

    @classmethod
    def _trim_leadin(cls, stem: str) -> str:
        m = cls._LE.match(stem)
        if not m:
            return stem
        junk, tail = m.group(0), stem[m.end():]
        for opener, closer in cls._PR:
            if opener in junk and tail.count(closer) > tail.count(opener):
                return opener + tail  # сохраняем парную ведущую скобку
        return tail

    @classmethod
    def _trim_traili(cls, stem: str) -> str:
        m = cls._TE.search(stem)
        if not m:
            return stem
        head, junk = stem[:m.start()], m.group(0)
        for opener, closer in cls._PR:
            if closer in junk and head.count(opener) > head.count(closer):
                return head + closer  # сохраняем парную концевую скобку
        return head
