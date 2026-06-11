"""Кросс-секционные тесты: пайплайн, идемпотентность, безопасность, ФС и фильтр.

Тесты отдельных правил — в tests/rules/test_<rule>.py. Фикстура `nn` — в conftest.py.
"""
from pathlib import PurePosixPath

import pathspec
import pytest

from normalizer import (
    FilesystemNormalizer,
    FsIgnore,
    build_normalizer,
    load_fs_ignore,
)
from normalizer.ignore import _FACTORY
from normalizer.safety import enforce_safe_component


# --------------------------------------------------------------------------- #
# Конвейер целиком (файлы)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, expected",
    [
        ("Отчёт.TXT", "otchiot.TXT"),
        ("1_file.TXT", "01_file.TXT"),
        ("v2 readme.MD", "v2-readme.MD"),
        ("20.05.2020_dump", "2020-05-20_dump"),
        ("dump_20.05.2020", "dump_2020-05-20"),
        ("05.2020_report", "2020-05-00_report"),
        # '_' не разделитель MM_YYYY: цифра-индекс перед датой не «съедает» год,
        # готовая дата сохраняется, результат идемпотентен:
        ("7_2020.05.20", "07_2020-05-20"),
        ("3 2021.03.10", "03_2021-03-10"),
        ("2020.05", "2020-05-00"),
        ("2020", "2020-00-00"),
        ("-file_01-.png", "file_01.png"),
        ("файл 1.JPG", "fail-01.JPG"),
        # Одиночная цифра рядом с кромочным «мусором»: ведущий ноль за один
        # проход (LeadingZeroRule идёт после TrimEdgeRule). Регресс идемпотентности.
        ("том 5!.txt", "tom-05.txt"),
        ("глава 9-.md", "glava-09.md"),
        ("2020-05-05-file.txt", "2020-05-05_file.txt"),
        ("dump-2020-05-05.txt", "dump_2020-05-05.txt"),
        # Дубли файлового менеджера ('(1)' и '[1]') -> скобки убираются, ведущий ноль:
        ("Файл (1).docx", "fail-01.docx"),
        ("Файл (12).docx", "fail-12.docx"),
        ("Файл [1].docx", "fail-01.docx"),
        # Текст в скобках -> скобки сохраняются (концевая скобка не срезается):
        ("инн (Нового договора нет).txt", "inn-(novogo-dogovora-net).txt"),
        ("инн [Нового договора нет].txt", "inn-[novogo-dogovora-net].txt"),
        # Пробел-дефис-пробел схлопывается в одно тире:
        ("Резюме - подготовка.txt", "reziume-podgotovka.txt"),
        # Намеренное двойное тире (без пробелов) сохраняется:
        ("file--improved.txt", "file--improved.txt"),
        # Незакрытые/несовпадающие скобки вырезаются (как невалидный мусор):
        ("Файл (1.docx", "fail-01.docx"),
        ("Файл (1].docx", "fail-01.docx"),
        ("инн (Нового договора нет.txt", "inn-novogo-dogovora-net.txt"),
        # Мягкий знак удаляется (не превращается в апостроф):
        ("Письмо.txt", "pismo.txt"),
        # Кавычки-«ёлочки» (unidecode -> '<<'/'>>') запрещены на Windows: вырезаются:
        (
            "Заявление директору ООО «Печоралифтсервис».docx",
            "zaiavlenie-direktoru-ooo-pechoraliftservis.docx",
        ),
    ],
)
def test_file_pipeline(nn, name, expected):
    assert nn.normalize(name, is_dir=False) == expected


# --------------------------------------------------------------------------- #
# Конвейер целиком (папки)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, expected",
    [
        ("отчёт за март", "Otchiot-za-mart"),
        ("Отчёт 2020", "Otchiot_2020-00-00"),
        ("my docs", "My-docs"),
        # Ведущие пробелы/дефисы не должны мешать капитализации с первого прогона:
        ("  отчёт", "Otchiot"),
        ("   фывфыв   фывфыв ---", "Fyvfyv-fyvfyv"),
        ("--- папка", "Papka"),
        ("-файл с пробелом", "Fail-s-probelom"),
        # Ведущий '_' сохраняется и у папок; первая буква после него — заглавная:
        ("_private", "_Private"),
        ("__cache__", "__Cache"),
    ],
)
def test_dir_pipeline(nn, name, expected):
    assert nn.normalize(name, is_dir=True) == expected


# --------------------------------------------------------------------------- #
# Идемпотентность
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, is_dir",
    [
        ("20.05.2020_dump", False),
        ("05.2020", False),
        ("2020", False),
        ("Отчёт 2020", True),
        ("v2 readme.MD", False),
        ("2020-05-05-file.txt", False),
        ("dump-2020-05-05.txt", False),
        # Скобки (круглые и квадратные) и схлопывание дефисов:
        ("Файл (1)", False),
        ("инн (Нового договора нет)", False),
        ("Файл [1]", False),
        ("инн [Нового договора нет]", False),
        ("Резюме - подготовка", False),
        ("file--improved", False),
        # Незакрытые скобки вырезаются за один прогон, дальше стабильно:
        ("Файл (1", False),
        ("инн (Нового договора нет", False),
        # Одиночная цифра рядом с кромочным «мусором»: ведущий ноль ставится за
        # один проход, иначе '5' -> '05' проявлялось бы только на втором прогоне:
        ("том 5!", False),
        ("report 5!", False),
        ("5.", False),
        ("глава 9-", True),
        # Папки с ведущим мусором — капитализация за один прогон:
        ("  отчёт", True),
        ("   фывфыв   фывфыв ---", True),
        ("--- папка", True),
        # Папки с ведущим '_' — стабильны после первого прогона:
        ("_private", True),
        ("__cache__", True),
        # Одиночная цифра-индекс ПЕРЕД датой: ведущий ноль даёт '0X_YYYY-...', но
        # '_' не считается разделителем месяц-год, поэтому готовая дата не ломается
        # на втором прогоне (раньше '03_2021-03-10' -> '2021-03-00_03-10').
        ("3 2021.03.10", False),
        ("5 20.05.2020", False),
        ("7_2020.05.20", False),
        ("@@ café 3 05.2020 ##", False),
        ("___naïve 7 2020___", False),
        ("--- Привет 5 20.05.2020 !!!", True),
        ("  проект №7 2020", True),
    ],
)
def test_idempotent(nn, name, is_dir):
    once = nn.normalize(name, is_dir)
    twice = nn.normalize(once, is_dir)
    assert once == twice


def test_empty_stem_guard(nn):
    # Имя из символов, которые после транслитерации/чистки исчезают -> без изменений.
    assert nn.normalize("@@@.png", is_dir=False) == "@@@.png"


# --------------------------------------------------------------------------- #
# Безопасность: общий барьер enforce_safe_component (один компонент пути).
# Разделители/управляющие -> '-', запрещённые на Windows символы вырезаются.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a/b", "a-b"),                          # '/' -> '-' (один компонент пути)
        ("a\\b", "a-b"),                         # '\' -> '-'
        ("a//b\\\\c", "a-b-c"),                  # цепочки разделителей схлопываются в один '-'
        ("a\x00b\x1fc", "a-b-c"),                # управляющие символы -> '-'
        ('a<b>c:d"e|f?g*h', "abcdefgh"),         # запрещённые на Windows вырезаются
        ("<>:|?*", ""),                          # имя из одного «мусора» -> пусто
        ("clean_name-01", "clean_name-01"),      # безопасное имя не меняется (идемпотентность)
    ],
)
def test_enforce_safe_component(raw, expected):
    assert enforce_safe_component(raw) == expected


@pytest.mark.parametrize("raw", ["a/b", "a\\b", 'x<y>:"|?*', "a\x00b", "<>:|?*"])
def test_enforce_safe_component_idempotent(raw):
    once = enforce_safe_component(raw)
    assert enforce_safe_component(once) == once


# --------------------------------------------------------------------------- #
# FilesystemNormalizer (e2e на временной папке)
# --------------------------------------------------------------------------- #
def _make_tree(root):
    (root / "Отчёт 2020").mkdir()
    (root / "Отчёт 2020" / "20.05.2020_dump").write_text("x")
    (root / "1_file.TXT").write_text("x")
    (root / "v2 readme.MD").write_text("x")
    hidden = root / ".git"
    hidden.mkdir()
    (hidden / "CONFIG").write_text("x")
    (root / ".env").write_text("x")


def test_fs_end_to_end(tmp_path):
    _make_tree(tmp_path)
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)

    assert (tmp_path / "Otchiot_2020-00-00").is_dir()
    assert (tmp_path / "Otchiot_2020-00-00" / "2020-05-20_dump").exists()
    assert (tmp_path / "01_file.TXT").exists()
    assert (tmp_path / "v2-readme.MD").exists()
    # Скрытые не тронуты:
    assert (tmp_path / ".git").is_dir()
    assert (tmp_path / ".git" / "CONFIG").exists()
    assert (tmp_path / ".env").exists()


def test_fs_idempotent_second_run_empty(tmp_path):
    _make_tree(tmp_path)
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)
    renamed, skipped = fs.apply(tmp_path)
    assert renamed == 0


def test_fs_conflict_skipped(tmp_path):
    (tmp_path / "a b.md").write_text("a")  # -> "a-b.md"
    (tmp_path / "a-b.md").write_text("b")  # уже "a-b.md"
    fs = FilesystemNormalizer(build_normalizer())
    renamed, skipped = fs.apply(tmp_path)
    # Переименование в уже занятое имя пропускается, оба файла сохраняются.
    assert renamed == 0
    assert skipped >= 1
    assert (tmp_path / "a b.md").exists()
    assert (tmp_path / "a-b.md").exists()


def test_fs_no_relocation_via_separator(tmp_path):
    # Регресс на критический баг: имя с дробью раньше давало '10-1/2.dat' и os.rename
    # МОЛЧА перемещал файл в соседний каталог '10-1'. Теперь имя остаётся одним
    # компонентом пути, файл нормализуется на месте, ничего не теряется.
    secret = tmp_path / "10½.dat"
    secret.write_text("СЕКРЕТ")
    sibling = tmp_path / "10-1"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("сосед")
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)
    # Данные остались прямо в корне (не уехали внутрь соседнего каталога):
    survivors = [p for p in tmp_path.iterdir() if p.is_file() and p.read_text() == "СЕКРЕТ"]
    assert len(survivors) == 1
    assert "/" not in survivors[0].name and "\\" not in survivors[0].name
    assert (tmp_path / "10½.dat").exists() is False  # переименован


def test_fs_guillemets_renamed_no_data_loss(tmp_path):
    # Регресс на WinError 123: имя с кавычками-«ёлочками» давало '<<'/'>>' через
    # unidecode, и одиночный '<' в середине ломал переименование на Windows.
    # Теперь запрещённые символы вырезаются, файл нормализуется на месте.
    doc = tmp_path / "Заявление ООО «Печоралифтсервис».docx"
    doc.write_text("ДАННЫЕ")
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)
    survivors = [p for p in tmp_path.iterdir() if p.is_file() and p.read_text() == "ДАННЫЕ"]
    assert len(survivors) == 1
    name = survivors[0].name
    assert not any(ch in name for ch in '<>:"|?*')
    assert name == "zaiavlenie-ooo-pechoraliftservis.docx"
    assert doc.exists() is False  # переименован


def test_fs_case_collision_no_data_loss(tmp_path):
    # Регистрозависимая ФС: "File.md" нормализуется в "file.md", где уже есть
    # другой файл. Это конфликт — переименование должно пропускаться, а не
    # перезатирать существующий файл.
    (tmp_path / "File.md").write_text("upper")
    (tmp_path / "file.md").write_text("lower")
    if len(list(tmp_path.iterdir())) < 2:
        pytest.skip("регистронезависимая ФС: файлы-двойники не сосуществуют")
    fs = FilesystemNormalizer(build_normalizer())
    renamed, skipped = fs.apply(tmp_path)
    assert renamed == 0
    assert skipped >= 1
    assert (tmp_path / "File.md").read_text() == "upper"
    assert (tmp_path / "file.md").read_text() == "lower"


# --------------------------------------------------------------------------- #
# FsIgnore — матчинг в стиле .gitignore (движок pathspec), относительно корня
# --------------------------------------------------------------------------- #
def _ign(*lines):
    spec = pathspec.PathSpec.from_lines(_FACTORY, lines)
    incl = any(p.include is False for p in spec.patterns)
    return FsIgnore(spec, incl)


@pytest.mark.parametrize(
    "lines, rel, is_dir, ignored",
    [
        # basename (без '/') совпадает на любой глубине; границы сегмента:
        (["Archive"], "Archive", True, True),
        (["Archive"], "a/b/Archive", True, True),
        (["Archive"], "MyArchive", True, False),
        (["Archive"], "Archive2", True, False),
        # потомки исключённого каталога тоже исключены:
        (["Archive"], "a/Archive/file.txt", False, True),
        # завершающий '/' — только каталог, не одноимённый файл:
        (["build/"], "build", True, True),
        (["build/"], "build", False, False),
        (["build/"], "build/out.o", False, True),
        # '/' в паттерне (ведущий или срединный) — якорь к корню нормализации:
        (["/Archive"], "Archive", True, True),
        (["/Archive"], "a/Archive", True, False),
        (["Home/Components"], "Home/Components", True, True),
        (["Home/Components"], "x/Home/Components", True, False),
        # Префикс './' НЕ поддерживается ('.' — обычный сегмент): не совпадает,
        # тогда как basename 'Foo' и якорь '/Foo' — совпадают:
        (["./Foo"], "Foo", True, False),
        (["Foo"], "Foo", True, True),
        (["/Foo"], "Foo", True, True),
        # '*' — в пределах сегмента; '**' — через сегменты (в т.ч. ноль):
        (["*.bak"], "Docs/notes.bak", False, True),
        (["*.bak"], "Docs/notes.txt", False, False),
        (["Projects/*/build"], "Projects/web/build", True, True),
        (["Projects/*/build"], "Projects/build", True, False),
        (["Projects/**/Data"], "Projects/a/b/Data", True, True),
        (["Projects/**/Data"], "Projects/Data", True, True),
        # СМЕНА КОНТРАКТА: '[abc]' — класс, '?' — один символ (активные метасимволы):
        (["file[12]"], "file1", False, True),
        (["file[12]"], "file3", False, False),
        (["a?b"], "axb", False, True),
        (["a?b"], "ab", False, False),
        # Литеральные скобки/'?' — через экранирование '\':
        ([r"Файл \[1\]"], "Файл [1]", True, True),
        ([r"Файл \[1\]"], "Файл 1", True, False),
        # Регистронезависимость (как git core.ignorecase=true): совпадает в любом регистре:
        (["Archive"], "archive", True, True),
        (["*.txt"], "Notes.TXT", False, True),
        # Комментарии и пустые строки игнорируются:
        (["# комментарий", "", "Archive"], "Archive", True, True),
    ],
)
def test_fsignore_matching(lines, rel, is_dir, ignored):
    assert _ign(*lines).matches(PurePosixPath(rel), is_dir) is ignored


def test_fsignore_empty_never_matches():
    ign = _ign()
    assert ign.matches(PurePosixPath("anything/at/all"), True) is False
    assert ign._incl is False


def test_fsignore_negation_last_match_wins():
    # '!' возвращает убранное; выигрывает последняя совпавшая строка.
    ign = _ign("*.log", "!keep.log")
    assert ign.matches(PurePosixPath("a.log"), False) is True
    assert ign.matches(PurePosixPath("keep.log"), False) is False
    assert ign._incl is True


def test_fsignore_order_reexclude_after_reinclude():
    # Порядок важен: повторное исключение перекрывает более раннее включение.
    ign = _ign("build/", "!build/keep/", "build/keep/secret")
    assert ign.matches(PurePosixPath("build/keep"), True) is False
    assert ign.matches(PurePosixPath("build/keep/secret"), False) is True


# Реальная пользовательская конфигурация: проекты занятий исключены целиком, но
# папки Data внутри них возвращаются на любой глубине (!/Activities/*/Projects/**/Data),
# в т.ч. под исключённым Archive. Проверяем, что затрагиваются ТОЛЬКО папки Data.
_ACTIVITIES_LINES = (
    "Archive",
    "/Activities/*/Projects",
    "!/Activities/*/Projects/**/Data",
    "!/Activities/Video/Projects",
    "/Components",
    "/Resources/Fonts",
)


@pytest.mark.parametrize(
    "rel, ignored",
    [
        # Проект технического занятия и его содержимое исключены...
        ("Activities/Web/Projects", True),
        ("Activities/Web/Projects/Addl", True),
        ("Activities/Web/Projects/Addl/Archive", True),
        ("Activities/Web/Projects/Addl/Archive/example.com", True),
        ("Activities/Web/Projects/Addl/Archive/example.com/Back", True),
        # ...кроме папок Data (на любой глубине, сквозь сегменты, под Archive):
        ("Activities/Web/Projects/Addl/Archive/example.com/Data", False),
        ("Activities/Web/Projects/Addl/Archive/example.com/Data/sub", False),
        ("Activities/Web/Projects/Self/Data", False),
        ("Activities/Web/Projects/Data", False),       # ** = ноль сегментов
        # Сайт-каталог рядом с Archive (НЕ под ним): исключён правилом Projects,
        # т.е. exclude не зависит от вложенности в Archive; его Data всё равно возвращён:
        ("Activities/Web/Projects/Addl/another.com", True),
        ("Activities/Web/Projects/Addl/another.com/Back", True),
        ("Activities/Web/Projects/Addl/another.com/Data", False),
        # Возврат только по ТОЧНОМУ сегменту Data: похожие имена остаются исключены:
        ("Activities/Web/Projects/Addl/Database", True),
        ("Activities/Web/Projects/Addl/DataX", True),
        ("Activities/Web/Projects/Addl/My Data", True),
        # Ресурсы вне Projects не затрагиваются исключением проектов:
        ("Activities/Web/Resources", False),
        # Творческое занятие возвращено целиком (включая не-Data содержимое):
        ("Activities/Video/Projects/Clip/Back", False),
        # Прочие якорные исключения:
        ("Components", True),
        ("Resources/Fonts", True),
    ],
)
def test_fsignore_activities_projects_data(rel, ignored):
    assert _ign(*_ACTIVITIES_LINES).matches(PurePosixPath(rel), True) is ignored


# --------------------------------------------------------------------------- #
# load_fs_ignore — чтение .fs-ignore из выбранного каталога (корня нормализации)
# --------------------------------------------------------------------------- #
def test_load_fs_ignore_missing_file(tmp_path):
    # Нет файла -> None (фильтр выключен).
    assert load_fs_ignore(tmp_path) is None


def test_load_fs_ignore_empty_file(tmp_path):
    # Пустой файл -> FsIgnore без правил (ничего не исключает).
    (tmp_path / ".fs-ignore").write_text("")
    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    assert ign.matches(PurePosixPath("home/user/Archive"), True) is False
    assert ign._incl is False


def test_load_fs_ignore_patterns_comments_negation(tmp_path):
    (tmp_path / ".fs-ignore").write_text(
        "# комментарий\nArchive\n\n*.bak\n!important.bak\n"
    )
    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    assert ign.matches(PurePosixPath("x/Archive/y"), False) is True
    assert ign.matches(PurePosixPath("notes.bak"), False) is True
    assert ign.matches(PurePosixPath("important.bak"), False) is False
    assert ign._incl is True


def test_load_fs_ignore_does_not_modify_file(tmp_path):
    # Файл при сопоставлении не изменяется: содержимое читается как есть.
    content = "Archive\n*.bak\n"
    f = tmp_path / ".fs-ignore"
    f.write_text(content)
    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    ign.matches(PurePosixPath("x/Archive"), True)
    assert f.read_text() == content


def test_load_fs_ignore_utf8_bom(tmp_path):
    # BOM в начале файла не ломает первый паттерн (чтение utf-8-sig).
    (tmp_path / ".fs-ignore").write_text("Archive\n", encoding="utf-8-sig")
    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    assert ign.matches(PurePosixPath("Archive"), True) is True


# --------------------------------------------------------------------------- #
# FilesystemNormalizer + .fs-ignore (e2e на временной папке)
# --------------------------------------------------------------------------- #
def test_fs_ignored_dir_not_renamed_or_descended(tmp_path):
    # Исключённый каталог не переименовывается, внутрь не заходим (содержимое
    # тоже не трогаем), при этом видимый сосед нормализуется.
    archive = tmp_path / "Archive"
    archive.mkdir()
    (archive / "Отчёт 2020").write_text("x")  # имя осталось бы ненормализованным
    (tmp_path / "Отчёт 2020").write_text("y")
    fs = FilesystemNormalizer(build_normalizer(), _ign("Archive"))
    fs.apply(tmp_path)
    # Исключённый каталог и его содержимое не тронуты:
    assert (tmp_path / "Archive").is_dir()
    assert (tmp_path / "Archive" / "Отчёт 2020").exists()
    # Сосед нормализован:
    assert (tmp_path / "otchiot_2020-00-00").exists()


def test_fs_ignored_not_counted(tmp_path):
    # Исключённые объекты не попадают в счётчики renamed/skipped.
    archive = tmp_path / "Archive"
    archive.mkdir()
    (archive / "Файл (1).txt").write_text("x")  # был бы переименован
    (tmp_path / "Файл (1).txt").write_text("y")  # сосед -> переименование
    fs = FilesystemNormalizer(build_normalizer(), _ign("Archive"))
    renamed, skipped = fs.apply(tmp_path)
    assert renamed == 1  # только сосед
    assert skipped == 0
    assert (tmp_path / "fail-01.txt").exists()


def test_fs_ignore_file_by_name(tmp_path):
    # Паттерн может совпасть с именем самого файла.
    (tmp_path / "Keep").write_text("x")  # имя нормализуемо, но исключено
    (tmp_path / "Drop me").write_text("y")
    fs = FilesystemNormalizer(build_normalizer(), _ign("Keep"))
    renamed, skipped = fs.apply(tmp_path)
    assert (tmp_path / "Keep").exists()  # не тронут
    assert (tmp_path / "drop-me").exists()  # сосед нормализован
    assert renamed == 1
    assert skipped == 0


def test_fs_without_ignorer_behaves_as_before(tmp_path):
    # ignorer=None (по умолчанию) -> прежнее поведение.
    (tmp_path / "Archive").mkdir()
    (tmp_path / "Archive" / "Отчёт.txt").write_text("x")
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)
    assert (tmp_path / "Archive" / "otchiot.txt").exists()


def test_fs_ignore_basename_anywhere(tmp_path):
    # Паттерн без '/' (basename) исключает 'notes.txt' в любом месте дерева;
    # прочие файлы нормализуются. Каталоги названы уже нормализованно.
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Deep" / "Inner").mkdir(parents=True)
    (tmp_path / "Docs" / "notes.txt").write_text("1")
    (tmp_path / "Deep" / "Inner" / "notes.txt").write_text("2")
    (tmp_path / "Docs" / "Заметки.txt").write_text("3")
    fs = FilesystemNormalizer(build_normalizer(), _ign("notes.txt"))
    renamed, skipped = fs.apply(tmp_path)
    # notes.txt не тронуты и не посчитаны:
    assert (tmp_path / "Docs" / "notes.txt").exists()
    assert (tmp_path / "Deep" / "Inner" / "notes.txt").exists()
    # Прочий файл нормализован:
    assert (tmp_path / "Docs" / "zametki.txt").exists()
    assert skipped == 0
    assert renamed == 1  # только 'Заметки.txt' менял имя


def test_fs_ignore_anchored_path(tmp_path):
    # Якорный паттерн с '/' ('Sub/notes.txt') действует только в этой цепочке от
    # корня нормализации (не как basename в любом месте).
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Other").mkdir()
    (tmp_path / "Sub" / "notes.txt").write_text("1")
    (tmp_path / "Other" / "notes.txt").write_text("2")
    fs = FilesystemNormalizer(build_normalizer(), _ign("Sub/notes.txt"))
    fs.apply(tmp_path)
    assert (tmp_path / "Sub" / "notes.txt").exists()    # исключён
    # 'Other/notes.txt' не исключён; имя уже нормализовано -> остаётся
    assert (tmp_path / "Other" / "notes.txt").exists()


def test_fs_ignore_case_insensitive(tmp_path):
    # Матчинг регистронезависим (как git core.ignorecase=true): паттерн Archive
    # исключает и Archive, и archive — содержимое обоих не трогаем.
    upper = tmp_path / "Archive"
    lower = tmp_path / "archive"
    upper.mkdir()
    lower.mkdir()
    (upper / "Файл.txt").write_text("x")
    (lower / "Файл.txt").write_text("y")
    fs = FilesystemNormalizer(build_normalizer(), _ign("Archive"))
    fs.apply(tmp_path)
    assert (upper / "Файл.txt").exists()              # исключён
    assert (lower / "Файл.txt").exists()              # тоже исключён (регистр не важен)


def test_fs_ignore_idempotent_across_runs_with_capitalized_parent(tmp_path):
    # Кросс-прогонная идемпотентность фильтра: вышележащие каталоги (box/inner) не
    # совпадают с паттерном и капитализируются CaseRule (box -> Box, inner -> Inner).
    # На втором прогоне якорь /box/inner/*.bak должен совпасть с Box/Inner/... за
    # счёт регистронезависимости — иначе исключённый файл нормализуется (баг).
    inner = tmp_path / "box" / "inner"
    inner.mkdir(parents=True)
    (inner / "Секрет.bak").write_text("x")           # был бы нормализован -> sekret.bak
    (tmp_path / ".fs-ignore").write_text("/box/inner/*.bak\n")

    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    FilesystemNormalizer(build_normalizer(), ign).apply(tmp_path)
    # После первого прогона родители капитализированы, файл исключён и не тронут:
    assert (tmp_path / "Box" / "Inner" / "Секрет.bak").exists()

    # Второй прогон поверх результата (фильтр перечитывается из того же .fs-ignore):
    ign2 = load_fs_ignore(tmp_path)
    assert ign2 is not None
    renamed, _ = FilesystemNormalizer(build_normalizer(), ign2).apply(tmp_path)
    assert renamed == 0                              # ничего не меняется
    assert (tmp_path / "Box" / "Inner" / "Секрет.bak").exists()
    assert not (tmp_path / "Box" / "Inner" / "sekret.bak").exists()


def test_fs_negation_reincludes_file(tmp_path):
    # '!' возвращает к нормализации убранное; порядок строк важен.
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs" / "Черновик.tmp").write_text("x")  # остаётся исключён
    (tmp_path / "Docs" / "Важное.keep").write_text("y")    # возвращён
    ign = _ign("Docs/*", "!Docs/*.keep")
    fs = FilesystemNormalizer(build_normalizer(), ign)
    fs.apply(tmp_path)
    assert (tmp_path / "Docs" / "Черновик.tmp").exists()   # исключён -> не тронут
    assert (tmp_path / "Docs" / "vazhnoe.keep").exists()   # включён -> нормализован


def test_fs_hidden_not_reincluded_by_negation(tmp_path):
    # Скрытые (имя на '.') отсекаются `_hidden` ДО фильтра и внутрь не заходим,
    # поэтому правило-'!' их не возвращает (даже при включённом probe, _incl=True).
    (tmp_path / ".keep").write_text("x")            # скрытый файл
    hidden = tmp_path / ".cfg"
    hidden.mkdir()
    (hidden / "Отчёт 2020").write_text("y")          # внутрь скрытой папки не заходим
    ign = _ign("Archive", "!*.keep", "!.cfg/**")    # '!' -> _incl=True (probe)
    assert ign._incl is True
    fs = FilesystemNormalizer(build_normalizer(), ign)
    renamed, skipped = fs.apply(tmp_path)
    assert (tmp_path / ".keep").exists()             # скрытый файл не тронут
    assert (hidden / "Отчёт 2020").exists()          # содержимое скрытой папки не тронуто
    assert renamed == 0
    assert skipped == 0


def test_fs_negation_probe_descends_ignored_dir(tmp_path):
    # При наличии '!' обход не обрезает исключённые каталоги (probe): потомок
    # внутри Archive достижим и нормализуется, сам Archive остаётся исключён.
    data = tmp_path / "Archive" / "nested" / "Data"
    (data / "Папка").mkdir(parents=True)
    ign = _ign("Archive", "!**/Data/**")
    assert ign._incl is True
    fs = FilesystemNormalizer(build_normalizer(), ign)
    fs.apply(tmp_path)
    assert (data / "Papka").is_dir()       # возвращённый потомок нормализован
    assert (tmp_path / "Archive").is_dir()  # промежуточный Archive не тронут


def test_fs_activities_projects_data_reincluded(tmp_path):
    # Реальный кейс: !/Activities/*/Projects/**/Data возвращает к нормализации
    # ТОЛЬКО папки Data внутри проектов (на любой глубине, под исключённым
    # Archive), а остальное содержимое проекта (Back, промежуточные каталоги,
    # соседний с Archive каталог прямо в Addl) остаётся нетронутым и не попадает
    # в счётчики.
    addl = tmp_path / "Activities" / "Web" / "Projects" / "Addl"
    base = addl / "Archive" / "example.com"
    back = base / "Back"
    data = base / "Data"
    back.mkdir(parents=True)
    data.mkdir(parents=True)
    (back / "Старый бэкап").write_text("x")        # под Projects, не Data -> исключён
    (data / "Выгрузка 2021").write_text("y")        # внутри Data -> возвращён
    # Сайт-каталог рядом с Archive (прямо в проекте, НЕ под Archive): exclude от
    # правила Projects не зависит от вложенности в Archive. Его Back исключён,
    # а Data возвращена так же, как у example.com.
    sib = addl / "another.com"
    sib_back = sib / "Back"
    sib_data = sib / "Data"
    sib_back.mkdir(parents=True)
    sib_data.mkdir(parents=True)
    (sib_back / "Прошлый отчёт").write_text("z")   # под Projects, не Data -> исключён
    (sib_data / "Выгрузка 2022").write_text("w")    # внутри Data -> возвращён
    # Сайт прямо в Addl вообще без Data: всё содержимое остаётся нетронутым.
    nodata = addl / "example.com"
    nodata.mkdir(parents=True)
    (nodata / "Резервная копия").write_text("r")   # под Projects, не Data -> исключён
    (tmp_path / ".fs-ignore").write_text(
        "Archive\n/Activities/*/Projects\n!/Activities/*/Projects/**/Data\n"
    )

    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    renamed, skipped = FilesystemNormalizer(build_normalizer(), ign).apply(tmp_path)

    # Содержимое Data нормализовано (дата -> ISO) в обоих сайтах:
    assert (data / "vygruzka_2021-00-00").exists()
    assert (sib_data / "vygruzka_2022-00-00").exists()
    # Соседний Back и промежуточные исключённые каталоги не тронуты:
    assert (back / "Старый бэкап").exists()
    assert back.is_dir()
    assert base.is_dir()                             # example.com не переименован
    # Сайт-каталог рядом с Archive и его Back тоже не тронуты:
    assert (sib_back / "Прошлый отчёт").exists()
    assert sib.is_dir()                              # another.com не переименован
    assert sib_back.is_dir()
    # Сайт без Data полностью не тронут:
    assert (nodata / "Резервная копия").exists()
    assert nodata.is_dir()
    assert (tmp_path / "Activities" / "Web" / "Projects").is_dir()
    # Посчитаны только два возвращённых файла Data; исключённое в счётчики не попало:
    assert renamed == 2
    assert skipped == 0


def test_fs_ignore_bracket_class_active(tmp_path):
    # СМЕНА КОНТРАКТА: '[12]' теперь КЛАСС символов (а не литерал). 'отчёт[12]'
    # исключает 'отчёт1', но не 'отчёт3' (тот нормализуется).
    a = tmp_path / "отчёт1"
    b = tmp_path / "отчёт3"
    a.mkdir()
    b.mkdir()
    (a / "вложение").write_text("x")
    (b / "вложение").write_text("y")
    fs = FilesystemNormalizer(build_normalizer(), _ign("отчёт[12]"))
    fs.apply(tmp_path)
    assert (a / "вложение").exists()  # исключён классом -> не тронут
    survivors = [p for p in tmp_path.rglob("*") if p.is_file() and p.read_text() == "y"]
    assert len(survivors) == 1
    assert survivors[0].name == "vlozhenie"  # 'отчёт3' не исключён -> нормализован


def test_fs_ignore_literal_bracket_escaped(tmp_path):
    # Литеральные скобки экранируются '\': 'Файл \[1\]' исключает ровно такой
    # каталог, а 'Файл 2' — нет (нормализуется).
    a = tmp_path / "Файл [1]"
    b = tmp_path / "Файл 2"
    a.mkdir()
    b.mkdir()
    (a / "вложение").write_text("x")
    (b / "вложение").write_text("y")
    fs = FilesystemNormalizer(build_normalizer(), _ign(r"Файл \[1\]"))
    fs.apply(tmp_path)
    assert (a / "вложение").exists()  # исключён литерально -> не тронут
    survivors = [p for p in tmp_path.rglob("*") if p.is_file() and p.read_text() == "y"]
    assert len(survivors) == 1
    assert survivors[0].name == "vlozhenie"


def test_fs_ignore_read_from_normalized_dir(tmp_path):
    # .fs-ignore лежит ВНУТРИ нормализуемого каталога и читается из него
    # (load_fs_ignore(root)); якорь '/' отсчитывается от этой же папки, а сам файл
    # .fs-ignore (имя на '.') обходом пропускается и не переименовывается.
    (tmp_path / ".fs-ignore").write_text("/Sub\n")
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Other").mkdir()
    (tmp_path / "Sub" / "Отчёт 2020").write_text("x")    # исключён якорем /Sub
    (tmp_path / "Other" / "Отчёт 2020").write_text("y")  # сосед нормализуется
    ign = load_fs_ignore(tmp_path)
    assert ign is not None
    fs = FilesystemNormalizer(build_normalizer(), ign)
    renamed, skipped = fs.apply(tmp_path)
    assert (tmp_path / "Sub" / "Отчёт 2020").exists()            # исключён
    assert (tmp_path / "Other" / "otchiot_2020-00-00").exists()  # нормализован
    assert (tmp_path / ".fs-ignore").is_file()                   # сам файл уцелел
    # Посчитан только переименованный сосед: .fs-ignore не попал в счётчики.
    assert renamed == 1
    assert skipped == 0
