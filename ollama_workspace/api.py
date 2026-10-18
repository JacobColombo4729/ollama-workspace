"""Headless API: run one turn of ollama-workspace programmatically, without the REPL.

    from ollama_workspace.api import run_once
    reply = run_once("C:/path/to/project", "I need the list of files here", model="qwen3:8b")

Reuses the same machinery the REPL uses (turn.run_turn, memory, models, agents, config),
so a programmatic call gets the same per-project memory, tools, and mode rules as an
interactive session. Importing this module has no side effects: nothing below runs until
run_once()/Session is actually called, and nothing here starts the REPL, prompts, or
needs a TTY. It does need a running Ollama server, same as the REPL.

Rough edges, documented rather than fixed here to keep this change additive:
- ollama_workspace's chat/model/agent state lives in module-level globals (memory.active,
  models.current, agents.active, tools.state, config.WORKSPACE), not function arguments.
  Session saves and restores them around a call, the same pattern tools/dispatch.py's
  dispatch_to_agent already uses for a nested dispatch - but that means two calls from
  different threads at the same time would stomp on each other. Call this one request at
  a time per process, like the REPL itself.
- There's no one to answer an approval prompt here, so Session turns tools.state.ask_first
  off for the call by default (headless means unattended), regardless of this project's
  last /approve setting. Pass approve=True to keep prompting instead - restricted mode's
  password gate on dangerous commands is unaffected either way; that's not an approval
  prompt and always applies.
- Unlike switching models in the REPL (models.use, which also remembers the pick in
  data/settings.json), Session loads a model without persisting that choice, so a headless
  call sharing a workspace with an interactive session won't change what that session
  reopens to.
- The REPL's /reasoning setting (whether the model's reasoning is printed) lives in
  data/settings.json and governs interactive sessions only. A headless call never prints to
  a terminal anyone is reading, so Session/run_once default show_thinking to False
  regardless of that saved setting, and never touch it; pass show_thinking=True to print
  reasoning for this call anyway. Either way, the model reasons exactly as /think says to -
  this only controls what's printed.
"""
from contextlib import contextmanager
from pathlib import Path

from . import agents, config, guard, memory, models
from .tools import changed, state
from .turn import run_turn

__all__ = ["Session", "run_once"]


@contextmanager
def Session(workspace, model: str | None = None, agent: str | None = None,
           approve: bool = False, show_thinking: bool | None = None):
    """Point every module-level global at `workspace`'s project for the duration of the
    `with` block, restoring the previous values on exit. If `agent` is given, that agent's
    own model is used (and its tools/persona apply) rather than `model`; `model` is a
    fallback if the agent has none set.

    `show_thinking` controls whether the model's reasoning is printed during this call:
    None (default) means off, regardless of the REPL's saved /reasoning setting; pass True
    to print it anyway, or False to be explicit. It never changes how much the model
    reasons - that's /think's job, unaffected by this.

    Yields the memory.Chat this call logs to (a fresh one, or the agent's persistent one -
    see agents.agent_chat).
    """
    try:
        guard.init()
    except SystemExit as e:
        raise RuntimeError(str(e)) from e

    prev_workspace = config.WORKSPACE
    prev_chat, prev_agent_obj = memory.active, agents.active
    prev_names, prev_model_obj = state.active_names, models.current
    prev_ask_first, prev_changed = state.ask_first, set(changed)
    prev_show_thinking = models.show_thinking_override

    config.WORKSPACE = Path(workspace).expanduser().resolve()
    project = memory.project_dir(config.WORKSPACE)
    target_agent = None
    if agent:
        target_agent = agents.find_agent(agents.list_agents(project), agent)
        if target_agent is None:
            raise ValueError(f"no agent named '{agent}' in this project")
    use_model = (target_agent.model if target_agent else None) or model
    if not use_model:
        raise ValueError("pass a model, or an agent that has one set")

    chat = (agents.agent_chat(project, target_agent) if target_agent
            else memory.Chat.create(project, title="api"))
    try:
        memory.active = chat
        agents.activate(target_agent)
        models.current = models.load(use_model)
        state.ask_first = approve
        models.show_thinking_override = bool(show_thinking)
        yield chat
    finally:
        config.WORKSPACE = prev_workspace
        memory.active = prev_chat
        agents.activate(prev_agent_obj)
        state.active_names = prev_names
        models.current = prev_model_obj
        state.ask_first = prev_ask_first
        models.show_thinking_override = prev_show_thinking
        changed.clear()
        changed.update(prev_changed)


def run_once(workspace, message: str, model: str | None = None, agent: str | None = None,
             approve: bool = False, show_thinking: bool | None = None) -> str:
    """Send one message to `model` (or to `agent`'s own model) in `workspace`'s project and
    return the model's final reply - the non-interactive equivalent of typing a message at
    the ochat prompt. Memory, tools, and mode rules (restricted/unleashed, scope, ...)
    behave exactly as they do in the REPL; see the module docstring for what's different
    about running headless (no approval prompts by default, model choice isn't persisted,
    reasoning isn't printed unless show_thinking=True).
    """
    with Session(workspace, model, agent, approve, show_thinking):
        return run_turn(message)
