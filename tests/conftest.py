"""Shared fixtures. Every test here runs against a tmp_path project, never the real data/
directory - PROJECTS_DIR and WORKSPACE are monkeypatched per test (see isolated_project)."""
import pytest

from ollama_workspace import config, guard, memory
from ollama_workspace.tools import state


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    """A workspace + project dir rooted in tmp_path, with config.WORKSPACE and
    memory.PROJECTS_DIR pointed at it so nothing touches the real data/ folder."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(memory, "PROJECTS_DIR", tmp_path / "projects")
    project = memory.project_dir(workspace)
    return workspace, project


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A plain workspace for the file tools (browse.py, edit.py, ...): restricted mode,
    not /unlock'd, and approvals off by default so most tests don't need to stub console.ask -
    tests of the approval prompt itself override ask_first and stub base.ask explicitly."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", ws)
    monkeypatch.setattr(guard, "mode", "restricted")
    monkeypatch.setattr(guard, "self_edit", False)
    monkeypatch.setattr(state, "ask_first", False)
    return ws
