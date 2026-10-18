"""tools/dispatch.py: dispatch_to_agent's error cases, state save/restore, and the real
cycle/depth-limit logic. No model/Ollama server needed - run_turn (looked up fresh from
ollama_workspace.turn on every call, since dispatch.py imports it deferred) is replaced with
a fake, and models.use/refresh are stubbed so nothing touches Ollama or data/settings.json.

For the nested-chain tests, the fake run_turn recursively calls the real dispatch_to_agent -
exercising the actual chain-tracking code in tools/dispatch.py, not a mock of it.
"""
import pytest

import ollama_workspace.turn as turn_module
from ollama_workspace import agents, memory, models
from ollama_workspace.tools import dispatch, state
from ollama_workspace.tools.base import changed


class FakeModel:
    def __init__(self, name):
        self.name = name


def make_agent(project, name, model):
    agent = agents.Agent(agents._path(project, name))
    agent.meta = {"name": name, "model": model, "persona": f"persona for {name}",
                  "all_tools": True, "tools": []}
    agent.save()
    return agent


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A project with a caller chat already active, and all the module globals
    dispatch_to_agent reads/writes set to a known, auto-restored baseline."""
    project = tmp_path
    (project / "chats").mkdir()
    caller_chat = memory.Chat.create(project, title="caller")

    monkeypatch.setattr(memory, "active", caller_chat)
    monkeypatch.setattr(agents, "active", None)
    monkeypatch.setattr(state, "active_names", None)
    monkeypatch.setattr(models, "current", FakeModel("caller-model"))
    monkeypatch.setattr(models, "installed", ["caller-model"], raising=False)
    monkeypatch.setattr(models, "refresh", lambda: None)

    def fake_use(name):
        models.current = FakeModel(name)
        return models.current
    monkeypatch.setattr(models, "use", fake_use)
    changed.clear()

    assert dispatch._chain == []  # no leftover state from a previous test
    return project, caller_chat


def install_models(monkeypatch, *names):
    monkeypatch.setattr(models, "installed", list(models.installed) + list(names))


def test_dispatch_to_unknown_agent(env, monkeypatch):
    project, caller_chat = env
    monkeypatch.setattr(turn_module, "run_turn",
                         lambda task: pytest.fail("should not run a turn"))

    result = dispatch.dispatch_to_agent("ghost", "do something")

    assert result.startswith("Error: no agent named 'ghost'")
    assert memory.active is caller_chat
    assert agents.active is None


def test_dispatch_to_self_is_rejected(env, monkeypatch):
    project, _ = env
    b = make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-b")
    monkeypatch.setattr(agents, "active", b)  # "you" are already agent B
    monkeypatch.setattr(turn_module, "run_turn",
                         lambda task: pytest.fail("should not run a turn"))

    result = dispatch.dispatch_to_agent("B", "do something")

    assert result == "Error: that's you. Dispatching to yourself would just loop."


def test_dispatch_rejects_model_not_installed(env, monkeypatch):
    project, caller_chat = env
    make_agent(project, "D", "model-d")  # not added to models.installed
    monkeypatch.setattr(turn_module, "run_turn",
                         lambda task: pytest.fail("should not run a turn"))

    result = dispatch.dispatch_to_agent("D", "do something")

    assert result == "Error: agent 'D' uses model-d, which isn't installed."
    assert memory.active is caller_chat
    assert dispatch._chain == []


def test_dispatch_happy_path_restores_everything(env, monkeypatch):
    project, caller_chat = env
    make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-b")
    captured = {}

    def fake_run_turn(task):
        captured["task"] = task
        captured["model"] = models.current.name
        captured["agent"] = agents.active.name
        captured["chat_title"] = memory.active.title
        return "the answer"
    monkeypatch.setattr(turn_module, "run_turn", fake_run_turn)

    result = dispatch.dispatch_to_agent("B", "go recon the target")

    assert result == "the answer"
    assert captured == {"task": "go recon the target", "model": "model-b",
                        "agent": "B", "chat_title": "agent:B"}
    # fully restored afterwards
    assert memory.active is caller_chat
    assert agents.active is None
    assert models.current.name == "caller-model"
    assert dispatch._chain == []


def test_dispatch_empty_reply_returns_placeholder(env, monkeypatch):
    project, _ = env
    make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-b")
    monkeypatch.setattr(turn_module, "run_turn", lambda task: "")

    assert dispatch.dispatch_to_agent("B", "go") == "(B gave no reply.)"


def test_dispatch_reuses_the_same_persistent_chat_across_calls(env, monkeypatch):
    project, _ = env
    make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-b")
    seen_dirs = []
    monkeypatch.setattr(turn_module, "run_turn",
                         lambda task: seen_dirs.append(memory.active.dir) or "ok")

    dispatch.dispatch_to_agent("B", "first")
    dispatch.dispatch_to_agent("B", "second")

    assert seen_dirs[0] == seen_dirs[1]


def test_dispatch_drops_subagent_file_changes_from_the_caller(env, monkeypatch):
    """Current behavior (locked in, not endorsed): `changed` is reset to whatever it was
    before the dispatch, so files the sub-agent reports editing don't surface in the
    caller's own [changes: ...] tag. This documents that, rather than asserting it's ideal."""
    project, _ = env
    make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-b")
    changed.clear()
    changed.add("before.py")

    def fake_run_turn(task):
        changed.add("sub_agent_edit.py")
        return "done"
    monkeypatch.setattr(turn_module, "run_turn", fake_run_turn)

    dispatch.dispatch_to_agent("B", "edit something")

    assert changed == {"before.py"}


def test_dispatch_catches_a_direct_cycle(env, monkeypatch):
    """B's turn tries to dispatch to A, whose turn tries to dispatch back to B - a real
    A -> B -> A loop, caught by the chain check rather than infinite recursion."""
    project, _ = env
    make_agent(project, "A", "model-a")
    make_agent(project, "B", "model-b")
    install_models(monkeypatch, "model-a", "model-b")

    def fake_run_turn(task):
        if agents.active.name == "B":
            return "B says: " + dispatch.dispatch_to_agent("A", "nested from B")
        if agents.active.name == "A":
            return dispatch.dispatch_to_agent("B", "nested from A")  # should be refused
        return "unexpected"
    monkeypatch.setattr(turn_module, "run_turn", fake_run_turn)

    result = dispatch.dispatch_to_agent("B", "start")

    assert "already working on this chain" in result
    assert "B -> A -> B" in result
    assert dispatch._chain == []
    assert agents.active is None
    assert memory.active.title == "caller"


def test_dispatch_rejects_a_chain_deeper_than_the_limit(env, monkeypatch):
    project, _ = env
    make_agent(project, "B", "model-b")
    make_agent(project, "C", "model-c")
    make_agent(project, "D", "model-d")
    install_models(monkeypatch, "model-b", "model-c", "model-d")
    monkeypatch.setattr(dispatch, "MAX_DISPATCH_DEPTH", 2)

    def fake_run_turn(task):
        nxt = {"B": "C", "C": "D"}.get(agents.active.name)
        if nxt:
            return dispatch.dispatch_to_agent(nxt, f"nested from {agents.active.name}")
        return "should not get here"
    monkeypatch.setattr(turn_module, "run_turn", fake_run_turn)

    result = dispatch.dispatch_to_agent("B", "start")

    assert "chain is already 2 deep" in result
    assert dispatch._chain == []
