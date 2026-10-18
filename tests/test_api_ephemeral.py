"""api.py: Session/run_once's ephemeral=True option - independent, non-accumulating calls
even when an agent is given, instead of reusing (and polluting) that agent's persistent
chat. No model or Ollama server needed - api.run_turn is replaced with a fake that reads
and writes memory.active directly, the same way turn.run_turn would via memory.active.append.
guard.init() is stubbed since it depends on real machine state (and the runner's privilege
level), neither of which this test cares about."""
import pytest

from ollama_workspace import agents, api, config, guard, memory, models


class DummyModel:
    def __init__(self, name):
        self.name = name


def make_agent(project, name, model="m"):
    agent = agents.Agent(agents._path(project, name))
    agent.meta = {"name": name, "model": model, "persona": "", "all_tools": True, "tools": []}
    agent.save()
    return agent


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
    monkeypatch.setattr(guard, "init", lambda: None)

    project = memory.project_dir(workspace)
    make_agent(project, "scout")
    return workspace, project


def fake_run_turn_recording(message):
    """Stands in for turn.run_turn: records what was already in context (the prior log)
    before "answering", then appends this turn - exactly what a real turn would persist."""
    prior = memory.active.log()
    memory.active.append(message, f"reply to: {message}")
    return prior


def test_ephemeral_call_does_not_touch_the_agents_persistent_chat_field(env, monkeypatch):
    workspace, project = env
    monkeypatch.setattr(api, "run_turn", fake_run_turn_recording)

    api.run_once(workspace, "first", agent="scout", ephemeral=True)

    reloaded = agents.Agent(agents._path(project, "scout"))
    assert "chat" not in reloaded.meta


def test_two_ephemeral_calls_to_the_same_agent_do_not_share_context(env, monkeypatch):
    workspace, _ = env
    monkeypatch.setattr(api, "run_turn", fake_run_turn_recording)

    first_prior_log = api.run_once(workspace, "first turn", agent="scout", ephemeral=True)
    second_prior_log = api.run_once(workspace, "second turn", agent="scout", ephemeral=True)

    assert first_prior_log == ""   # nothing before it: a fresh chat
    assert second_prior_log == ""  # still fresh: no trace of the first call's turn
    assert "first turn" not in second_prior_log


def test_ephemeral_calls_use_different_chat_dirs(env, monkeypatch):
    workspace, _ = env
    seen_dirs = []

    def fake_run_turn(message):
        seen_dirs.append(memory.active.dir)
        return "ok"
    monkeypatch.setattr(api, "run_turn", fake_run_turn)

    api.run_once(workspace, "first", agent="scout", ephemeral=True)
    api.run_once(workspace, "second", agent="scout", ephemeral=True)

    assert seen_dirs[0] != seen_dirs[1]


def test_non_ephemeral_call_still_reuses_the_agents_persistent_chat(env, monkeypatch):
    workspace, _ = env
    seen_dirs = []

    def fake_run_turn(message):
        seen_dirs.append(memory.active.dir)
        memory.active.append(message, "ok")
        return "ok"
    monkeypatch.setattr(api, "run_turn", fake_run_turn)

    api.run_once(workspace, "first", agent="scout")
    api.run_once(workspace, "second", agent="scout")

    assert seen_dirs[0] == seen_dirs[1]  # same persistent chat both times
