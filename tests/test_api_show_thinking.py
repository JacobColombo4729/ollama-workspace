"""api.py: Session/run_once default show_thinking to off for headless calls, independent of
the REPL's saved /reasoning setting, and restore the previous override afterwards. No model
or Ollama server needed - api.run_turn (bound at import time, so it must be patched on the
api module itself, not ollama_workspace.turn) is replaced with a fake."""
import pytest

from ollama_workspace import api, config, memory, models


@pytest.fixture
def env(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(config, "WORKSPACE", workspace)
    monkeypatch.setattr(memory, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(models, "DATA_DIR", tmp_path)
    monkeypatch.setattr(models, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(models, "show_thinking_override", None)
    monkeypatch.setattr(models, "load", lambda name: DummyModel(name))
    monkeypatch.setattr(api, "run_turn", lambda message: "the answer")
    return workspace


class DummyModel:
    def __init__(self, name):
        self.name = name


def test_run_once_defaults_show_thinking_off_regardless_of_the_saved_setting(env):
    models.set_show_thinking(True)  # REPL setting: reasoning visible

    reply = api.run_once(env, "hi", model="m")

    assert reply == "the answer"
    assert models.show_thinking_override is None  # restored after the call


def test_run_once_show_thinking_true_overrides_for_that_call(env, monkeypatch):
    captured = {}

    def fake_run_turn(message):
        captured["override"] = models.show_thinking_override
        return "the answer"
    monkeypatch.setattr(api, "run_turn", fake_run_turn)

    api.run_once(env, "hi", model="m", show_thinking=True)

    assert captured["override"] is True
    assert models.show_thinking_override is None  # restored after the call


def test_session_restores_the_previous_override_on_exit(env):
    models.show_thinking_override = "sentinel"

    with api.Session(env, model="m"):
        assert models.show_thinking_override is False

    assert models.show_thinking_override == "sentinel"
