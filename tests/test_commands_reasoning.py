"""commands.py: the /reasoning command - a display-only toggle, independent of /think. See
test_models_settings.py for the underlying persisted setting and test_stream.py for the
actual print gate."""
import pytest

from ollama_workspace import commands, models


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DATA_DIR", tmp_path)
    monkeypatch.setattr(models, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(models, "show_thinking_override", None)


def test_no_argument_shows_the_current_state(settings_file, capsys):
    commands.handle_command("/reasoning", None)
    assert "on" in capsys.readouterr().out.lower()


def test_off_then_on_persists_and_reports_the_new_state(settings_file, capsys):
    commands.handle_command("/reasoning off", None)
    assert models.show_thinking() is False
    assert "off" in capsys.readouterr().out.lower()

    commands.handle_command("/reasoning on", None)
    assert models.show_thinking() is True
    assert "on" in capsys.readouterr().out.lower()


def test_invalid_argument_is_rejected_without_changing_anything(settings_file, capsys):
    commands.handle_command("/reasoning maybe", None)
    assert "choose" in capsys.readouterr().out.lower()
    assert models.show_thinking() is True  # unchanged
