import pytest

from normalizer import (
    CaseRule,
    DateRule,
    FilesystemNormalizer,
    LeadingZeroRule,
    TrimEdgeRule,
    build_normalizer,
)


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
        # Папки с ведущим мусором — капитализация за один прогон:
        ("  отчёт", True),
        ("   фывфыв   фывфыв ---", True),
        ("--- папка", True),
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
# CaseRule / TrimEdgeRule
# --------------------------------------------------------------------------- #
def test_case_rule():
    assert CaseRule().apply("report", is_dir=True) == "Report"
    assert CaseRule().apply("Report", is_dir=False) == "report"
    # README в верхнем регистре сохраняется как есть:
    assert CaseRule().apply("README", is_dir=False) == "README"
    # Сохраняется только точное совпадение: иной регистр приводится к нижнему.
    assert CaseRule().apply("Readme", is_dir=False) == "readme"


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
    ],
)
def test_trim_edge(raw, expected):
    assert TrimEdgeRule().apply(raw, is_dir=False) == expected


def test_trim_edge_dir_strips_leading_underscore():
    # Для папок поведение не меняется: ведущий '_' обрезается.
    assert TrimEdgeRule().apply("__name__", is_dir=True) == "name"


def test_empty_stem_guard(nn):
    # Имя из символов, которые после транслитерации/чистки исчезают -> без изменений.
    assert nn.normalize("@@@.png", is_dir=False) == "@@@.png"


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
