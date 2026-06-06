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


# Разделители пути ('/' на всех ОС, '\' на Windows) и ASCII-управляющие символы
# (0x00-0x1F, включая '\n'). Имя файла/папки не должно содержать ни одного из них:
# иначе нормализованное имя перестаёт быть одним компонентом пути.
_DIR_UNSAFE_RE = re.compile(r"[\\/\x00-\x1f]+")

# Символы, запрещённые в именах файлов Windows. Транслитерация легко их порождает
# из типографики ('«'->'<<', '»'->'>>', '“'/'”'->'"'). В отличие от разделителей
# пути их нельзя оставить даже в виде '-': пользователь хочет, чтобы такой «мусор»
# просто вырезался. Удаляем ВЕЗДЕ (не только по краям), иначе одиночный '<' в
# середине имени ломает os.rename на Windows (WinError 123).
_WIN_FRBIDDDEN_RE = re.compile(r'[<>:"|?*]+')


class Rule(ABC):
    """Базовое правило: преобразует stem имени."""

    @abstractmethod
    def apply(self, stem: str, is_dir: bool) -> str:  # pragma: no cover - интерфейс
        ...


class TransliterationRule(Rule):
    """Любой не-ASCII символ -> ASCII (кириллица, умляуты, emoji и т.п.).

    Транслитерация может породить разделители пути и управляющие символы:
    например '½' -> '1/2', '½'(дробь)/'∖'/стрелки -> '\\', а U+2028/U+2029 -> '\\n'.
    Если оставить их в stem, os.rename истолкует '/'/'\\' как разделитель пути и
    МОЛЧА переместит объект в соседний каталог (или потеряет его). Поэтому сразу
    после транслитерации такие символы заменяются на '-': имя гарантированно
    остаётся ОДНИМ компонентом пути на любой ОС. Делается это до остальных правил,
    чтобы LeadingZero/Trim видели одинаковую структуру токенов и сохранялась
    идемпотентность.

    Дополнительно чистятся два класса «мусора», который вносит unidecode:
    - мягкий и твёрдый знаки ('ь'/'ъ' -> апостроф) удаляются ДО транслитерации,
      чтобы апостроф не появлялся вовсе (ASCII-апостроф во входном имени, как в
      O'Brien, при этом не затрагивается);
    - запрещённые на Windows символы ('< > : " | ? *', в которые превращается
      типографика вроде '«»') удаляются ПОСЛЕ транслитерации.
    """

    # Кириллические знаки, дающие через unidecode апостроф, вырезаем.
    _DROP = str.maketrans("", "", "ьЬъЪ")

    def apply(self, stem: str, is_dir: bool) -> str:
        ascii_stem = stem.translate(self._DROP)
        ascii_stem = unidecode(ascii_stem)
        ascii_stem = _DIR_UNSAFE_RE.sub("-", ascii_stem)
        ascii_stem = _WIN_FRBIDDDEN_RE.sub("", ascii_stem)
        return ascii_stem


class BracketsRule(Rule):
    """Круглые и квадратные скобки: с числом/датой убираем, с текстом сохраняем.

    Дубли файловых менеджеров ('Файл (1)', 'Файл [1]') -> 'file-01': скобки
    вокруг числа/даты снимаем, дальше DateRule/LeadingZero дополнят. Скобки с
    буквами ('(копия)', '[черновик]') оставляем как часть имени. Идёт после
    транслитерации (содержимое уже ASCII, проверка '[A-Za-z]' однозначна).
    Пустые и непарные/несовпадающие скобки ('Файл (1', 'инн (текст]') убираются:
    обрабатываем сбалансированные пары до стабилизации, остаток (непарные '()[]')
    вырезаем.
    """

    _RE = re.compile(r"\(([^()\[\]]*)\)|\[([^()\[\]]*)\]")
    _HAS_LETTER = re.compile(r"[A-Za-z]")
    _OP = {"(": ")", "[": "]"}
    _CL = {")": "(", "]": "["}

    def apply(self, stem: str, is_dir: bool) -> str:
        prev = ""
        while prev != stem:  # вложенные пары: '((1))' -> '(1)' -> '1'
            prev = stem
            stem = self._RE.sub(self._rep, stem)
        return self._strip_unpa(stem)

    @classmethod
    def _rep(cls, m: "re.Match[str]") -> str:
        content = m.group(1) if m.group(1) is not None else m.group(2)
        if cls._HAS_LETTER.search(content):
            return m.group(0)  # текст — скобки сохраняем
        return content  # число/дата/пусто — скобки убираем

    @classmethod
    def _strip_unpa(cls, stem: str) -> str:
        # Стек сопоставляет открывающие с закрывающими; индексы найденных пар —
        # в pairs, всё остальное из '()[]' (непарное/несовпадающее) вырезаем.
        pairs: set[int] = set()
        stack: list[tuple[str, int]] = []
        for i, ch in enumerate(stem):
            if ch in cls._OP:
                stack.append((ch, i))
            elif ch in cls._CL and stack and stack[-1][0] == cls._CL[ch]:
                pairs.add(i)
                pairs.add(stack.pop()[1])
        return "".join(ch for i, ch in enumerate(stem) if i in pairs or (ch not in cls._OP and ch not in cls._CL))


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
            return cls._format_mmyy(m.group("mmyy")) or m.group(0)
        if m.group("year"):
            year = int(m.group("year"))
            if 1900 <= year <= 2099:
                return f"{year:04d}-00-00"
            return m.group(0)
        return m.group(0)  # pragma: no cover

    @staticmethod
    def _sep(m: "re.Match[str]") -> str:
        out = m.group("date")
        if m.group("pre") is not None:
            out = "_" + out
        if m.group("post") is not None:
            out = out + "_"
        return out

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
    def _format_mmyy(cls, text: str) -> str | None:
        parts = cls._SP.split(text)
        if len(parts[0]) == 4:
            year, month = parts
        else:
            month, year = parts
        month_i = int(month)
        if not 1 <= month_i <= 12:
            return None
        return f"{int(year):04d}-{month_i:02d}-00"


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
    """Пробелы -> дефис; цепочки дефисов вокруг пробелов схлопываются в один.

    Схлопывается только прогон с пробелом ('Резюме - подготовка' дало бы три
    тире, а нужно одно). Намеренные дефисы без пробелов ('file--improved') и
    одиночные дефисы дат ('2020-05-20') сохраняются — идемпотентность не страдает.
    """

    # Прогон с пробелом (и любыми соседними дефисами) -> один дефис; чисто
    # дефисные прогоны не трогаем, чтобы 'file--improved' сохранил двойное тире.
    _RE = re.compile(r"[\s-]*\s[\s-]*")

    def apply(self, stem: str, is_dir: bool) -> str:
        return self._RE.sub("-", stem)


class TrimEdgeRule(Rule):
    """Обрезает не буквенно-цифровые символы по краям имени.

    Исключение — парная скобка на краю: у 'inn-(...-net)' (или '[...]') концевую
    ')'/']' не срезаем, если есть непарная открывающая (симметрично для ведущей).
    Числовые скобки к этому моменту уже убраны BracketsRule.
    """

    _LE = re.compile(r"^[^0-9A-Za-z]+")
    _TE = re.compile(r"[^0-9A-Za-z]+$")
    # Ведущие '_' у файлов сохраняем (например, _private, __init__),
    # обрезаем только остальной «мусор» по краям.
    _LEAD_US = re.compile(r"^_+")
    _PR = (("(", ")"), ("[", "]"))

    def apply(self, stem: str, is_dir: bool) -> str:
        lead = ""
        if not is_dir:
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
