"""agents.py: agent profiles (model + tools + persona), their persistence, lookup, and the
guided creation flow. No model/Ollama server needed - create_agent's model choice is a
callback (pick_model), and its I/O goes through console.ask/ask_message, which we stub."""
import shutil

import pytest

from ollama_workspace import agents, tools


def make_agent(project, name, model="m", persona="p", all_tools=False, tool_names=None):
    agent = agents.Agent(agents._path(project, name))
    agent.meta = {"name": name, "model": model, "persona": persona,
                  "all_tools": all_tools, "tools": tool_names or []}
    agent.save()
    return agent


@pytest.fixture
def project(tmp_path):
    (tmp_path / "chats").mkdir()
    return tmp_path


def test_agent_defaults_when_file_does_not_exist(project):
    agent = agents.Agent(agents._path(project, "scout"))
    assert agent.name == "scout"
    assert agent.model == ""
    assert agent.persona == ""
    assert agent.all_tools is False
    assert agent.tool_names == []
    assert agent.describe_tools() == "no tools"


def test_agent_save_and_reload(project):
    make_agent(project, "scout", model="qwen3:8b", persona="recon", all_tools=True)
    reloaded = agents.Agent(agents._path(project, "scout"))
    assert reloaded.model == "qwen3:8b"
    assert reloaded.persona == "recon"
    assert reloaded.all_tools is True
    assert reloaded.describe_tools() == "all tools"


def test_path_sanitizes_name(project):
    p = agents._path(project, "weird name!/with*chars")
    assert p.parent == agents._dir(project)
    assert p.suffix == ".json"
    assert "/" not in p.stem and "*" not in p.stem and "!" not in p.stem

    assert agents._path(project, "") == agents._dir(project) / "agent.json"


def test_list_agents_empty_when_no_agents_dir(project):
    assert agents.list_agents(project) == []


def test_list_agents_sorted_case_insensitively(project):
    for name in ("Zeta", "alpha", "Mid"):
        make_agent(project, name)
    assert [a.name for a in agents.list_agents(project)] == ["alpha", "Mid", "Zeta"]


def test_named_is_case_insensitive(project):
    make_agent(project, "Scout")
    found = agents.list_agents(project)
    assert agents.named(found, "SCOUT").name == "Scout"
    assert agents.named(found, "nope") is None


def test_find_agent_by_number_name_and_partial(project, capsys):
    make_agent(project, "alpha")
    make_agent(project, "alphabet")
    make_agent(project, "beta")
    found = agents.list_agents(project)  # alpha, alphabet, beta

    assert agents.find_agent(found, "1").name == "alpha"
    assert agents.find_agent(found, "beta").name == "beta"
    assert agents.find_agent(found, "eta").name == "beta"  # unique partial match
    assert agents.find_agent(found, "alpha").name == "alpha"  # exact match

    assert agents.find_agent(found, "alph") is None  # ambiguous: alpha and alphabet
    assert "Several agents match" in capsys.readouterr().out

    assert agents.find_agent(found, "nonexistent") is None
    assert "No agent matches" in capsys.readouterr().out


def test_activate_restricts_tools_unless_all_tools(project, monkeypatch):
    monkeypatch.setattr(agents, "active", None)
    monkeypatch.setattr(tools.state, "active_names", None)

    full = make_agent(project, "full", all_tools=True)
    agents.activate(full)
    assert agents.active is full
    assert tools.state.active_names is None  # all_tools: no restriction

    limited = make_agent(project, "limited", all_tools=False, tool_names=["read_file"])
    agents.activate(limited)
    assert agents.active is limited
    assert tools.state.active_names == ["read_file"]

    agents.activate(None)
    assert agents.active is None
    assert tools.state.active_names is None


def test_agent_chat_creates_once_and_reuses(project):
    agent = make_agent(project, "scout")
    assert "chat" not in agent.meta

    chat1 = agents.agent_chat(project, agent)
    assert agent.meta["chat"] == chat1.dir.name
    assert agents.Agent(agents._path(project, "scout")).meta["chat"] == chat1.dir.name

    chat2 = agents.agent_chat(project, agent)
    assert chat2.dir == chat1.dir
    assert len(list((project / "chats").iterdir())) == 1


def test_agent_chat_recreates_if_its_chat_folder_is_gone(project):
    agent = make_agent(project, "scout")
    chat1 = agents.agent_chat(project, agent)
    chat1.append("hi", "hello")
    shutil.rmtree(chat1.dir)

    chat2 = agents.agent_chat(project, agent)
    assert chat2.dir.is_dir()
    assert chat2.log() == ""  # a fresh chat, not somehow still holding the deleted one's log


@pytest.mark.parametrize("persona,expected", [
    ("implement and debug the coding script", "all"),
    ("supervise and summarize status reports", "none"),
    ("hello there, nothing special", ""),
    ("coordinate the next build", ""),  # one code word, one text word: a tie
])
def test_suggest_tools_heuristic(persona, expected):
    assert agents.suggest_tools(persona) == expected


def test_parse_tool_choice_all_and_none():
    assert agents._parse_tool_choice("all", "") == (True, [])
    assert agents._parse_tool_choice("none", "") == (False, [])


def test_parse_tool_choice_empty_falls_back_to_hint():
    assert agents._parse_tool_choice("", "all") == (True, [])
    assert agents._parse_tool_choice("", "") == (False, [])  # no hint either: defaults none


def test_parse_tool_choice_by_number_and_exact_name():
    names = [t.__name__ for t in tools.TOOLS]
    assert agents._parse_tool_choice("1", "") == (False, [names[0]])
    assert agents._parse_tool_choice("read_file", "") == (False, ["read_file"])


def test_parse_tool_choice_ignores_ambiguous_and_unknown(capsys):
    all_tools, picked = agents._parse_tool_choice("zzz_not_a_real_tool", "")
    assert (all_tools, picked) == (False, [])
    assert "no match" in capsys.readouterr().out

    all_tools, picked = agents._parse_tool_choice("file", "")  # matches several *_file tools
    assert (all_tools, picked) == (False, [])
    assert "ambiguous" in capsys.readouterr().out


def test_create_agent_guided_flow(project, monkeypatch):
    monkeypatch.setattr(agents, "ask_message", lambda prompt: "a recon specialist, terse")
    monkeypatch.setattr(agents, "ask", lambda prompt: "all")
    agent = agents.create_agent(project, "scout", pick_model=lambda: "qwen3:8b")

    assert agent is not None
    assert agent.name == "scout"
    assert agent.model == "qwen3:8b"
    assert agent.persona == "a recon specialist, terse"
    assert agent.all_tools is True
    assert agents.Agent(agents._path(project, "scout")).model == "qwen3:8b"


def test_create_agent_refuses_duplicate_name(project, capsys):
    make_agent(project, "scout")
    agent = agents.create_agent(project, "scout", pick_model=lambda: "qwen3:8b")
    assert agent is None
    assert "already exists" in capsys.readouterr().out


def test_create_agent_without_a_model_is_not_created(project, monkeypatch):
    monkeypatch.setattr(agents, "ask_message", lambda prompt: "persona")
    monkeypatch.setattr(agents, "ask", lambda prompt: "none")
    agent = agents.create_agent(project, "scout", pick_model=lambda: None)

    assert agent is None
    assert not agents._path(project, "scout").exists()


def test_delete_agent_removes_file_and_clears_if_active(project, monkeypatch):
    agent = make_agent(project, "scout")
    monkeypatch.setattr(agents, "active", agent)
    monkeypatch.setattr(tools.state, "active_names", None)

    agents.delete_agent(agent)

    assert not agents._path(project, "scout").exists()
    assert agents.active is None


def test_delete_agent_leaves_a_different_active_agent_alone(project, monkeypatch):
    scout = make_agent(project, "scout")
    other = make_agent(project, "other")
    monkeypatch.setattr(agents, "active", other)
    monkeypatch.setattr(tools.state, "active_names", None)

    agents.delete_agent(scout)

    assert not agents._path(project, "scout").exists()
    assert agents.active is other
