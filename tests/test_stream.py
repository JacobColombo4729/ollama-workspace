"""stream.py: the /reasoning (show_thinking) gate on printed reasoning - checks that it's
only the PRINT that's toggled, not the reasoning collected and returned, the tool calls, or
the final answer. No Ollama server needed: ollama.chat is stubbed to yield a canned
thinking-then-content stream."""
import ollama
import pytest

from ollama_workspace import memory, models, stream


class DummyModel:
    name = "dummy"
    tools = False
    num_ctx = 4096

    def think_value(self, choice):
        return None


def fake_chat(**kwargs):
    return [
        {"done_reason": None, "message": {"thinking": "pondering...", "content": ""}},
        {"done_reason": "stop", "message": {"thinking": "", "content": "the answer"}},
    ]


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(ollama, "chat", fake_chat)
    monkeypatch.setattr(models, "current", DummyModel())
    monkeypatch.setattr(memory, "active", None)  # think_level() falls back to THINK_LEVEL


def test_reasoning_is_printed_when_show_thinking_is_on(stubbed, monkeypatch, capsys):
    monkeypatch.setattr(models, "show_thinking_override", True)

    content, reasoning, calls, done = stream.stream_step([], 100)

    out = capsys.readouterr().out
    assert "[thinking]" in out
    assert "pondering" in out
    assert content == "the answer"
    assert reasoning == "pondering..."
    assert done == "stop"


def test_reasoning_is_hidden_but_still_collected_when_show_thinking_is_off(
        stubbed, monkeypatch, capsys):
    monkeypatch.setattr(models, "show_thinking_override", False)

    content, reasoning, calls, done = stream.stream_step([], 100)

    out = capsys.readouterr().out
    assert "[thinking]" not in out
    assert "pondering" not in out
    assert content == "the answer"       # the answer is unaffected
    assert reasoning == "pondering..."   # still collected, just not printed
    assert done == "stop"
