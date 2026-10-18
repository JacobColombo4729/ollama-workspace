"""tools/edit.py: edit_file, write_file, make_dir, move_path - and the approval prompt
(_confirm) they all share, which is off by default in the `workspace` fixture."""
from ollama_workspace import config
from ollama_workspace.tools import base, edit
from ollama_workspace.tools.base import changed


def test_edit_file_replaces_the_one_exact_match(workspace):
    (workspace / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

    result = edit.edit_file("a.py", "x = 1", "x = 100")

    assert result == "Saved a.py."
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 100\ny = 2\n"
    assert "a.py" in changed


def test_edit_file_rejects_zero_matches(workspace):
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = edit.edit_file("a.py", "not there", "x")
    assert "found 0 times" in result
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 1\n"  # unchanged


def test_edit_file_rejects_multiple_matches(workspace):
    (workspace / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = edit.edit_file("a.py", "x = 1", "x = 2")
    assert "found 2 times" in result
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 1\nx = 1\n"  # unchanged


def test_edit_file_preserves_crlf_line_endings(workspace):
    (workspace / "a.txt").write_bytes(b"line1\r\nline2\r\n")
    edit.edit_file("a.txt", "line1", "LINE1")
    assert (workspace / "a.txt").read_bytes() == b"LINE1\r\nline2\r\n"


def test_edit_file_asks_first_when_approvals_are_on(workspace, monkeypatch):
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    base.state.ask_first = True
    monkeypatch.setattr(base, "ask", lambda prompt: "n")

    result = edit.edit_file("a.py", "x = 1", "x = 2")

    assert "rejected" in result.lower()
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_edit_file_feedback_is_passed_back(workspace, monkeypatch):
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    base.state.ask_first = True
    monkeypatch.setattr(base, "ask", lambda prompt: "not like that, use a constant")

    result = edit.edit_file("a.py", "x = 1", "x = 2")

    assert "Feedback: not like that, use a constant" in result


def test_write_file_creates_a_new_file(workspace):
    result = edit.write_file("new.txt", "hello\n")
    assert result == "Saved new.txt."
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "hello\n"
    assert "new.txt" in changed


def test_write_file_creates_missing_parent_folders(workspace):
    edit.write_file("a/b/c.txt", "deep\n")
    assert (workspace / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "deep\n"


def test_write_file_overwrites_an_existing_file(workspace):
    (workspace / "a.txt").write_text("old\n", encoding="utf-8")
    edit.write_file("a.txt", "new\n")
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "new\n"


def test_write_file_rejects_a_folder_path(workspace):
    (workspace / "a_dir").mkdir()
    result = edit.write_file("a_dir", "x")
    assert result == "Error: a_dir is a folder."


def test_make_dir_creates_nested_folders(workspace):
    result = edit.make_dir("a/b/c")
    assert result == "Created a/b/c/."
    assert (workspace / "a" / "b" / "c").is_dir()
    assert "a/b/c/" in changed


def test_make_dir_reports_already_exists(workspace):
    (workspace / "existing").mkdir()
    result = edit.make_dir("existing")
    assert result == "existing already exists."


def test_make_dir_asks_first_when_approvals_are_on(workspace, monkeypatch):
    base.state.ask_first = True
    monkeypatch.setattr(base, "ask", lambda prompt: "n")

    result = edit.make_dir("blocked")

    assert "rejected" in result.lower()
    assert not (workspace / "blocked").exists()


def test_move_path_renames_a_file(workspace):
    (workspace / "old.txt").write_text("x", encoding="utf-8")
    result = edit.move_path("old.txt", "new.txt")
    assert result == "Moved old.txt to new.txt."
    assert not (workspace / "old.txt").exists()
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "x"
    assert "old.txt -> new.txt" in changed


def test_move_path_into_an_existing_folder_keeps_the_name(workspace):
    (workspace / "file.txt").write_text("x", encoding="utf-8")
    (workspace / "dest").mkdir()
    result = edit.move_path("file.txt", "dest")
    assert result == "Moved file.txt to dest/file.txt."
    assert (workspace / "dest" / "file.txt").exists()


def test_move_path_rejects_missing_source(workspace):
    result = edit.move_path("ghost.txt", "new.txt")
    assert result == "Error: ghost.txt doesn't exist."


def test_move_path_rejects_moving_the_workspace_itself(workspace):
    result = edit.move_path(".", "elsewhere")
    assert result == "Error: can't move the workspace itself."


def test_move_path_rejects_an_existing_destination(workspace):
    (workspace / "src.txt").write_text("x", encoding="utf-8")
    (workspace / "dst.txt").write_text("y", encoding="utf-8")
    result = edit.move_path("src.txt", "dst.txt")
    assert "already exists" in result
    assert (workspace / "src.txt").exists()  # nothing moved


def test_move_path_creates_missing_destination_parents(workspace):
    (workspace / "src.txt").write_text("x", encoding="utf-8")
    edit.move_path("src.txt", "deep/nested/dst.txt")
    assert (workspace / "deep" / "nested" / "dst.txt").read_text(encoding="utf-8") == "x"


def test_move_path_rejects_outside_workspace_in_restricted(workspace, tmp_path):
    (workspace / "src.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    try:
        edit.move_path("src.txt", str(outside))
        assert False, "expected a ValueError from _resolve"
    except ValueError:
        pass
    assert config.WORKSPACE == workspace  # fixture's config untouched by the failed attempt
