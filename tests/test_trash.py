"""trash.py: delete -> list -> restore roundtrip."""
from datetime import datetime

from ollama_workspace import trash


def test_put_does_not_collide_within_the_same_clock_tick(tmp_path, monkeypatch):
    """Two deletes landing in the same timestamp (common on Windows, whose clock doesn't
    really tick every microsecond) must not crash with FileExistsError."""
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    frozen = datetime(2026, 1, 1, 12, 0, 0)
    monkeypatch.setattr(trash, "datetime", type("_dt", (), {"now": staticmethod(lambda: frozen)}))

    for name in ("a.txt", "b.txt"):
        p = workspace / name
        p.write_text(name, encoding="utf-8")
        trash.put(project, p, name)

    items = trash.entries(project)
    assert len(items) == 2
    assert {e.path for e in items} == {"a.txt", "b.txt"}


def test_delete_list_restore_roundtrip(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    f = workspace / "note.txt"
    f.write_text("hello", encoding="utf-8")

    trash.put(project, f, "note.txt")
    assert not f.exists()

    items = trash.entries(project)
    assert len(items) == 1
    assert items[0].path == "note.txt"
    assert "note.txt" in items[0].describe()

    restored_rel = trash.restore(items[0], workspace)
    assert restored_rel == "note.txt"
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "hello"
    assert trash.entries(project) == []


def test_restore_rejects_outside_workspace_without_anywhere(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    f = workspace / "note.txt"
    f.write_text("hello", encoding="utf-8")
    trash.put(project, f, "note.txt")
    entry = trash.entries(project)[0]

    try:
        trash.restore(entry, workspace, rel="../escaped.txt")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_find_by_number_and_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for name in ("a.txt", "b.txt"):
        p = workspace / name
        p.write_text(name, encoding="utf-8")
        trash.put(project, p, name)

    items = trash.entries(project)
    assert len(items) == 2
    assert trash.find(project, "1")[0].path == items[0].path
    assert trash.find(project, "b.txt")[0].path == "b.txt"
    assert trash.find(project, "nope.txt") == []


def test_empty_removes_everything(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for name in ("a.txt", "b.txt"):
        p = workspace / name
        p.write_text(name, encoding="utf-8")
        trash.put(project, p, name)

    assert trash.empty(project) == 2
    assert trash.entries(project) == []
