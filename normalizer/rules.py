"""Правила нормализации имён. Каждое правило преобразует stem имени."""
from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime

try:
    from unidecode import unidecode
except ImportError:  # pragma: no cover - дружелюбное сообщение вместо трейсбека
    sys.stderr.write("Не найден пакет 'Unidecode'. Установите зависимости:\npip install -r requirements.txt\n")
    raise


class Rule(ABC):
    """Базовое правило: преобразует stem имени."""

    @abstractmethod
    def apply(self, stem: str, is_dir: bool) -> str:  # pragma: no cover - интерфейс
        ...


class TransliterationRule(Rule):
    """Любой не-ASCII символ -> ASCII (кириллица, умляуты, emoji и т.п.)."""

    def apply(self, stem: str, is_dir: bool) -> str:
        return unidecode(stem)


class DateRule(Rule):
    """
    Находит даты в имени и приводит их к ISO-форме с плейсхолдерами '00'.
    Порядок альтернатив важен: от самого специфичного к общему, чтобы
    частичные шаблоны не «съедали» более полные. Уже нормализованные формы
    распознаются первыми и не меняются (идемпотентность).
    """

    # Внешние границы исключают соседние буквы И цифры: дата — отдельный токен,
    # ограниченный разделителями (. - _ / пробел) или краями строки. Иначе цифры
    # внутри слов давали бы ложные даты: model2020, version2021, abc1999x.
    _RE = re.compile(
        r"""
        (?<![0-9A-Za-z])                # слева не буква/цифра
        (?:
            (?P<norm>                   # уже готовый ISO — не трогаем (идемпотентность)
                \d{4,4}-\d{2,2}-\d{2,2}
            )
          | (?P<full>                   # полная дата: YYYY.MM.DD или DD.MM.YYYY
                \d{4,4}[._/-]\d{1,2}[._/-]\d{1,2}
              | \d{1,2}[._/-]\d{1,2}[._/-]\d{4,4}
            )
          | (?P<mmyy>                   # месяц+год: MM.YYYY или YYYY.MM
                \d{1,2}[._/-]\d{4,4}
              | \d{4,4}[._/-]\d{1,2}
            )
          | (?P<year>                   # только год
                \d{4,4}
            )
        )
        (?![0-9A-Za-z])                 # справа не буква/цифра
        """,
        re.VERBOSE,
    )
    _SP = re.compile(r"[._/\-]")

    # Каноническая дата (после нормализации) и её соседние разделители.
    # Используется, чтобы любой разделитель вокруг даты привести к '_'
    # (2020-05-05-file -> 2020-05-05_file, dump-2020-05-05 -> dump_2020-05-05).
    _DF = r"\d{4,4}-\d{2,2}-\d{2,2}"
    _BR = re.compile(
        r"(?P<pre>[ ._/\-]+)?(?P<date>" + _DF + r")(?P<post>[ ._/\-]+)?"
    )

    def apply(self, stem: str, is_dir: bool) -> str:
        stem = self._RE.sub(self._rep, stem)
        return self._BR.sub(self._sep, stem)

    @classmethod
    def _rep(cls, m: "re.Match[str]") -> str:
        if m.group("norm"):
            return m.group(0)
        if m.group("full"):
            return cls._format_full(m.group("full")) or m.group(0)
        if m.group("mmyy"):
            return cls._format_month_year(m.group("mmyy")) or m.group(0)
        if m.group("year"):
            year = int(m.group("year"))
            if 1900 <= year <= 2099:
                return f"{year:04d}-00-00"
            return m.group(0)
        return m.group(0)  # pragma: no cover

    @classmethod
    def _format_full(cls, text: str) -> str | None:
        parts = cls._SP.split(text)
        if len(parts[0]) == 4:
            year, month, day = parts  # ISO-порядок
        else:
            day, month, year = parts  # день-первым
        try:
            dt = datetime(int(year), int(month), int(day))
        except ValueError:
            return None
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"

    @classmethod
    def _format_month_year(cls, text: str) -> str | None:
        parts = cls._SP.split(text)
        if len(parts[0]) == 4:
            year, month = parts
        else:
            month, year = parts
        month_i = int(month)
        if not 1 <= month_i <= 12:
            return None
        return f"{int(year):04d}-{month_i:02d}-00"

    @staticmethod
    def _sep(m: "re.Match[str]") -> str:
        out = m.group("date")
        if m.group("pre") is not None:
            out = "_" + out
        if m.group("post") is not None:
            out = out + "_"
        return out


class LeadingZeroRule(Rule):
    """
    Однозначное число как отдельный токен -> с ведущим нулём.
    Токен ограничен пробелом/подчёркиванием/дефисом или краями строки.
    Дроби (1.5), числа с буквами (v2, 2x) и компоненты дат не затрагиваются.
    """

    _SE = " _-"

    def apply(self, stem: str, is_dir: bool) -> str:
        score: list[str] = []
        token = ""
        for ch in stem:
            if ch in self._SE:
                score.append(self._pad(token))
                score.append(ch)
                token = ""
            else:
                token += ch
        score.append(self._pad(token))
        return "".join(score)

    @staticmethod
    def _pad(token: str) -> str:
        if len(token) == 1 and token in "0123456789":
            return "0" + token
        return token


class CaseRule(Rule):
    """Папки — с заглавной буквы, файлы — в нижнем регистре.

    Исключение: общепринятые имена-маркеры (README и т.п.) сохраняют
    свой регистр — их stem не приводится к нижнему. Чтобы защитить новое
    имя, достаточно добавить его в PRESERVED_STEMS.
    """

    # Имена (stem без расширения), регистр которых не меняем: README, README.md ...
    PRESERVED_STEMS = frozenset({"README"})

    def apply(self, stem: str, is_dir: bool) -> str:
        if is_dir:
            return stem[:1].upper() + stem[1:]
        if stem in self.PRESERVED_STEMS:
            return stem
        return stem.lower()


class SpaceToDashRule(Rule):
    """Пробелы (и их повторы) -> одиночный дефис."""

    _RE = re.compile(r"\s+")

    def apply(self, stem: str, is_dir: bool) -> str:
        return self._RE.sub("-", stem)


class TrimEdgeRule(Rule):
    """Обрезает не буквенно-цифровые символы по краям имени."""

    _LE = re.compile(r"^[^0-9A-Za-z]+")
    _TE = re.compile(r"[^0-9A-Za-z]+$")
    # Ведущие '_' у файлов сохраняем (например, _private, __init__),
    # обрезаем только остальной «мусор» по краям.
    _LEAD_US = re.compile(r"^_+")

    def apply(self, stem: str, is_dir: bool) -> str:
        lead = ""
        if not is_dir:
            m = self._LEAD_US.match(stem)
            if m:
                lead = m.group(0)
                stem = stem[len(lead):]
        stem = self._LE.sub("", stem)
        return lead + self._TE.sub("", stem)
