"""Фильтры путей: exclude (пропуск) и include (повторное включение).

Списки фрагментов читаются из exclude.txt и include.txt в корне проекта.
Сопоставление — по сегментам пути (а не сырой подстрокой) против полного
абсолютного пути объекта, с поддержкой glob. Спецсимвол только один — '*':
- '*' — любое количество символов (в т.ч. ноль) В ПРЕДЕЛАХ ОДНОГО сегмента
  (не пересекает разделитель): '*.txt', 'a*', '*foo*', 'data-*-final';
  одиночная '*' = ровно один сегмент целиком (сегменты всегда непустые).
- '**' — ТОЛЬКО как ЦЕЛЫЙ сегмент: ноль или более сегментов (cross-segment).
- Любая другая комбинация со звёздами в сегменте ('a**b', '***', 'a*b*') —
  обычный intra-segment '*' (несколько '*' подряд = один '*').
Символы '?', '[', ']' — ЛИТЕРАЛЫ (в именах проекта скобки встречаются повсюду),
поэтому fnmatch не используется. Файлы при сопоставлении НЕ изменяются: их
строки лишь приводятся к каноническому виду в памяти.

Конфликт exclude/include решается в FilesystemNormalizer по глубине последнего
совпавшего сегмента (см. там), а здесь матчер лишь сообщает эту глубину.
"""
from __future__ import annotations

import re
from pathlib import Path

# Буква диска Windows ('C:', 'D:') и WSL-монтирование ('/mnt/d') приводятся к
# ОДНОМУ сохраняемому токену-букве ('d'), чтобы 'D:\\Programs' и '/mnt/d/Programs'
# совпадали в обе стороны (Windows<->WSL), но РАЗНЫЕ диски не путались
# ('E:\\Programs' != 'D:\\Programs'). Только токен диска — в lower; остальные
# сегменты сохраняют регистр как в паттерне и в str(path).
_DRIVE_RE = re.compile(r"^([A-Za-z]):$")
_MOUNT_LETTER_RE = re.compile(r"^[A-Za-z]$")


def _canon(text: str) -> tuple[str, ...]:
    """Путь/фрагмент -> кортеж канонических сегментов.

    Разделители '\\' приводятся к '/', регистр сегментов сохраняется (матчинг
    регистрозависимый), пустые сегменты отбрасываются. Исключение — буква диска
    и WSL-монтирование: сводятся к одному токену-букве в lower ('D:' -> 'd',
    '/mnt/d/...' -> 'd/...') для симметрии Windows<->WSL. Относительный путь без
    диска ('Programs') токена не получает и совпадает с любым диском. Glob-
    метасимвол '*' внутри сегмента (и целый сегмент '**') проходит как есть.
    """
    frag = [p.strip() for p in text.replace("\\", "/").split("/")]
    segs = [p for p in frag if p]
    if segs and (drive := _DRIVE_RE.match(segs[0])):
        segs = [drive.group(1).lower(), *segs[1:]]   # 'D:' -> 'd'
    elif len(segs) >= 2 and segs[0] == "mnt" and _MOUNT_LETTER_RE.match(segs[1]):
        segs = [segs[1].lower(), *segs[2:]]           # '/mnt/d/...' -> 'd/...'
    return tuple(segs)


def _seg_glob(pat_seg: str, text_seg: str) -> bool:
    """Сопоставляет ОДИН сегмент: спецсимвол только '*' (любые символы, в т.ч.
    ноль, в пределах сегмента), остальное — литералы (включая '?', '[', ']').

    Сегмент-паттерн делится по '*' на литеральные части: первая должна быть
    префиксом, последняя — суффиксом, промежуточные — встречаться по порядку без
    перекрытия. Несколько '*' подряд (или вперемешку, 'a**b', '***') дают пустые
    части и работают как один '*'. Без '*' — точное равенство (обратная
    совместимость). Регистр сохраняется (_canon не меняет сегменты, кроме токена
    диска).
    """
    frag = pat_seg.split("*")
    if len(frag) == 1:                                # нет '*' -> литерал
        return pat_seg == text_seg
    pref, suf = frag[0], frag[-1]
    if not text_seg.startswith(pref) or not text_seg.endswith(suf):
        return False
    pos = len(pref)
    region_end = len(text_seg) - len(suf)           # суффикс занимает хвост
    if pos > region_end:                              # префикс и суффикс перекрылись
        return False
    for mid in frag[1:-1]:
        if not mid:                                   # пустая часть от соседних '*'
            continue
        idx = text_seg.find(mid, pos, region_end)
        if idx < 0:
            return False
        pos = idx + len(mid)
    return True


def _match_end(segs: tuple[str, ...], start: int, pat: tuple[str, ...]) -> int:
    """Самый глубокий индекс конца совпадения pat в segs, начиная с start.

    Целый сегмент '**' поглощает 0+ сегментов (cross-segment); любой другой
    сегмент-паттерн сопоставляется с ОДНИМ сегментом через _seg_glob (intra '*').
    Возвращает максимальный достижимый конец (для глубины) или -1, если нет.
    Конец «плавающий»: лишние сегменты после совпадения допускаются.
    """
    if not pat:
        return start
    head, rest = pat[0], pat[1:]
    if head == "**":
        best = -1
        for k in range(start, len(segs) + 1):         # '**' поглощает segs[start:k]
            end = _match_end(segs, k, rest)
            if end > best:
                best = end
        return best
    if start >= len(segs):
        return -1
    if _seg_glob(head, segs[start]):
        return _match_end(segs, start + 1, rest)
    return -1


def _deepest_end(segs: tuple[str, ...], pat: tuple[str, ...]) -> int:
    """Максимальный конец совпадения pat где угодно в segs (плавающий старт)."""
    if not pat:
        return -1
    best = -1
    for i in range(len(segs) + 1):
        end = _match_end(segs, i, pat)
        if end > best:
            best = end
    return best


class PathMatcher:
    """Сопоставление пути со списком канонических glob-паттернов-сегментов."""

    def __init__(self, patterns: list[tuple[str, ...]]):
        self.patterns = patterns

    def deepest_match(self, path: Path) -> int:
        """Глубина (индекс конца) самого глубокого совпадения; -1 — нет совпадений."""
        if not self.patterns:
            return -1
        segs = _canon(str(path))
        best = -1
        for pat in self.patterns:
            end = _deepest_end(segs, pat)
            if end > best:
                best = end
        return best

    def matches(self, path: Path) -> bool:
        return self.deepest_match(path) >= 0


class PathExcluder(PathMatcher):
    """Матчер exclude.txt: какие пути исключить из нормализации."""

    def is_excluded(self, path: Path) -> bool:
        return self.matches(path)


class PathIncluder(PathMatcher):
    """Матчер include.txt: какие пути повторно включить (override exclude)."""

    def is_included(self, path: Path) -> bool:
        return self.matches(path)


def _load_patterns(path: Path) -> list[tuple[str, ...]] | None:
    """Читает список паттернов из файла. Нет файла -> None. Пустые строки
    игнорируются, файл не изменяется."""
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    return [seg for line in raw.splitlines() if (seg := _canon(line))]


def load_excluder(project_root: Path) -> PathExcluder | None:
    """Читает exclude.txt из корня проекта. Нет файла -> None (проверки выключены).

    Пустой файл даёт PathExcluder без паттернов (ничего не исключает) — обычное
    поведение.
    """
    patterns = _load_patterns(project_root / "exclude.txt")
    return None if patterns is None else PathExcluder(patterns)


def load_includer(project_root: Path) -> PathIncluder | None:
    """Читает include.txt из корня проекта. Нет файла -> None.

    include только переопределяет exclude (возвращает к нормализации убранное);
    без exclude.txt не влияет ни на что.
    """
    patterns = _load_patterns(project_root / "include.txt")
    return None if patterns is None else PathIncluder(patterns)
