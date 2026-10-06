"""The chat loop: picks the chat, reads messages, runs the model and its tool calls, and
saves each exchange. The pieces live in prompts.py, stream.py, session.py, commands.py
and tools/."""
import argparse
import os
import pathlib
import sys

import ollama

from . import config, guard, memory, models, tools, trash
from .commands import COMMANDS, handle_command, run_shell
from .config import MAX_TOOL_STEPS, REPLY_LIMIT, UNLEASHED_TOOL_STEPS
from .console import ask, ask_message
from .attachments import attach_files
from .session import clean_name, drop_if_empty, find_chat, named, print_chats, set_model, switch_to
from .stream import build_messages, fit_context, interjection, stream_step
from .tools import changed, run_tool


def main() -> None:
    parser = argparse.ArgumentParser(description="ollama-workspace: terminal chat for any Ollama model, with per-project memory.")
    parser.add_argument("name", nargs="?",
                        help="open the chat with this name, or start one with it")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true", help="start a new (unnamed) chat")
    group.add_argument("--resume", action="store_true", help="pick which chat to continue")
    parser.add_argument("--workspace", metavar="FOLDER",
                        help="project folder to work on (default: the current folder)")
    parser.add_argument("--model", metavar="NAME",
                        help="Ollama model to use (number, name, or part of a name)")
    parser.add_argument("--think", choices=models.THINK_CHOICES,
                        help="how much the model reasons before answering (saved on the chat)")
    args = parser.parse_args()
    guard.init()  # quits if this computer has no mode set
    tools.state.ask_first = guard.restricted() and not config.AUTO_APPROVE  # unleashed never asks
    if args.workspace:
        config.WORKSPACE = pathlib.Path(args.workspace).expanduser().resolve()
        if not config.WORKSPACE.is_dir():
            parser.error(f"not a folder: {config.WORKSPACE}")

    if os.name == "nt":
        os.system("")  # enables ANSI colors in the Windows console
    else:
        try:
            import readline  # noqa: F401  arrow keys and history for input() on macOS/Linux
        except ImportError:
            pass
    try:
        models.refresh()
    except Exception as e:  # httpx.ConnectError etc. when the server isn't up
        sys.exit(f"Can't reach Ollama ({e}).\nStart the Ollama app or run 'ollama serve', "
                 "then try again.")
    if not models.installed:
        sys.exit("No chat models installed. Install one with e.g. 'ollama pull llama3.2' "
                 "(browse more at https://ollama.com/library).")
    if args.model:  # an explicit choice beats the chat's and the saved one
        if not (name := models.find(args.model)):
            sys.exit(1)
        set_model(name)

    project = memory.project_dir(config.WORKSPACE)
    trash.purge_old(project)
    chats = memory.list_chats(project)
    color = "33" if guard.restricted() else "31"
    print(f"\033[1;{color}mMode: {guard.mode.upper()}\033[0m  (/mode for details)")
    print(f"Project: {config.WORKSPACE}")
    keep = not args.model
    if args.name:
        if chat := named(chats, clean_name(args.name)):
            print(f"[opening existing chat '{chat.title}']")
            switch_to(chat, keep)
        else:
            switch_to(memory.Chat.create(project, clean_name(args.name)), keep)
    elif args.new or not chats:
        switch_to(memory.Chat.create(project), keep)
    elif args.resume:
        print_chats(chats)
        chat = find_chat(chats, ask("Chat number or name [1]: ") or "1")
        switch_to(chat or chats[0], keep)
    else:
        switch_to(chats[0], keep)  # continue the most recent chat

    if models.current is None:  # chat had no (installed) model: saved default, or ask
        default = models.saved_default()
        if default in models.installed:
            set_model(default)
        elif len(models.installed) == 1:
            set_model(models.installed[0])
        else:
            set_model(models.pick())
        memory.active.compact_if_needed()
    elif args.model:  # record the explicit choice on this chat
        memory.active.meta["model"] = models.current.name
        memory.active.save()
    if args.think:
        handle_command(f"/think {args.think}", project)
    print("Type /help for commands, 'exit' to quit.\n")
    while True:
        try:
            q = ask_message("> ")
        except (EOFError, KeyboardInterrupt):  # Ctrl+Z / Ctrl+C at the prompt
            q = "exit"
            print()
        if q.lower() in ("exit", "quit", "/exit", "/quit"):
            drop_if_empty(memory.active)
            break
        if not q:
            continue
        if q.startswith("!"):
            run_shell(q[1:].strip())
            continue
        if q.startswith("/") and q.split()[0] in COMMANDS:
            project = handle_command(q, project) or project  # /cd switches projects
            continue
        prompt, attached = attach_files(q)
        num_predict = REPLY_LIMIT
        messages = build_messages(prompt)
        changed.clear()
        replies, notes, done_reason = [], [], None
        max_steps = MAX_TOOL_STEPS if guard.restricted() else UNLEASHED_TOOL_STEPS
        print("[waiting for model... Ctrl+C to interrupt and add info]", flush=True)
        try:
            # the model may call tools several times before it gives its final answer
            for _ in range(max_steps):
                fit_context(messages, num_predict)
                content, reasoning, calls, done_reason = stream_step(messages, num_predict)
                if done_reason == "interrupted":
                    try:
                        note = ask_message("[paused] Add info for the model (Enter = just stop): ")
                    except KeyboardInterrupt:
                        note = ""
                    if content.strip():
                        replies.append(content.strip() + " [interrupted]")
                    if not note:
                        print("[stopped]")
                        done_reason = "stopped"
                        break
                    notes.append(note)
                    if content.strip():
                        messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": interjection(reasoning, note)})
                    print("[continuing with your note...]", flush=True)
                    continue
                if content.strip():
                    replies.append(content.strip())
                    print()
                messages.append({"role": "assistant", "content": content, "tool_calls": calls})
                if not calls:
                    break
                for call in calls:
                    messages.append({"role": "tool", "content": run_tool(call),
                                     "tool_name": call.function.name})
            else:
                print(f"[stopped after {max_steps} tool steps]")
        except KeyboardInterrupt:  # Ctrl+C outside streaming, e.g. at an edit approval prompt
            print("\033[0m\n[stopped]")
            done_reason = "stopped"
        except ollama.ResponseError as e:
            print(f"\033[0m\n[model error: {e.error}] - try /model to switch models")
            continue  # nothing to save
        reply = "\n".join(replies)
        print()
        if not reply and not changed:
            if done_reason == "stopped":
                continue  # stopped before saying anything: don't clutter the history
            print(f"[no answer - stopped: {done_reason}; raise REPLY_LIMIT or THINK_BUDGET in config.py]")
        # log only file names, not contents, so big files don't flood memory
        logged = q + (f" [attached: {', '.join(attached)}]" if attached else "")
        logged += "".join(f"\n[interjected: {n}]" for n in notes)
        if changed:
            reply += f" [changes: {', '.join(sorted(changed))}]"
        memory.active.meta["model"] = models.current.name
        memory.active.append(logged, reply)  # saved immediately, so nothing is lost on a crash
        memory.active.compact_if_needed()
