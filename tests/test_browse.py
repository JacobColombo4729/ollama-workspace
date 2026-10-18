"""tools/browse.py: listing, finding, searching, outlining and reading files. Pure
filesystem operations against the `workspace` fixture (see conftest.py) - no model needed
except for read_file's context budget, which is stubbed with a fake Model."""
from ollama_workspace import models
from ollama_workspace.tools import base, browse


class FakeModel:
    def __init__(self, limit):
        self.limit = limit

    def chars(self, share):
        return self.limit


def test_list_files_reports_every_file_with_size(workspace):
    (workspace / "a.txt").write_text("hi", encoding="utf-8")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("hello", encoding="utf-8")

    out = browse.list_files()

    assert "a.txt (2 bytes)" in out
    assert "sub/b.txt (5 bytes)" in out


def test_list_files_empty_workspace(workspace):
    assert browse.list_files() == "(no files)"


def test_list_files_skips_hidden_and_build_dirs(workspace):
    (workspace / "keep.txt").write_text("x", encoding="utf-8")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "y.js").write_text("x", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "z").write_text("x", encoding="utf-8")

    out = browse.list_files()

    assert "keep.txt" in out
    assert "x.pyc" not in out
    assert "y.js" not in out
    assert "z" not in out


def test_list_dir_lists_folders_then_files_with_counts_and_sizes(workspace):
    (workspace / "b_folder").mkdir()
    (workspace / "b_folder" / "inner.txt").write_text("x", encoding="utf-8")
    (workspace / "a_folder").mkdir()
    (workspace / "c.txt").write_text("hello", encoding="utf-8")

    out = browse.list_dir()

    lines = out.splitlines()
    assert lines[0] == "./"
    assert "a_folder/  (0 items)" in lines
    assert "b_folder/  (1 item)" in lines
    assert "c.txt  (5 bytes)" in lines
    # folders (alphabetical) before files
    assert lines.index("a_folder/  (0 items)") < lines.index("c.txt  (5 bytes)")


def test_list_dir_on_empty_folder(workspace):
    (workspace / "empty").mkdir()
    assert browse.list_dir("empty") == "empty/\n(empty folder)"


def test_list_dir_rejects_a_file_path(workspace):
    (workspace / "f.txt").write_text("x", encoding="utf-8")
    assert browse.list_dir("f.txt") == "Error: f.txt is not a folder."


def test_list_dir_hides_data_dir(workspace, monkeypatch):
    fake_data = workspace / "data"
    fake_data.mkdir()
    (fake_data / "secret.json").write_text("{}", encoding="utf-8")
    (workspace / "visible.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(base, "DATA_DIR", fake_data)

    out = browse.list_dir()

    assert "visible.txt" in out
    assert "data" not in out


def test_find_files_matches_by_name_case_insensitively(workspace):
    (workspace / "Config.py").write_text("x", encoding="utf-8")
    (workspace / "app.js").write_text("x", encoding="utf-8")

    assert browse.find_files("*.py") == "Config.py"
    assert browse.find_files("config.*") == "Config.py"


def test_find_files_matches_folders_with_trailing_slash(workspace):
    (workspace / "src").mkdir()
    assert browse.find_files("src") == "src/"


def test_find_files_no_matches(workspace):
    assert browse.find_files("*.nonexistent") == "No matches."


def test_find_files_skips_hidden_paths(workspace, monkeypatch):
    (workspace / "keep.py").write_text("x", encoding="utf-8")
    fake_data = workspace / "data"
    fake_data.mkdir()
    (fake_data / "secret.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(base, "DATA_DIR", fake_data)

    out = browse.find_files("*.py")

    assert "keep.py" in out
    assert "secret.py" not in out


def test_search_files_finds_matching_lines(workspace):
    (workspace / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (workspace / "b.py").write_text("x = 2\n", encoding="utf-8")

    out = browse.search_files(r"def \w+")

    assert "a.py:1: def foo():" in out
    assert "b.py" not in out


def test_search_files_is_case_insensitive(workspace):
    (workspace / "a.txt").write_text("Hello World\n", encoding="utf-8")
    assert "a.txt:1:" in browse.search_files("hello world")


def test_search_files_no_matches(workspace):
    (workspace / "a.txt").write_text("nothing relevant\n", encoding="utf-8")
    assert browse.search_files("zzz_not_present") == "No matches."


def test_file_outline_finds_python_definitions(workspace):
    (workspace / "a.py").write_text(
        "import os\n\nclass Foo:\n    def bar(self):\n        pass\n", encoding="utf-8")

    out = browse.file_outline("a.py")

    assert out.startswith("a.py: 5 lines, ")
    assert "3: class Foo:" in out
    assert "4:     def bar(self):" in out
    assert "1: import os" not in out


def test_file_outline_finds_markdown_headings(workspace):
    (workspace / "doc.md").write_text(
        "# Title\n\nSome text.\n\n## Subheading\nMore text.\n", encoding="utf-8")

    out = browse.file_outline("doc.md")

    assert "1: # Title" in out
    assert "5: ## Subheading" in out


def test_file_outline_finds_setext_markdown_headings(workspace):
    (workspace / "doc.md").write_text("Title\n=====\n\nBody text.\n", encoding="utf-8")
    out = browse.file_outline("doc.md")
    assert "1: Title" in out


def test_file_outline_reports_no_structure_found(workspace):
    (workspace / "data.txt").write_text("just some lines\nof plain text\n", encoding="utf-8")
    out = browse.file_outline("data.txt")
    assert "no structure found" in out


def test_read_file_whole_small_file(workspace, monkeypatch):
    monkeypatch.setattr(models, "current", FakeModel(10_000))
    (workspace / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")

    out = browse.read_file("a.txt")

    assert out == "line1\nline2\nline3\n"
    assert "[lines" not in out


def test_read_file_line_range(workspace, monkeypatch):
    monkeypatch.setattr(models, "current", FakeModel(10_000))
    (workspace / "a.txt").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

    out = browse.read_file("a.txt", start_line=2, end_line=3)

    assert out == "[lines 2-3 of 4]\nline2\nline3\n"


def test_read_file_empty_file(workspace, monkeypatch):
    monkeypatch.setattr(models, "current", FakeModel(10_000))
    (workspace / "empty.txt").write_text("", encoding="utf-8")
    assert browse.read_file("empty.txt") == "(no content: file has 0 lines)"


def test_read_file_cuts_off_past_the_context_budget(workspace, monkeypatch):
    monkeypatch.setattr(models, "current", FakeModel(12))  # tiny budget: a couple of lines
    (workspace / "a.txt").write_text("123456\n123456\n123456\n123456\n", encoding="utf-8")

    out = browse.read_file("a.txt")

    assert "cut off at line" in out
    assert "start_line=" in out
