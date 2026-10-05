"""The chat loop: picks the chat, handles /commands, streams replies, runs tool calls,
and keeps the context within budget."""
import argparse
import os
import pathlib
import shutil
import sys

import ollama

from . import config, memory, models
from .console import ask
from .attachments import attach_files
from .config import (CHARS_PER_TOKEN, REPLY_LIMIT, MAX_TOOL_STEPS, MEMORY_SHARE, STYLE,
                     THINK_BUDGET, THINK_LEVEL)
from .tools import TOOLS, changed, run_tool

TRIMMED = "[old tool output removed to save context; call the tool again if you need it]"

CODING = (
    "You can work on the codebase in {workspace} with tools: list_files, search_files, "
    "file_outline, read_file, edit_file, write_file. Use them only when the user's request "
    "involves the code or files. Read a file before editing it. For large files, call "
    "file_outline first and read only the line ranges you need. Make small targeted edits "
    "with edit_file and use paths relative to the workspace. The user approves each edit; "
    "if one is rejected, follow their feedback. When done, briefly say what you changed.\n"
    "Memory tools: search_history finds exact details from earlier conversation that are only "
    "summarized in your memory. save_note records a lasting project fact for future chats."
)

NO_TOOLS = (
    "You have no access to the user's files in this chat. If they ask for code changes, "
    "show the changed code in your reply."
)

HELP = """Commands:
  /new [name]         start a new chat in this project (or open the one with that name)
  /chats              list this project's chats
  /resume <n|name>    switch chats by number from /chats or by name
  /rename <name>      rename the current chat
  /models             list installed Ollama models
  /model [n|name]     switch model for this chat (no argument: pick from a list)
  /think [level]      how much the model reasons first: off, low, medium, high
                      (less = faster; no argument: show the current level)
  /notes              show the project notes (shared by all chats here)
  /help               show this
  exit                quit
Ctrl+C during a reply pauses it so you can add info."""

COMMANDS = ("/new", "/chats", "/resume", "/rename", "/models", "/model", "/think", "/notes",
            "/help")


def think_level() -> str:
    """This chat's /think choice: off, low, medium or high."""
    level = memory.active.meta.get("think") if memory.active else None
    return level if level in models.THINK_CHOICES else THINK_LEVEL


def think_budget() -> int:
    """Extra tokens reserved for reasoning: scales with the thinking level."""
    if models.current.think_value(think_level()) in (None, False):
        return 0
    return {"low": THINK_BUDGET // 2, "high": THINK_BUDGET * 2}.get(think_level(), THINK_BUDGET)


def describe_thinking() -> str:
    m, level = models.current, think_level()
    if not m.thinking:
        return "this model doesn't think, so /think has no effect"
    sent = m.think_value(level)
    detail = ("on/off only" if not m.levels
              else "levels: " + ", ".join((["off"] if m.can_disable else []) + m.levels))
    note = f" -> sends {sent!r}" if isinstance(sent, str) and sent != level else ""
    if level == "off" and not m.can_disable:
        note = " -> this model always thinks"
    return f"thinking: {level}{note} ({detail})"


def build_messages(user_msg: str) -> list:
    m = models.current
    return [
        {"role": "system", "content": memory.active.memory_prompt(m.chars(MEMORY_SHARE), m.tools)},
        {"role": "system", "content": CODING.format(workspace=config.WORKSPACE)
                                      if m.tools else NO_TOOLS},
        # style rules go last so they aren't buried under the long log
        {"role": "system", "content": "Response style: " + STYLE},
        {"role": "user", "content": user_msg},
    ]


def fit_context(messages: list, num_predict: int) -> None:
    """Ollama silently drops the start of the conversation when it overflows, which would
    lose the memory and instructions. Clear the oldest tool outputs first instead."""
    budget = (models.current.num_ctx - num_predict - think_budget()) * CHARS_PER_TOKEN
    size = sum(len(m["content"] or "") + len(str(m.get("tool_calls") or "")) for m in messages)
    for m in messages:
        if size <= budget:
            return
        if m["role"] == "tool" and m["content"] != TRIMMED:
            size -= len(m["content"]) - len(TRIMMED)
            m["content"] = TRIMMED
            print("\033[2m[cleared an old tool output to stay within the context window]\033[0m")


def stream_step(messages: list, num_predict: int) -> tuple[str, str, list, str | None]:
    """Stream one model response. Returns (reply text, reasoning, tool calls, done reason);
    done reason is "interrupted" if the user pressed Ctrl+C."""
    content, reasoning, calls, in_think, reply_tokens, done_reason = "", "", [], False, 0, None
    # num_predict counts thinking + reply together, so give thinking its own budget
    # and cap the reply ourselves (each streamed content chunk is ~1 token)
    m = models.current
    stream = ollama.chat(model=m.name, messages=messages, stream=True,
                         tools=TOOLS if m.tools else None, think=m.think_value(think_level()),
                         options={"num_ctx": m.num_ctx,
                                  "num_predict": num_predict + think_budget()})
    try:
        for part in stream:
            done_reason = part.get("done_reason") or done_reason
            calls += part["message"].get("tool_calls") or []
            think_chunk = part["message"].get("thinking") or ""
            if think_chunk:
                if not in_think:
                    print("\033[2m[thinking]\n", end="", flush=True)  # dim
                    in_think = True
                print(think_chunk, end="", flush=True)
                reasoning += think_chunk
            chunk = part["message"]["content"] or ""
            if chunk:
                if in_think:
                    print("\033[0m\n\n", end="", flush=True)  # reset dim, blank line before answer
                    in_think = False
                print(chunk, end="", flush=True)
                content += chunk
                reply_tokens += 1
                if reply_tokens >= num_predict:
                    done_reason = "length"
                    break
    except KeyboardInterrupt:
        done_reason = "interrupted"
    finally:
        if hasattr(stream, "close"):
            stream.close()  # closes the connection, which makes Ollama stop generating
    print("\033[0m" + ("\n" if in_think or done_reason == "interrupted" else ""),
          end="", flush=True)
    return content, reasoning, calls, done_reason


INTERJECT_REASONING = 6000  # chars of interrupted reasoning carried over (the most recent part)


def interjection(reasoning: str, note: str) -> str:
    """The message that hands the model its interrupted reasoning plus the user's note."""
    so_far = reasoning.strip()
    if len(so_far) > INTERJECT_REASONING:
        so_far = "..." + so_far[-INTERJECT_REASONING:]
    return ("[The user interrupted you to add information.]\n\n"
            + (f"Your reasoning so far:\n{so_far}\n\n" if so_far else "")
            + f"The user adds: {note}\n\n"
            "Continue from where you were, taking this into account. Don't restart your "
            "reasoning from scratch or apologize for the interruption.")


def print_chats(chats: list) -> None:
    if not chats:
        print("No chats yet in this project.")
    for i, c in enumerate(chats, 1):
        mark = "*" if memory.active and c.dir == memory.active.dir else " "
        print(f"{mark}{i:>3}. {c.title}  ({len(c.exchanges())} messages, {c.meta['updated']})")


def drop_if_empty(chat) -> None:
    """Don't keep unnamed chats that never got a message."""
    if chat is not None and not chat.meta["title"] and not chat.log().strip():
        shutil.rmtree(chat.dir, ignore_errors=True)


def set_model(name: str) -> None:
    m = models.use(name)
    print(f"Model: {m.describe()}")
    if m.thinking:
        print(f"\033[2m[{describe_thinking()}; change with /think]\033[0m")
    if not m.tools:
        print("\033[2m[this model can't use tools: file editing, history search and notes "
              "are off]\033[0m")
    if memory.active is not None:
        memory.active.meta["model"] = name  # each chat remembers its model
        memory.active.save()


def switch_to(chat, adopt_model: bool = True) -> None:
    if memory.active is not None and memory.active.dir != chat.dir:
        drop_if_empty(memory.active)
    memory.active = chat
    n = len(chat.exchanges())
    print(f"Chat: {chat.title}" + (f" ({n} messages)" if n else " (new)"))
    want = chat.meta.get("model")
    if adopt_model and want and (models.current is None or want != models.current.name):
        if want in models.installed:
            set_model(want)
        else:
            print(f"\033[2m[this chat used {want}, which isn't installed]\033[0m")
    if models.current is not None:
        chat.compact_if_needed()  # handles an already-large log (needs a model)


def clean_name(text: str) -> str:
    """Normalize a typed chat name: single spaces, and no surrounding quotes, so
    /rename "my chat" gives the same name as `ochat "my chat"` (where the shell drops them)."""
    text = " ".join(text.split())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def named(chats: list, name: str):
    """The chat whose name matches exactly (ignoring case), or None."""
    return next((c for c in chats if clean_name(c.meta["title"]).lower() == name.lower()), None)


def find_chat(chats: list, ref: str):
    """Find a chat by its /chats number, exact name, or a unique part of its name."""
    if ref.isdigit() and 1 <= int(ref) <= len(chats):
        return chats[int(ref) - 1]
    if chat := named(chats, ref):
        return chat
    partial = [c for c in chats if ref.lower() in c.meta["title"].lower()]
    if len(partial) == 1:
        return partial[0]
    print(f"{'Several chats match' if partial else 'No chat matches'} '{ref}'; see /chats.")
    return None


def open_named(project, name: str) -> None:
    """Switch to the chat with this name, or start one with it."""
    if chat := named(memory.list_chats(project), name):
        print(f"[opening existing chat '{chat.title}']")
        switch_to(chat)
    else:
        switch_to(memory.Chat.create(project, name))


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
    else:
        print(HELP)


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
    chats = memory.list_chats(project)
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
            q = ask("> ")
        except (EOFError, KeyboardInterrupt):  # Ctrl+Z / Ctrl+C at the prompt
            q = "exit"
            print()
        if q.lower() in ("exit", "quit", "/exit", "/quit"):
            drop_if_empty(memory.active)
            break
        if not q:
            continue
        if q.startswith("/") and q.split()[0] in COMMANDS:
            handle_command(q, project)
            continue
        prompt, attached = attach_files(q)
        num_predict = REPLY_LIMIT
        messages = build_messages(prompt)
        changed.clear()
        replies, notes, done_reason = [], [], None
        print("[waiting for model... Ctrl+C to interrupt and add info]", flush=True)
        try:
            # the model may call tools several times before it gives its final answer
            for _ in range(MAX_TOOL_STEPS):
                fit_context(messages, num_predict)
                content, reasoning, calls, done_reason = stream_step(messages, num_predict)
                if done_reason == "interrupted":
                    try:
                        note = ask("[paused] Add info for the model (Enter = just stop): ")
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
                print(f"[stopped after {MAX_TOOL_STEPS} tool steps]")
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
            reply += f" [edited: {', '.join(sorted(changed))}]"
        memory.active.meta["model"] = models.current.name
        memory.active.append(logged, reply)  # saved immediately, so nothing is lost on a crash
        memory.active.compact_if_needed()
