"""The /commands typed at the prompt, plus /cd (switch workspace) and !command (run a
shell command yourself)."""
import os
import pathlib
import subprocess

from . import config, guard, memory, models, tools, trash
from .config import TRASH_DAYS
from .console import ask
from .prompts import HELP
from .session import clean_name, find_chat, named, open_named, print_chats, set_model, switch_to
from .stream import describe_thinking
from .tools import SHELL


COMMANDS = ("/new", "/chats", "/resume", "/rename", "/models", "/model", "/think", "/notes",
            "/trash", "/restore", "/mode", "/approve", "/cd", "/help")


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
        print("\033[2m[set per computer: setx OCHAT_MODE restricted|unleashed, then open a "
              "new terminal]\033[0m")
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
    else:
        print(HELP)


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
