import shutil
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from normalizer import (
    BracketsRule,
    CaseRule,
    DateRule,
    FilesystemNormalizer,
    LeadingZeroRule,
    PathExcluder,
    PathIncluder,
    SpaceToDashRule,
    TransliterationRule,
    TrimEdgeRule,
    build_normalizer,
    load_excluder,
    load_includer,
)
from normalizer.exclude import _canon, _seg_glob


@pytest.fixture()
def nn():
    return build_normalizer()


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
        ("2020.05", "2020-05-00"),
        ("2020", "2020-00-00"),
        ("-file_01-.png", "file_01.png"),
        ("файл 1.JPG", "fail-01.JPG"),
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


def test_brackets_rule_exported():
    # Публичное API не должно разойтись: новое правило экспортируется из пакета.
    import normalizer

    assert "BracketsRule" in normalizer.__all__
    assert normalizer.BracketsRule is BracketsRule


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
        # Папки с ведущим мусором — капитализация за один прогон:
        ("  отчёт", True),
        ("   фывфыв   фывфыв ---", True),
        ("--- папка", True),
        # Папки с ведущим '_' — стабильны после первого прогона:
        ("_private", True),
        ("__cache__", True),
    ],
)
def test_idempotent(nn, name, is_dir):
    once = nn.normalize(name, is_dir)
    twice = nn.normalize(once, is_dir)
    assert once == twice


# --------------------------------------------------------------------------- #
# DateRule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("20.05.2020", "2020-05-20"),
        ("2020.05.20", "2020-05-20"),
        ("2020/05/20", "2020-05-20"),
        ("1.2.2020", "2020-02-01"),
        # Соседние разделители вокруг даты -> '_':
        ("2020-05-05-file", "2020-05-05_file"),
        ("dump-2020-05-05", "dump_2020-05-05"),
        ("2020-05-05.file", "2020-05-05_file"),
        ("dump 20.05.2020", "dump_2020-05-20"),
        ("dump_2020-05-05", "dump_2020-05-05"),
        ("2020-05-00-file", "2020-05-00_file"),
        ("year-2020-end", "year_2020-00-00_end"),
        ("05.2020", "2020-05-00"),
        ("2020.05", "2020-05-00"),
        ("1.2020", "2020-01-00"),
        ("2020", "2020-00-00"),
        # Невалидные/нерелевантные — без изменений:
        ("31.02.2020", "31.02.2020"),
        ("13.2020", "13.2020"),
        ("1080", "1080"),
        ("12345", "12345"),
        # Цифры, склеенные с буквами, — НЕ дата (отдельный токен обязателен):
        ("model2020", "model2020"),
        ("version2021", "version2021"),
        ("abc1999x", "abc1999x"),
        ("build2024release", "build2024release"),
        ("2020s", "2020s"),
        # Разделители-токены (_) сохраняют распознавание года:
        ("file_2020", "file_2020-00-00"),
        # Уже нормализованные — без изменений:
        ("2020-05-20", "2020-05-20"),
        ("2020-05-00", "2020-05-00"),
        ("2020-00-00", "2020-00-00"),
    ],
)
def test_date_rule(raw, expected):
    assert DateRule().apply(raw, is_dir=False) == expected


# --------------------------------------------------------------------------- #
# LeadingZeroRule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1_file", "01_file"),
        ("file_5", "file_05"),
        ("a 7 b", "a 07 b"),
        ("1.5", "1.5"),        # дробь не трогаем
        ("v2", "v2"),          # буквенный префикс
        ("2x", "2x"),          # буквенный суффикс
        ("file10", "file10"),  # двузначное / слитно с буквами
        ("12", "12"),          # уже двузначное
    ],
)
def test_leading_zero(raw, expected):
    assert LeadingZeroRule().apply(raw, is_dir=False) == expected


# --------------------------------------------------------------------------- #
# BracketsRule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        # Число/дата (без букв) -> скобки убираются (круглые и квадратные):
        ("file (1)", "file 1"),
        ("file (12)", "file 12"),
        ("(2021.03.10)", "2021.03.10"),
        ("file [1]", "file 1"),
        ("[2021.03.10]", "2021.03.10"),
        # Текст (буквы) -> скобки сохраняются:
        ("inn (kopiia)", "inn (kopiia)"),
        ("a (b1c)", "a (b1c)"),
        ("inn [chernovik]", "inn [chernovik]"),
        # Пустые скобки убираются, без скобок — без изменений:
        ("x ()", "x "),
        ("x []", "x "),
        ("plain", "plain"),
        # Непарные/несовпадающие скобки вырезаются (валидность контента не важна):
        ("file (1", "file 1"),
        ("file 1)", "file 1"),
        ("file (1]", "file 1"),
        ("file [1)", "file 1"),
        ("inn (kopiia", "inn kopiia"),
        ("inn kopiia)", "inn kopiia"),
        ("a (1) b (2", "a 1 b 2"),
        ("((1))", "1"),  # вложенные пары схлопываются
    ],
)
def test_brackets_rule(raw, expected):
    assert BracketsRule().apply(raw, is_dir=False) == expected


# --------------------------------------------------------------------------- #
# SpaceToDashRule — схлопывание пробелов и дефисов
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        # Прогон с пробелом -> одно тире:
        ("a b", "a-b"),
        ("a - b", "a-b"),
        ("a -- b", "a-b"),
        ("a   b", "a-b"),
        # Дефисы без пробелов сохраняются (даты не множатся, идемпотентно):
        ("a---b", "a---b"),
        ("file--improved", "file--improved"),
        ("2020-05-20", "2020-05-20"),
    ],
)
def test_space_to_dash(raw, expected):
    assert SpaceToDashRule().apply(raw, is_dir=False) == expected


# --------------------------------------------------------------------------- #
# CaseRule / TrimEdgeRule
# --------------------------------------------------------------------------- #
def test_case_rule():
    assert CaseRule().apply("report", is_dir=True) == "Report"
    assert CaseRule().apply("Report", is_dir=False) == "report"
    # README в верхнем регистре сохраняется как есть:
    assert CaseRule().apply("README", is_dir=False) == "README"
    # Сохраняется только точное совпадение: иной регистр приводится к нижнему.
    assert CaseRule().apply("Readme", is_dir=False) == "readme"
    # У папок ведущий '_' сохраняется, капитализируется первая буква после него:
    assert CaseRule().apply("_private", is_dir=True) == "_Private"
    assert CaseRule().apply("__cache", is_dir=True) == "__Cache"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("README", "README"),
        ("README.md", "README.md"),
        ("README.TXT", "README.TXT"),
    ],
)
def test_readme_preserved(nn, name, expected):
    assert nn.normalize(name, is_dir=False) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("-file-", "file"),
        ("__name__", "__name"),  # ведущие '_' у файлов сохраняются
        ("_private", "_private"),
        ("--_file", "file"),  # '_' не в самом начале -> обрезается вместе с мусором
        ("2020-05-00", "2020-05-00"),  # цифры плейсхолдера сохраняются
        ("2020-00-00", "2020-00-00"),
        # Парная скобка на краю сохраняется (круглая и квадратная):
        ("inn-(novogo-net)", "inn-(novogo-net)"),
        ("(kopiia)-fail", "(kopiia)-fail"),
        ("inn-[novogo-net]", "inn-[novogo-net]"),
        ("[kopiia]-fail", "[kopiia]-fail"),
        # Непарная скобка по-прежнему срезается как мусор:
        ("abc)", "abc"),
        ("(abc", "abc"),
        ("abc]", "abc"),
        ("[abc", "abc"),
    ],
)
def test_trim_edge(raw, expected):
    assert TrimEdgeRule().apply(raw, is_dir=False) == expected


def test_trim_edge_dir_keeps_leading_underscore():
    # Ведущий '_' сохраняется и у папок (как у файлов); хвостовой мусор обрезается.
    assert TrimEdgeRule().apply("__name__", is_dir=True) == "__name"


def test_empty_stem_guard(nn):
    # Имя из символов, которые после транслитерации/чистки исчезают -> без изменений.
    assert nn.normalize("@@@.png", is_dir=False) == "@@@.png"


# --------------------------------------------------------------------------- #
# Безопасность: транслитерация не должна вносить разделители пути / управляющие
# символы. Иначе os.rename истолковал бы их как путь и переместил/потерял объект.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "½", "¼", "¾", "10½", "½ доля", "naïve½", "файл ½",
        "∖обратная", "↘стрелка", "＼fullwidth",  # дают '\' через unidecode
        "пример\u2028строка", "две\u2029строки",  # дают '\n' через unidecode
    ],
)
def test_no_path_separators_introduced(nn, raw):
    for is_dir in (False, True):
        out = nn.normalize(raw if is_dir else raw + ".txt", is_dir=is_dir)
        assert "/" not in out
        assert "\\" not in out
        assert not any(ord(c) < 0x20 for c in out)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("½.txt", "01-02.txt"),
        ("10½.dat", "10-01-02.dat"),
        ("½ доля.txt", "01-02-dolia.txt"),
    ],
)
def test_fraction_pipeline(nn, name, expected):
    assert nn.normalize(name, is_dir=False) == expected


def test_transliteration_rule_strips_separators():
    # Прямой контракт правила: '/' и '\' из unidecode заменяются на '-'.
    assert "/" not in TransliterationRule().apply("½", is_dir=False)
    assert "\\" not in TransliterationRule().apply("∖", is_dir=False)


# --------------------------------------------------------------------------- #
# Мягкий/твёрдый знак: unidecode превращает 'ь'/'ъ' в апостроф — мы его убираем.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, expected",
    [
        ("Письмо", "pismo"),
        ("автомобиль", "avtomobil"),
        ("секретарь", "sekretar"),
        ("подъезд", "podezd"),
        ("Объявление", "obiavlenie"),
    ],
)
def test_soft_hard_sign_removed(nn, name, expected):
    assert nn.normalize(name, is_dir=False) == expected
    # Апостроф не должен появляться в имени:
    assert "'" not in nn.normalize(name, is_dir=False)


def test_ascii_apostrophe_preserved(nn):
    # ASCII-апостроф во ВХОДНОМ имени не трогаем — убираем только 'ь'/'ъ'.
    assert nn.normalize("O'Brien.txt", is_dir=False) == "o'brien.txt"


# --------------------------------------------------------------------------- #
# Запрещённые на Windows символы (< > : " | ? *). Транслитерация порождает их из
# типографики ('«'->'<<', '»'->'>>', '“'/'”'->'"'); их нужно вырезать, иначе
# одиночный '<' в середине имени ломает os.rename на Windows (WinError 123).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "«ёлочки»", "ООО «Печоралифтсервис»", "“кавычки”", "„нижние“",
        "файл «с» кавычками", "‹одинарные›",
    ],
)
def test_no_windows_forbidden_introduced(nn, raw):
    for is_dir in (False, True):
        out = nn.normalize(raw if is_dir else raw + ".txt", is_dir=is_dir)
        assert not any(ch in out for ch in '<>:"|?*')


@pytest.mark.parametrize(
    "name, expected",
    [
        ("«Печоралифтсервис».txt", "pechoraliftservis.txt"),
        ("ООО «Рога и Копыта».doc", "ooo-roga-i-kopyta.doc"),
    ],
)
def test_guillemets_pipeline(nn, name, expected):
    assert nn.normalize(name, is_dir=False) == expected


def test_transliteration_rule_removes_windows_forbidden():
    # Прямой контракт правила: '<<'/'>>' из unidecode('«»') вырезаются.
    out = TransliterationRule().apply("«тест»", is_dir=False)
    assert "<" not in out and ">" not in out


@pytest.mark.parametrize("raw", ["½", "10½", "½ доля", "naïve½"])
def test_fraction_idempotent(nn, raw):
    once = nn.normalize(raw, is_dir=False)
    assert nn.normalize(once, is_dir=False) == once


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
# PathExcluder — сопоставление по сегментам пути
# --------------------------------------------------------------------------- #
def _exc(*entries):
    return PathExcluder([_canon(e) for e in entries])


def _p(text):
    return PurePosixPath(text)


@pytest.mark.parametrize(
    "entry, path, excluded",
    [
        # Совпадение по границам сегмента (а не сырой подстрокой):
        ("Archive", "/home/user/Archive/file.txt", True),
        ("Archive", "/home/user/MyArchive/file.txt", False),
        ("Archive", "/home/user/Archive2/file.txt", False),
        # Регистронезависимость (кросс-платформенно):
        ("archive", "/home/user/Archive/x", True),
        ("ARCHIVE", "/home/user/archive/x", True),
        # Нормализация разделителей: '\\' эквивалентен '/':
        ("Programs\\Composer", "/opt/Programs/Composer/bin", True),
        ("Programs/Composer", "/opt/Programs/Composer/bin", True),
        # Многосегментный паттерн — непрерывная цепочка:
        ("Home/Components", "/home/achieffment/Home/Components/fs", True),
        ("Home/Components", "/home/achieffment/Home/Other/Components/fs", False),
        # Буква диска -> токен: совпадает на Windows и в WSL (один диск):
        ("D:\\Programs", "D:\\Programs\\app", True),
        ("D:\\Programs", "/mnt/d/Programs/app", True),
        # Разные диски НЕ путаются:
        ("E:\\Programs", "D:\\Programs\\app", False),
        ("E:\\Programs", "/mnt/d/Programs/app", False),
        # Несовпадающий префикс не исключает:
        ("Resources/Fonts", "/x/Resources/Other/Fonts", False),
    ],
)
def test_path_excluder_matching(entry, path, excluded):
    p = PureWindowsPath(path) if "\\" in path else PurePosixPath(path)
    assert _exc(entry).is_excluded(p) is excluded


def test_path_excluder_empty_never_excludes():
    exc = PathExcluder([])
    assert exc.is_excluded(_p("/anything/at/all")) is False


# --------------------------------------------------------------------------- #
# _canon — устойчивость к слешам (ведущие/завершающие/кратные)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Home/Components", ("home", "components")),
        ("Home/Components/", ("home", "components")),
        ("/Home/Components", ("home", "components")),
        ("Home//Components", ("home", "components")),
        ("///Home///Components///", ("home", "components")),
        ("  Home/Components  ", ("home", "components")),
        ("/home//mnt///disk", ("home", "mnt", "disk")),
        ("Home\\Components\\", ("home", "components")),
        ("", ()),
        ("///", ()),
    ],
)
def test_canon_slash_robustness(text, expected):
    assert _canon(text) == expected


def test_canon_slash_forms_equal():
    # Форма со слешем на конце/в начале и без — один и тот же канон.
    assert _canon("Home/Components/") == _canon("Home/Components")
    assert _canon("/Home/Components") == _canon("Home/Components")
    assert _canon("Home//Components") == _canon("Home/Components")


@pytest.mark.parametrize(
    "entry",
    ["Resources/Fonts", "Resources/Fonts/", "/Resources/Fonts", "Resources//Fonts"],
)
def test_is_excluded_dirty_pattern_forms(entry):
    # «Грязные» формы паттерна дают одинаковый результат сопоставления.
    assert _exc(entry).is_excluded(_p("/x/Resources/Fonts/y")) is True
    assert _exc(entry).is_excluded(_p("/x/Resources/Other/Fonts")) is False


# --------------------------------------------------------------------------- #
# Кросс-платформенная матрица: Windows / WSL / Linux / Mac
# Одна запись ведёт себя одинаково, в т.ч. при переносе Windows<->WSL.
# --------------------------------------------------------------------------- #
def _path(text):
    # Windows-форму распознаём по '\\' или префиксу диска 'X:'.
    if "\\" in text or (len(text) >= 2 and text[1] == ":"):
        return PureWindowsPath(text)
    return PurePosixPath(text)


@pytest.mark.parametrize(
    "entry, path, excluded",
    [
        # Один диск, Windows<->WSL в обе стороны:
        ("D:\\Programs", "D:\\Programs\\app", True),
        ("D:\\Programs", "/mnt/d/Programs/app", True),
        ("/mnt/d/Programs", "D:\\Programs\\app", True),
        ("/mnt/d/Programs", "/mnt/d/Programs/app", True),
        ("mnt/d/Programs", "D:\\Programs\\app", True),
        ("D:/Programs", "/mnt/d/Programs/app", True),
        # Разные диски не путаются:
        ("E:\\Programs", "D:\\Programs\\app", False),
        ("/mnt/e/Programs", "D:\\Programs\\app", False),
        # Относительный паттерн без диска совпадает с любым диском:
        ("Programs", "D:\\Programs\\app", True),
        ("Programs", "/mnt/c/Programs/app", True),
        # Linux/Mac:
        ("Home/Components", "/home/u/Home/Components/x", True),
        ("Home/Components", "/Users/u/Home/Components/x", True),
        # UNC из Windows к файлам WSL (containment):
        ("/home/achieffment/Home", "\\\\wsl.localhost\\Ubuntu\\home\\achieffment\\Home\\x", True),
        # '/mnt/wsl' — не диск (сегмент не одиночная буква):
        ("/mnt/wsl/Programs", "/mnt/wsl/Programs/app", True),
        ("D:\\Programs", "/mnt/wsl/Programs/app", False),
    ],
)
def test_crossplatform_matrix(entry, path, excluded):
    assert _exc(entry).is_excluded(_path(path)) is excluded


def test_crossplatform_drive_token_symmetry():
    # D:\, D:/, /mnt/d, mnt/d -> один канон [d, programs].
    forms = ["D:\\Programs", "D:/Programs", "/mnt/d/Programs", "mnt/d/Programs"]
    canons = {_canon(f) for f in forms}
    assert canons == {("d", "programs")}


# --------------------------------------------------------------------------- #
# load_excluder — чтение exclude.txt из корня проекта
# --------------------------------------------------------------------------- #
def test_load_excluder_missing_file(tmp_path):
    # Нет файла -> None (проверки выключены).
    assert load_excluder(tmp_path) is None


def test_load_excluder_empty_file(tmp_path):
    # Пустой файл -> excluder без паттернов (ничего не исключает).
    (tmp_path / "exclude.txt").write_text("")
    exc = load_excluder(tmp_path)
    assert exc is not None
    assert exc.is_excluded(_p("/home/user/Archive")) is False


def test_load_excluder_patterns_and_blank_lines(tmp_path):
    (tmp_path / "exclude.txt").write_text(
        "Archive\n\n  Resources/Fonts  \nD:\\Programs\n\n"
    )
    exc = load_excluder(tmp_path)
    assert exc is not None
    assert exc.is_excluded(_p("/x/Archive/y")) is True
    assert exc.is_excluded(_p("/x/Resources/Fonts/y")) is True
    assert exc.is_excluded(_p("/mnt/d/Programs/y")) is True
    assert exc.is_excluded(_p("/x/Other/y")) is False


def test_load_excluder_does_not_modify_file(tmp_path):
    # Файл при сопоставлении не изменяется: содержимое читается как есть.
    content = "D:\\Programs\nArchive\n"
    f = tmp_path / "exclude.txt"
    f.write_text(content)
    exc = load_excluder(tmp_path)
    assert exc is not None
    exc.is_excluded(_p("/x/Archive"))
    assert f.read_text() == content


# --------------------------------------------------------------------------- #
# FilesystemNormalizer + исключения (e2e на временной папке)
# --------------------------------------------------------------------------- #
def test_fs_excluded_dir_not_renamed_or_descended(tmp_path):
    # Исключённый каталог не переименовывается, внутрь не заходим (содержимое
    # тоже не трогаем), при этом видимый сосед нормализуется.
    archive = tmp_path / "Archive"
    archive.mkdir()
    (archive / "Отчёт 2020").write_text("x")  # имя осталось бы ненормализованным
    (tmp_path / "Отчёт 2020").write_text("y")
    exc = _exc("Archive")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    fs.apply(tmp_path)
    # Исключённый каталог и его содержимое не тронуты:
    assert (tmp_path / "Archive").is_dir()
    assert (tmp_path / "Archive" / "Отчёт 2020").exists()
    # Сосед нормализован:
    assert (tmp_path / "otchiot_2020-00-00").exists()


def test_fs_excluded_not_counted(tmp_path):
    # Исключённые объекты не попадают в счётчики renamed/skipped (req. 8).
    archive = tmp_path / "Archive"
    archive.mkdir()
    (archive / "Файл (1).txt").write_text("x")  # был бы переименован
    (tmp_path / "Файл (1).txt").write_text("y")  # сосед -> переименование
    exc = _exc("Archive")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    renamed, skipped = fs.apply(tmp_path)
    assert renamed == 1  # только сосед
    assert skipped == 0
    assert (tmp_path / "fail-01.txt").exists()


def test_fs_excluded_file_by_segment(tmp_path):
    # Паттерн может совпасть с именем самого файла (последний сегмент пути).
    (tmp_path / "Keep").write_text("x")  # имя нормализуемо, но исключено
    (tmp_path / "Drop me").write_text("y")
    exc = _exc("Keep")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    renamed, skipped = fs.apply(tmp_path)
    assert (tmp_path / "Keep").exists()  # не тронут
    assert (tmp_path / "drop-me").exists()  # сосед нормализован
    assert renamed == 1
    assert skipped == 0


def test_fs_without_excluder_behaves_as_before(tmp_path):
    # excluder=None (по умолчанию) -> прежнее поведение.
    (tmp_path / "Archive").mkdir()
    (tmp_path / "Archive" / "Отчёт.txt").write_text("x")
    fs = FilesystemNormalizer(build_normalizer())
    fs.apply(tmp_path)
    assert (tmp_path / "Archive" / "otchiot.txt").exists()


def test_fs_exclude_file_by_name_anywhere(tmp_path):
    # Паттерн-имя 'notes.txt' исключает такой файл в любом месте дерева; файлы с
    # другими именами (включая близкие) нормализуются. Каталоги названы уже
    # нормализованно ('Docs'/'Deep'/'Inner'), чтобы проверять именно файлы.
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Deep" / "Inner").mkdir(parents=True)
    (tmp_path / "Docs" / "notes.txt").write_text("1")
    (tmp_path / "Deep" / "Inner" / "notes.txt").write_text("2")
    (tmp_path / "Docs" / "mynotes.txt").write_text("3")
    (tmp_path / "Docs" / "notes.txt.bak").write_text("4")
    (tmp_path / "Docs" / "Заметки.txt").write_text("5")
    exc = _exc("notes.txt")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    renamed, skipped = fs.apply(tmp_path)
    # notes.txt не тронуты и не посчитаны:
    assert (tmp_path / "Docs" / "notes.txt").exists()
    assert (tmp_path / "Deep" / "Inner" / "notes.txt").exists()
    # Прочие файлы нормализованы (mynotes.txt/notes.txt.bak уже в нижнем регистре):
    assert (tmp_path / "Docs" / "zametki.txt").exists()
    assert skipped == 0
    assert renamed == 1  # только 'Заметки.txt' менял имя


def test_fs_exclude_file_specific_path(tmp_path):
    # Уточнённый паттерн 'Sub/notes.txt' исключает только файл в этой цепочке.
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Other").mkdir()
    (tmp_path / "Sub" / "notes.txt").write_text("1")
    (tmp_path / "Other" / "notes.txt").write_text("2")
    exc = _exc("Sub/notes.txt")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    fs.apply(tmp_path)
    assert (tmp_path / "Sub" / "notes.txt").exists()  # исключён
    # 'Other/notes.txt' не исключён; имя уже нормализовано, но папка Other -> остаётся
    assert (tmp_path / "Other" / "notes.txt").exists()


def test_fs_real_scenario_projects_components_archive(tmp_path):
    # Сценарий пользователя: нормализуем .../Home; исключаем конкретные Projects,
    # Components и любой Archive; неуказанные каталоги нормализуются.
    home = tmp_path / "Home"
    (home / "Activities" / "3D" / "Projects").mkdir(parents=True)
    (home / "Activities" / "Web" / "Projects").mkdir(parents=True)
    (home / "Activities" / "Misc" / "Archive").mkdir(parents=True)
    (home / "Activities" / "Java" / "src").mkdir(parents=True)
    (home / "Components").mkdir()
    # Внутри исключённых — «грязные» имена, которые НЕ должны меняться:
    (home / "Activities" / "3D" / "Projects" / "Мой проект").write_text("x")
    (home / "Activities" / "Misc" / "Archive" / "Старьё 2019").write_text("x")
    (home / "Components" / "Кнопка").write_text("x")
    # В неисключённом src — имя, которое ДОЛЖНО нормализоваться:
    (home / "Activities" / "Java" / "src" / "Главный Класс").write_text("x")

    exc = _exc(
        "/mnt/disk/DevOps",
        "Archive",
        "Home/Activities/3D/Projects",
        "Home/Activities/Web/Projects/",  # форма со слешем на конце
        "Home/Components",
    )
    fs = FilesystemNormalizer(build_normalizer(), exc)
    fs.apply(home)

    # Исключённое не тронуто:
    assert (home / "Activities" / "3D" / "Projects" / "Мой проект").exists()
    assert (home / "Activities" / "Misc" / "Archive" / "Старьё 2019").exists()
    assert (home / "Components" / "Кнопка").exists()
    # Каталоги-исключения сохранили исходные имена:
    assert (home / "Activities" / "3D" / "Projects").is_dir()
    assert (home / "Activities" / "Web" / "Projects").is_dir()
    assert (home / "Components").is_dir()
    # Неуказанный src нормализован (папка -> 'Src'), как и файл внутри него:
    assert (home / "Activities" / "Java" / "Src" / "glavnyi-klass").exists()
    # Родители (Activities, языки) целиком не исключались — нормализуются:
    assert (home / "Activities" / "Java" / "Src").is_dir()


# --- include: glob-матчер (юнит) ---


def _inc(*entries):
    return PathIncluder([_canon(e) for e in entries])


def test_glob_double_star_floats():
    inc = _inc("Activities/Web/Projects/**/Data")
    # '**' поглощает промежуточные сегменты:
    assert inc.matches(PurePosixPath("/h/Activities/Web/Projects/Addl/Archive/Data"))
    # поддерево re-included объекта тоже матчится (плавающий конец):
    assert inc.matches(PurePosixPath("/h/Activities/Web/Projects/X/Data/inner"))
    # '**' поглощает ноль сегментов:
    assert inc.matches(PurePosixPath("/h/Activities/Web/Projects/Data"))


def test_glob_single_star_one_segment():
    inc = _inc("a/*/b")
    assert inc.matches(PurePosixPath("/root/a/x/b"))
    # ровно один сегмент — не ноль:
    assert not inc.matches(PurePosixPath("/root/a/b"))
    # и не два:
    assert not inc.matches(PurePosixPath("/root/a/x/y/b"))


def test_glob_zero_segments_double_star_middle():
    inc = _inc("a/**/b")
    assert inc.matches(PurePosixPath("/root/a/b"))  # ноль сегментов между


def test_glob_literal_backwards_compatible():
    # Без '*'/'**' поведение идентично прежнему подсеквенс-матчу по сегментам.
    exc = _exc("Home/Components")
    assert exc.is_excluded(PurePosixPath("/home/u/Home/Components/Btn"))
    assert not exc.is_excluded(PurePosixPath("/home/u/Home/Other"))


def test_deepest_match_depth_index():
    # Глубина = индекс конца последнего совпавшего сегмента.
    exc = _exc("Archive")
    incl = _inc("Projects/**/Data")
    p = PurePosixPath("/h/Projects/Archive/Data")
    # Archive на индексе 2 -> конец 3; Data на индексе 3 -> конец 4 (глубже).
    assert exc.deepest_match(p) == 3
    assert incl.deepest_match(p) == 4


# --------------------------------------------------------------------------- #
# Intra-segment glob: '*' внутри сегмента (юнит _seg_glob, регистр уже снят)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "pat, text, ok",
    [
        # Суффикс/префикс/инфикс:
        ("*.txt", "notes.txt", True),
        ("*.txt", "notes.md", False),
        ("a*", "abc", True),
        ("a*", "abc", True),
        ("a*", "xabc", False),
        ("*foo*", "xfooy", True),
        ("*foo*", "foo", True),
        ("*foo*", "bar", False),
        ("data-*-final", "data-2020-final", True),
        ("data-*-final", "data--final", True),       # '*' матчит ноль символов
        ("data-*-final", "data-x-fin", False),
        # Одиночная '*' = весь сегмент (сегменты непустые):
        ("*", "anything", True),
        # Несколько '*' в сегменте:
        ("a*b*c", "axbyc", True),
        ("a*b*c", "abc", True),                       # пустые вставки
        ("a*b*c", "ac", False),
        # '**'/'***' вперемешку с символами трактуются как intra '*':
        ("a**b", "ab", True),
        ("a**b", "axyzb", True),
        ("***", "whatever", True),
        ("a*b*", "axb", True),
        ("a*b*", "ba", False),
        # Литерал без '*' — точное равенство:
        ("plain", "plain", True),
        ("plain", "plainx", False),
        # БЕЗОПАСНОСТЬ СКОБОК и '?': это ЛИТЕРАЛЫ, не классы/джокеры glob:
        ("файл [1]", "файл [1]", True),
        ("файл [1]", "файл 1", False),                # '[1]' НЕ класс символов
        ("файл [1]", "файл a", False),
        ("a?b", "a?b", True),
        ("a?b", "axb", False),                        # '?' литерал, не джокер
        ("инн [нового договора нет]", "инн [нового договора нет]", True),
        # '*' + литеральные скобки вместе:
        ("*[1]", "файл [1]", True),
        ("*[1]", "файл [2]", False),
    ],
)
def test_seg_glob(pat, text, ok):
    assert _seg_glob(pat, text) is ok


@pytest.mark.parametrize(
    "entry, path, excluded",
    [
        # intra-segment в реальном пути (последний сегмент / середина):
        ("*.bak", "/h/u/Docs/notes.bak", True),
        ("*.bak", "/h/u/Docs/notes.txt", False),
        ("tmp*", "/h/tmp_build/x", True),
        ("tmp*", "/h/mytmp/x", False),
        ("*cache*", "/h/u/AppCache/data", True),
        ("Projects/*/build", "/h/Projects/web/build/out", True),
        ("Projects/*/build", "/h/Projects/build", False),  # '*' — ровно один сегмент
        # Скобки в паттерне — литералы (имена проекта со скобками):
        ("Файл [1]", "/h/u/Файл [1]/x", True),
        ("Файл [1]", "/h/u/Файл 1/x", False),
        # intra '*' + cross '**' вместе:
        ("Projects/**/*.log", "/h/Projects/a/b/run.log", True),
        ("Projects/**/*.log", "/h/Projects/run.log", True),  # '**' = ноль сегментов
        ("Projects/**/*.log", "/h/Projects/a/run.txt", False),
    ],
)
def test_intra_segment_glob_matching(entry, path, excluded):
    assert _exc(entry).is_excluded(PurePosixPath(path)) is excluded


def test_intra_glob_crossplatform_drive():
    # intra-glob поверх канона диска: Win-паттерн матчит WSL-путь и наоборот.
    assert _exc("D:\\Prog*").is_excluded(PureWindowsPath("D:\\Programs\\app"))
    assert _exc("D:\\Prog*").is_excluded(PurePosixPath("/mnt/d/Programs/app"))
    assert _exc("/mnt/d/Prog*").is_excluded(PureWindowsPath("D:\\Programs\\app"))
    # Разные диски не путаются даже с glob:
    assert not _exc("E:\\Prog*").is_excluded(PurePosixPath("/mnt/d/Programs/app"))


def test_cross_segment_double_star_positions():
    # '**' в начале/середине/конце; ноль сегментов; несколько '**'.
    assert _inc("**/Data").matches(PurePosixPath("/a/b/Data"))      # начало
    assert _inc("a/**/b").matches(PurePosixPath("/r/a/b"))          # ноль сегментов
    assert _inc("a/**").matches(PurePosixPath("/r/a/x/y"))          # конец, 1+
    assert _inc("a/**").matches(PurePosixPath("/r/a"))              # конец, ноль
    assert _inc("a/**/b/**/c").matches(PurePosixPath("/r/a/x/b/y/c")) # несколько


def test_intra_glob_idempotent_safe_chars():
    # Паттерн со '*' не вносит разделителей пути и матчит по сегментам стабильно.
    inc = _inc("*.txt")
    p = PurePosixPath("/h/u/report.txt")
    assert inc.matches(p) is True
    assert inc.matches(p) is True  # повторное сопоставление детерминировано


# --- include: load_includer ---


def test_load_includer_no_file(tmp_path):
    assert load_includer(tmp_path) is None


def test_load_includer_empty_file(tmp_path):
    (tmp_path / "include.txt").write_text("", encoding="utf-8")
    inc = load_includer(tmp_path)
    assert isinstance(inc, PathIncluder)
    assert inc.patterns == []
    assert inc.deepest_match(PurePosixPath("/any/path")) == -1


def test_load_includer_patterns_and_blanks(tmp_path):
    (tmp_path / "include.txt").write_text(
        "Activities/Web/Projects/**/Data\n\n  \nFoo/Bar\n", encoding="utf-8-sig"
    )
    inc = load_includer(tmp_path)
    assert inc is not None
    assert len(inc.patterns) == 2
    assert inc.matches(PurePosixPath("/h/Activities/Web/Projects/X/Data"))


# --- include: e2e override ---


def test_fs_include_override_nested(tmp_path):
    # exclude убирает Archive и конкретный Projects; include возвращает Data-поддерево.
    base = tmp_path / "Home" / "Activities" / "Web" / "Projects" / "Addl" / "Archive" / "btkf.ru" / "Data"
    (base / "Раздел").mkdir(parents=True)
    (base / "Раздел" / "файл данных").write_text("x")
    exc = _exc("Archive", "Home/Activities/Web/Projects")
    inc = _inc("Activities/Web/Projects/**/Data")
    fs = FilesystemNormalizer(build_normalizer(), exc, inc)
    renamed, _ = fs.apply(tmp_path)
    # Data и содержимое нормализованы:
    assert base.is_dir()  # имя 'Data' уже нормальное
    assert (base / "Razdel").is_dir()
    assert (base / "Razdel" / "fail-dannykh").exists()
    # Промежуточные исключённые не тронуты:
    assert (tmp_path / "Home" / "Activities" / "Web" / "Projects").is_dir()
    assert base.parent.name == "btkf.ru"  # 'Archive' и 'btkf.ru' не нормализованы
    # В renamed попало только включённое поддерево (Razdel + файл = 2):
    assert renamed == 2


def test_fs_include_deeper_archive_reexcluded(tmp_path):
    # Внутри re-included Data есть Archive — он снова исключён (его exclude глубже).
    data = tmp_path / "Projects" / "Data"
    (data / "Archive" / "Старьё").mkdir(parents=True)
    (data / "Папка").mkdir()
    exc = _exc("Archive")
    inc = _inc("Projects/**/Data")
    fs = FilesystemNormalizer(build_normalizer(), exc, inc)
    fs.apply(tmp_path)
    assert (data / "Papka").is_dir()  # нормализовано
    assert (data / "Archive" / "Старьё").exists()  # вложенный Archive снова исключён


def test_fs_include_deeper_pattern_wins_tie(tmp_path):
    # Более глубокий include возвращает вложенный Archive (ничья по глубине -> include).
    data = tmp_path / "Projects" / "Data"
    (data / "Archive" / "Старьё").mkdir(parents=True)
    exc = _exc("Archive")
    inc = _inc("Projects/**/Data", "Projects/**/Data/**/Archive")
    fs = FilesystemNormalizer(build_normalizer(), exc, inc)
    fs.apply(tmp_path)
    assert (data / "Archive" / "Stario").exists()  # снова нормализуется


def test_fs_include_noop_without_exclude(tmp_path):
    # include без exclude ничего не меняет: всё нормализуется как обычно.
    (tmp_path / "Папка").mkdir()
    inc = _inc("Папка")
    fs = FilesystemNormalizer(build_normalizer(), None, inc)
    fs.apply(tmp_path)
    assert (tmp_path / "Papka").is_dir()


def test_fs_include_file_override(tmp_path):
    # Исключённый по имени файл повторно включается уточнённым include-путём.
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Other").mkdir()
    (tmp_path / "Docs" / "заметки.txt").write_text("x")
    (tmp_path / "Other" / "заметки.txt").write_text("x")
    exc = _exc("заметки.txt")
    inc = _inc("Docs/заметки.txt")
    fs = FilesystemNormalizer(build_normalizer(), exc, inc)
    fs.apply(tmp_path)
    assert (tmp_path / "Docs" / "zametki.txt").exists()  # включён обратно
    assert (tmp_path / "Other" / "заметки.txt").exists()  # остаётся исключён


def test_fs_exclude_intra_glob_file(tmp_path):
    # exclude по intra-glob '*.bak' исключает резервные копии в любом месте,
    # остальные файлы нормализуются и считаются.
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs" / "Отчёт.bak").write_text("1")  # исключён glob
    (tmp_path / "Docs" / "Отчёт.txt").write_text("2")  # нормализуется
    exc = _exc("*.bak")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    renamed, skipped = fs.apply(tmp_path)
    assert (tmp_path / "Docs" / "Отчёт.bak").exists()       # не тронут
    assert (tmp_path / "Docs" / "otchiot.txt").exists()     # нормализован
    assert renamed == 1
    assert skipped == 0


def test_fs_include_intra_glob_override(tmp_path):
    # exclude убирает всё поддерево Build; include с intra-glob '*.keep'
    # возвращает только подходящие файлы (override по глубине).
    build = tmp_path / "Build"
    build.mkdir()
    (build / "Черновик.tmp").write_text("x")    # остаётся исключён
    (build / "Важное.keep").write_text("y")      # re-included intra-glob
    exc = _exc("Build")
    inc = _inc("Build/*.keep")
    fs = FilesystemNormalizer(build_normalizer(), exc, inc)
    fs.apply(tmp_path)
    assert (build / "Черновик.tmp").exists()             # исключён -> не тронут
    assert (build / "vazhnoe.keep").exists()             # включён -> нормализован


def test_fs_exclude_bracket_literal_not_charclass(tmp_path):
    # Паттерн со скобками — литерал: 'Файл [1]' исключает ровно такой каталог,
    # а 'Файл 1' (как если бы '[1]' был классом) — нет.
    a = tmp_path / "Файл [1]"
    b = tmp_path / "Файл 1"
    a.mkdir()
    b.mkdir()
    (a / "вложение").write_text("x")
    (b / "вложение").write_text("y")
    exc = _exc("Файл [1]")
    fs = FilesystemNormalizer(build_normalizer(), exc)
    fs.apply(tmp_path)
    assert (a / "вложение").exists()             # исключён литерально -> не тронут
    # 'Файл 1' НЕ исключён -> нормализуются и каталог, и файл в нём (deepest-first):
    survivors = [p for p in tmp_path.rglob("*") if p.is_file() and p.read_text() == "y"]
    assert len(survivors) == 1
    assert survivors[0].name == "vlozhenie"
    assert survivors[0].parent.name != "Файл 1"  # каталог тоже нормализован


def test_fs_include_crossplatform_slash_forms(tmp_path):
    # Формы include-паттерна со слешем на конце и Windows-разделителем эквивалентны.
    for pat in ("Projects/**/Data/", "Projects\\**\\Data"):
        data = tmp_path / "Projects" / "X" / "Data"
        (data / "Папка").mkdir(parents=True)
        exc = _exc("Projects")
        inc = _inc(pat)
        fs = FilesystemNormalizer(build_normalizer(), exc, inc)
        fs.apply(tmp_path)
        assert (data / "Papka").is_dir()
        # очистка для следующей итерации
        shutil.rmtree(tmp_path / "Projects")
