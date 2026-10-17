"""Agent profiles: named presets that pin a chat to a particular model, tool access, and
persona, so one chat can be "mostly text, call out code" while another is "coding only,
narrate rarely" - the balance comes from the persona you write, not a fixed category.

data/projects/<project>/agents/<name>.json   one per agent, in that project

Activating an agent (/agent <name>) sets `active` and narrows tools.state.active_names for
the rest of the chat; it's remembered per chat (chat.meta["agent"]) the same way the model
is, so resuming a chat restores which agent (if any) was active.
"""
import json
import re
from pathlib import Path

from . import tools
from .console import ask, ask_message

active: "Agent | None" = None  # the agent governing the current chat, if any


class Agent:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.meta = json.loads(path.read_text("utf-8"))
        else:
            self.meta = {"name": path.stem, "model": "", "persona": "",
                        "all_tools": False, "tools": []}

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def model(self) -> str:
        return self.meta["model"]

    @property
    def persona(self) -> str:
        return self.meta["persona"]

    @property
    def all_tools(self) -> bool:
        return self.meta.get("all_tools", False)

    @property
    def tool_names(self) -> list[str]:
        return self.meta.get("tools", [])

    def describe_tools(self) -> str:
        return "all tools" if self.all_tools else (", ".join(self.tool_names) or "no tools")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.meta, indent=2), "utf-8")


def _dir(project: Path) -> Path:
    return project / "agents"


def _path(project: Path, name: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", name) or "agent"
    return _dir(project) / f"{safe}.json"


def list_agents(project: Path) -> list[Agent]:
    """Agents in a project, alphabetical by name."""
    d = _dir(project)
    if not d.is_dir():
        return []
    agents = [Agent(p) for p in d.glob("*.json")]
    return sorted(agents, key=lambda a: a.name.lower())


def named(agents: list[Agent], name: str) -> Agent | None:
    return next((a for a in agents if a.name.lower() == name.lower()), None)


def find_agent(agents: list[Agent], ref: str) -> Agent | None:
    """Find an agent by its /agent list number, exact name, or a unique part of its name."""
    if ref.isdigit() and 1 <= int(ref) <= len(agents):
        return agents[int(ref) - 1]
    if agent := named(agents, ref):
        return agent
    partial = [a for a in agents if ref.lower() in a.name.lower()]
    if len(partial) == 1:
        return partial[0]
    print(f"{'Several agents match' if partial else 'No agent matches'} '{ref}'; see /agent.")
    return None


def print_agents(agents: list[Agent]) -> None:
    if not agents:
        print("No agents yet in this project. /agent new <name> to create one.")
    for i, a in enumerate(agents, 1):
        mark = "*" if active and active.name == a.name else " "
        print(f"{mark}{i:>3}. {a.name}  ({a.model or 'no model set'}, {a.describe_tools()})")


def activate(agent: "Agent | None") -> None:
    """Make this agent (or None, to clear) govern tool access and persona for the rest of
    this chat. Doesn't touch the model - the caller switches that separately."""
    global active
    active = agent
    tools.state.active_names = None if (agent is None or agent.all_tools) else agent.tool_names


_CODE_WORDS = ("code", "coding", "program", "implement", "develop", "build", "debug",
               "refactor", "script", "edit", "file", "test")
_TEXT_WORDS = ("supervisor", "coordinat", "audit", "log", "narrat", "summar", "report",
               "oversee", "distribut", "delegat", "status", "manager", "plan")


def suggest_tools(persona: str) -> str:
    """A rough "all" or "none" guess from the persona text, shown as a hint - never applied
    without the user confirming it (typing nothing just falls back to this hint, not a
    silent default)."""
    low = persona.lower()
    code_hits = sum(w in low for w in _CODE_WORDS)
    text_hits = sum(w in low for w in _TEXT_WORDS)
    if code_hits > text_hits:
        return "all"
    if text_hits > code_hits:
        return "none"
    return ""


def _parse_tool_choice(choice: str, hint: str) -> tuple[bool, list[str]]:
    """"all"/"none", or a space/comma separated list of tool numbers or names (from the
    list create_agent prints) -> (all_tools, tool_names)."""
    low = choice.strip().lower() or hint or "none"
    if low in ("all", "a"):
        return True, []
    if low in ("none", "n"):
        return False, []
    names = [t.__name__ for t in tools.TOOLS]
    picked = []
    for part in re.split(r"[,\s]+", choice.strip()):
        if not part:
            continue
        if part.isdigit() and 1 <= int(part) <= len(names):
            picked.append(names[int(part) - 1])
        elif part in names:
            picked.append(part)
        else:
            match = [n for n in names if part.lower() in n.lower()]
            if len(match) == 1:
                picked.append(match[0])
            else:
                print(f"\033[2m[ignoring '{part}': {'ambiguous' if match else 'no match'} "
                      "tool name]\033[0m")
    return False, sorted(set(picked))


def create_agent(project: Path, name: str, pick_model) -> Agent | None:
    """Guided creation: asks for a persona in the user's own words (which drives how much
    it narrates vs. just shows code - that's a prompting choice, not a fixed category),
    which tools it gets, and its model. pick_model() is called to choose the model (see
    models.pick)."""
    if named(list_agents(project), name):
        print(f"An agent named '{name}' already exists; /agent delete {name} first, or "
              "pick another name.")
        return None
    print(f"Describe '{name}' in your own words: its role, and how much it should narrate "
          "in text vs. just show code. (\"\"\" for a multi-line description.)")
    persona = ask_message("> ").strip()
    hint = suggest_tools(persona)
    print("\nWhich tools should it have?\n"
          "  all              full file/shell access, like an ordinary coding agent\n"
          "  none             text only, no file or shell access\n"
          "  <names/numbers>  just these tools:")
    for i, t in enumerate(tools.TOOLS, 1):
        print(f"    {i:>3}. {t.__name__}")
    choice = ask(f"Tools{f' [{hint}]' if hint else ''}: ")
    all_tools, tool_names = _parse_tool_choice(choice, hint)
    model = pick_model()
    if not model:
        print("No model chosen; agent not created.")
        return None
    agent = Agent(_path(project, name))
    agent.meta = {"name": name, "model": model, "persona": persona,
                 "all_tools": all_tools, "tools": tool_names}
    agent.save()
    print(f"Created agent '{name}' ({model}, {agent.describe_tools()}).")
    return agent


def delete_agent(agent: Agent) -> None:
    agent.path.unlink(missing_ok=True)
    if active is not None and active.name == agent.name:
        activate(None)
