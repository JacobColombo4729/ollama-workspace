"""tools/base.py: path resolution and its workspace/hidden-path limits."""
import pytest

from ollama_workspace import config, guard
from ollama_workspace.tools import base


def test_resolve_allows_in_workspace_path(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "file.txt").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", False)

    assert base._resolve("file.txt") == (workspace / "file.txt").resolve()


def test_resolve_rejects_outside_workspace_in_restricted(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", False)

    with pytest.raises(ValueError):
        base._resolve(str(outside / "secret.txt"))


def test_resolve_allows_outside_workspace_in_unleashed(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "unleashed")
    monkeypatch.setattr(guard, "self_edit", False)

    assert base._resolve(str(outside / "secret.txt")) == (outside / "secret.txt").resolve()


def test_resolve_rejects_hidden_data_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_data = workspace / "data"
    fake_data.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", False)
    monkeypatch.setattr(base, "DATA_DIR", fake_data)

    with pytest.raises(ValueError):
        base._resolve("data/password.json")


def test_resolve_rejects_hidden_tool_code(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_code = workspace / "tool_code"
    fake_code.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", False)
    monkeypatch.setattr(guard, "PROTECTED", [fake_code])

    with pytest.raises(ValueError):
        base._resolve("tool_code/secret.py")


def test_resolve_allows_hidden_tool_code_when_unlocked(tmp_path, monkeypatch):
    """/unlock (guard.self_edit) lifts the code-hiding rule for the session."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_code = workspace / "tool_code"
    fake_code.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", True)
    monkeypatch.setattr(guard, "PROTECTED", [fake_code])

    assert base._resolve("tool_code/secret.py") == (fake_code / "secret.py").resolve()
