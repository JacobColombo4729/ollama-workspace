"""Shared fixtures. Every test here runs against a tmp_path project, never the real data/
directory - PROJECTS_DIR and WORKSPACE are monkeypatched per test (see isolated_project)."""
import pytest

from ollama_workspace import config, memory


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
