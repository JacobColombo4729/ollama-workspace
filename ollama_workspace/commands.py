"""The /commands typed at the prompt, plus /cd (switch workspace) and !command (run a
shell command yourself)."""
import os
import pathlib
import shutil
import subprocess

from . import agents, config, guard, memory, models, tools, trash
from .config import TRASH_DAYS
from .console import ask
from .prompts import HELP
from .session import clean_name, find_chat, named, open_named, print_chats, set_model, switch_to
from .stream import describe_thinking
from .tools import SHELL


COMMANDS = ("/new", "/chats", "/resume", "/rename", "/delete", "/agent", "/models", "/model",
            "/think", "/notes", "/trash", "/restore", "/mode", "/approve", "/cd", "/unlock",
            "/lock", "/help")


def handle_command(q: str, project) -> None:
    cmd, _, arg = q.partition(" ")
    arg = clean_name(arg)
    if cmd == "/new":
        open_named(project, arg) if arg else switch_to(memory.Chat.create(project))
    elif cmd == "/chats":
        print_chats(memory.list_chats(project))
    elif cmd == "/resume":
        chats = memory.list_chats(project)
        if not arg:
            print_chats(chats)
            arg = ask("Chat number or name: ")
        if arg and (chat := find_chat(chats, arg)):
            switch_to(chat)
    elif cmd == "/rename" and arg:
        other = named(memory.list_chats(project), arg)
        if other and other.dir != memory.active.dir:
            print(f"Another chat is already named '{other.title}'.")
            return
        memory.active.meta["title"] = arg
        memory.active.save()
        print(f"Renamed to: {arg}")
    elif cmd == "/delete":
        delete_chats(project, arg)
    elif cmd == "/agent":
        handle_agent(project, arg)
    elif cmd == "/models":
        models.refresh()
        models.print_installed()
    elif cmd == "/model":
        models.refresh()
        name = models.find(arg) if arg else models.pick()
        if name:
            set_model(name)
    elif cmd == "/think":
        if arg and arg.lower() not in models.THINK_CHOICES:
            print(f"Choose one of: {', '.join(models.THINK_CHOICES)}")
            return
        if arg:
            memory.active.meta["think"] = arg.lower()  # each chat remembers its level
            memory.active.save()
        print(describe_thinking()[0].upper() + describe_thinking()[1:])
    elif cmd == "/notes":
        path = project / "notes.md"
        print(path.read_text("utf-8").strip() or "(no notes yet)")
        print(f"\033[2m[edit by hand: {path}]\033[0m")
    elif cmd == "/mode":
        print(guard.describe())
        print("\033[2m[restricted is the default; set per computer with setx OCHAT_MODE "
              "unleashed, then open a new terminal, to change it]\033[0m")
    elif cmd == "/trash" and arg.lower() == "empty":
        items = trash.entries(project)
        if items and ask(f"Permanently delete {len(items)} trashed item(s)? [y/N]: ").lower() in ("y", "yes"):
            print(f"Emptied the trash ({trash.empty(project)} item(s)).")
    elif cmd == "/trash":
        items = trash.entries(project)
        for i, e in enumerate(items, 1):
            print(f"{i:>4}. {e.describe()}")
        print(f"\033[2m[restore with /restore <n>; kept {TRASH_DAYS} days]\033[0m" if items
              else "The trash is empty.")
    elif cmd == "/restore":
        if not arg:
            handle_command("/trash", project)
            arg = ask("Number or path to restore: ") if trash.entries(project) else ""
        if not arg:
            return
        matches = trash.find(project, arg)
        if len({e.path for e in matches}) != 1:
            print(f"{'Several items match' if matches else 'Nothing in the trash matches'} "
                  f"'{arg}'; see /trash.")
            return
        try:
            print(f"Restored {trash.restore(matches[0], config.WORKSPACE, anywhere=not guard.restricted())}")
        except (OSError, ValueError) as e:
            print(f"Can't restore: {e}")
    elif cmd == "/approve":
        if arg.lower() in ("on", "off"):
            tools.state.ask_first = arg.lower() == "on"
        elif arg:
            print("Use /approve on or /approve off.")
            return
        what = "File changes" + ("" if guard.restricted() else " and commands")
        print(f"{what} {'ask first' if tools.state.ask_first else 'run without asking'} "
              f"(/approve {'off' if tools.state.ask_first else 'on'} to change; this chat session only).")
        if guard.restricted():
            print("\033[2m[dangerous commands always need your password]\033[0m")
    elif cmd == "/cd":
        return change_workspace(q.partition(" ")[2].strip().strip("\"'"))
    elif cmd == "/unlock":
        unlock()
    elif cmd == "/lock":
        guard.self_edit = False
        print("Locked: the model can't see or edit this tool's own code.")
    else:
        print(HELP)


def delete_chats(project, arg: str) -> None:
    """/delete <n|name>: remove one chat for good. /delete all: remove every chat in this
    project. Unlike /trash, this doesn't go through the trash (chats live outside the
    workspace, so restore_deleted can't reach them) - it asks first and that's final."""
    chats = memory.list_chats(project)
    if not arg:
        print_chats(chats)
        arg = ask("Chat number, name, or 'all' to delete: ")
    if not arg:
        return
    if arg.lower() == "all":
        if not chats:
            print("No chats to delete.")
        elif ask(f"Permanently delete all {len(chats)} chat(s) in this project? [y/N]: ").lower() in ("y", "yes"):
            for c in chats:
                shutil.rmtree(c.dir, ignore_errors=True)
            memory.active = None
            switch_to(memory.Chat.create(project))
            print(f"Deleted {len(chats)} chat(s).")
        return
    if not (chat := find_chat(chats, arg)):
        return
    if ask(f"Permanently delete '{chat.title}'? [y/N]: ").lower() not in ("y", "yes"):
        return
    was_active = memory.active is not None and memory.active.dir == chat.dir
    shutil.rmtree(chat.dir, ignore_errors=True)
    print(f"Deleted '{chat.title}'.")
    if was_active:
        memory.active = None
        remaining = memory.list_chats(project)
        switch_to(remaining[0] if remaining else memory.Chat.create(project))


def handle_agent(project, arg: str) -> None:
    """/agent: list agents and ask which to switch to. /agent new <name>: create one.
    /agent delete <n|name>: remove one. /agent none: go back to this chat's own model and
    full tools. /agent <n|name>: switch to it (remembered for this chat, like /model)."""
    sub, _, rest = arg.partition(" ")
    if sub.lower() == "new":
        name = clean_name(rest) or ask("Name for the new agent: ")
        if name:
            models.refresh()
            agents.create_agent(project, name, models.pick)
        return
    if sub.lower() == "delete":
        existing = agents.list_agents(project)
        target = clean_name(rest)
        if not target:
            agents.print_agents(existing)
            target = ask("Agent number or name to delete: ")
        if target and (agent := agents.find_agent(existing, target)):
            if ask(f"Delete agent '{agent.name}'? [y/N]: ").lower() in ("y", "yes"):
                agents.delete_agent(agent)
                print(f"Deleted agent '{agent.name}'.")
        return
    if sub.lower() == "none":
        agents.activate(None)
        memory.active.meta["agent"] = ""  # explicit, so resuming this chat stays agent-less
        memory.active.save()
        print("Agent cleared; this chat uses its own model and full tools again.")
        return
    existing = agents.list_agents(project)
    if not arg:
        agents.print_agents(existing)
        arg = ask("Agent number, name, 'new <name>', or 'none' to clear: ")
        if arg:
            handle_agent(project, arg)
        return
    if not (agent := agents.find_agent(existing, arg)):
        return
    agents.activate(agent)
    memory.active.meta["agent"] = agent.name
    memory.active.save()
    models.refresh()
    if agent.model in models.installed:
        set_model(agent.model)
    else:
        print(f"\033[2m[agent '{agent.name}' uses {agent.model}, which isn't installed; "
              "keeping the current model]\033[0m")
    print(f"Agent: {agent.name}" + (f" - {agent.persona}" if agent.persona else ""))


def unlock() -> None:
    """Let the model edit this chat tool's own code for the rest of the session."""
    if guard.self_edit:
        print("Already unlocked; /lock to undo.")
        return
    if guard.restricted() and not guard.approve("", [
            "lets the model see and change this chat tool's own code (ollama_workspace/, "
            "chat.py, the launchers) for the rest of this session. That code includes the "
            "restricted-mode checks, so a bad or tricked edit could weaken them from the "
            "next start on. Review its changes (git diff) before restarting ochat.",
            "Your chats, notes and password stay off limits. /lock or restarting ochat "
            "turns the protection back on."], what="unlocking the tool's own code"):
        print("Still locked.")
        return
    guard.self_edit = True
    print("\033[33mUnlocked for this session: the model can edit this tool's own code. "
          "/lock to undo.\033[0m")


def change_workspace(path: str):
    """Switch to another folder's project, opening its latest chat. Returns the project."""
    if not path:
        print(f"Workspace: {config.WORKSPACE}")
        return None
    target = (config.WORKSPACE / pathlib.Path(path).expanduser()).resolve()
    if not target.is_dir():
        print(f"Not a folder: {target}")
        return None
    config.WORKSPACE = target
    project = memory.project_dir(target)
    trash.purge_old(project)
    print(f"Project: {target}")
    chats = memory.list_chats(project)
    switch_to(chats[0] if chats else memory.Chat.create(project))
    return project


def run_shell(command: str) -> None:
    """!command: the user runs a command in the workspace, interactively, outside the model.
    The user is trusted, so restricted mode's checks don't apply."""
    if not command:
        print("Type a command after !, e.g. !git status")
        return
    args = (["powershell", "-NoProfile", "-Command", command] if os.name == "nt"
            else [SHELL, "-c", command])
    try:
        code = subprocess.run(args, cwd=config.WORKSPACE).returncode
    except KeyboardInterrupt:
        code = "interrupted"
    except OSError as e:
        code = f"couldn't start: {e}"
    if code != 0:
        print(f"\033[2m[exit: {code}]\033[0m")
