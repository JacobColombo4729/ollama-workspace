"""dispatch_to_agent: hand a task to another agent in this project and get its result back.
Dispatching is sequential - it blocks until that agent finishes, no concurrency - and each
agent gets its own persistent chat (agents.agent_chat), so its work and context build up
across dispatches instead of starting fresh every time, reusing the normal chat/memory
machinery for free.
"""
from .. import agents, memory, models
from ..config import MAX_DISPATCH_DEPTH
from .base import changed, state

_chain: list[str] = []  # names of agents currently mid-dispatch, to catch cycles


def list_agents() -> str:
    """List the agents available to dispatch to in this project.

    Returns:
        One numbered line per agent: its name, model, tools, and persona.
    """
    found = agents.list_agents(memory.active.project)
    if not found:
        return "No agents in this project yet. The user can make one with /agent new."
    return "\n".join(f"{i}. {a.name} ({a.model}, {a.describe_tools()}) - {a.persona}"
                     for i, a in enumerate(found, 1))


def dispatch_to_agent(agent: str, task: str) -> str:
    """Hand a task to another agent and wait for its result - e.g. delegating
    implementation to a coding agent, or research/planning to a text-only one. That agent
    doesn't see this conversation, so give it full context in the task itself.

    Args:
        agent: The agent's name (see list_agents).
        task: What you want it to do, with enough context to act on its own.

    Returns:
        That agent's final reply.
    """
    from ..turn import run_turn  # deferred: avoids a circular import with tools/__init__.py

    found = agents.list_agents(memory.active.project)
    target = agents.find_agent(found, agent)
    if target is None:
        return f"Error: no agent named '{agent}'. Call list_agents to see what's available."
    if agents.active is not None and agents.active.name == target.name:
        return "Error: that's you. Dispatching to yourself would just loop."
    if target.name in _chain:
        return (f"Error: '{target.name}' is already working on this chain "
                f"({' -> '.join(_chain + [target.name])}); dispatching to it again would loop.")
    if len(_chain) >= MAX_DISPATCH_DEPTH:
        return (f"Error: this dispatch chain is already {MAX_DISPATCH_DEPTH} deep "
                f"({' -> '.join(_chain)}); go no further - finish without delegating again.")
    models.refresh()
    if target.model not in models.installed:
        return f"Error: agent '{target.name}' uses {target.model}, which isn't installed."

    prev_chat, prev_agent, prev_names = memory.active, agents.active, state.active_names
    prev_model, prev_changed = models.current.name, set(changed)
    chat = agents.agent_chat(memory.active.project, target)
    _chain.append(target.name)
    print(f"\033[35m[dispatch -> {target.name}]\033[0m {task}")
    try:
        memory.active = chat
        agents.activate(target)
        models.use(target.model)
        reply = run_turn(task)
        return reply or f"({target.name} gave no reply.)"
    finally:
        _chain.pop()
        memory.active = prev_chat
        agents.activate(prev_agent)
        state.active_names = prev_names
        models.use(prev_model)
        changed.clear()
        changed.update(prev_changed)
        print(f"\033[35m[dispatch -> {target.name} done; back to "
              f"{prev_agent.name if prev_agent else 'you'}]\033[0m")
