"""models.py: settings.json persistence for the saved model (models.use) and the
/reasoning display setting (models.show_thinking / set_show_thinking), plus the runtime
override api.Session uses for headless calls. No Ollama server needed - models.load (the
only function here that talks to Ollama) is stubbed."""
import pytest

from ollama_workspace import models


class DummyModel:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DATA_DIR", tmp_path)
    monkeypatch.setattr(models, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(models, "show_thinking_override", None)
    return tmp_path / "settings.json"


def test_show_thinking_defaults_true_with_no_settings_file(settings_file):
    assert models.show_thinking() is True


def test_set_show_thinking_persists(settings_file):
    models.set_show_thinking(False)
    assert models.show_thinking() is False
    models.set_show_thinking(True)
    assert models.show_thinking() is True


def test_set_show_thinking_does_not_erase_the_saved_model(settings_file, monkeypatch):
    monkeypatch.setattr(models, "load", lambda name: DummyModel(name))
    models.use("qwen3:8b")
    models.set_show_thinking(False)
    assert models.saved_default() == "qwen3:8b"
    assert models.show_thinking() is False


def test_use_does_not_erase_the_saved_show_thinking_setting(settings_file, monkeypatch):
    monkeypatch.setattr(models, "load", lambda name: DummyModel(name))
    models.set_show_thinking(False)
    models.use("qwen3:8b")
    assert models.show_thinking() is False  # use() merges, doesn't overwrite the whole file
    assert models.saved_default() == "qwen3:8b"


def test_show_thinking_override_takes_precedence_over_the_saved_setting(settings_file):
    models.set_show_thinking(False)
    models.show_thinking_override = True
    assert models.show_thinking() is True
    models.show_thinking_override = False
    assert models.show_thinking() is False
