"""Reading user input."""
import sys

BLOCK = '"""'  # a line with just this starts and ends a typed multi-line message

_session = None  # prompt_toolkit session for chat messages, created on first use


def ask(prompt: str) -> str:
    """input() without surrounding whitespace or the byte-order mark Windows PowerShell
    puts at the start of piped text (which would hide a /command)."""
    return input(prompt).replace("﻿", "").strip()


def ask_message(prompt: str) -> str:
    """Read a chat message. Pasted text never sends it: line breaks inside a paste become
    line breaks in the message, and only an Enter you type sends it, so you can keep typing
    after pasting. (Plain input() can't tell a pasted line break from Enter, so it sent
    each pasted line as its own message.) prompt_toolkit also adds line editing and
    Up/Down history. A line with just \"\"\" starts a block typed by hand."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        text = ask(prompt)  # piped input: one line per message, as before
    else:
        global _session
        if _session is None:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            _session = PromptSession(history=InMemoryHistory(), input=_input())
        text = _session.prompt(prompt).replace("﻿", "")
    if text.strip() == BLOCK:
        return _typed_block()
    return text.strip()


def _input():
    """prompt_toolkit's keyboard input. On Windows it normally relies on the terminal
    marking pastes ("bracketed paste"), which Windows Terminal and VS Code do but the old
    console window may not; there a paste would still arrive as separate lines. Outside
    those terminals, use its other Windows reader, which spots a paste as a burst of keys
    arriving at once. Returns None for prompt_toolkit's default."""
    import os
    if os.name != "nt" or os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return None
    try:
        from prompt_toolkit.input.win32 import ConsoleInputReader, Win32Input
        inp = Win32Input()
        inp.console_input_reader = ConsoleInputReader()  # detects pastes as bursts
        inp._use_virtual_terminal_input = False          # keep the console mode to match
        return inp
    except (ImportError, AttributeError):  # a prompt_toolkit version without these
        return None


def _typed_block() -> str:
    print(f'\033[2m[multi-line message: finish with a line containing only {BLOCK}]\033[0m')
    lines = []
    try:
        while (line := input("... ")).strip() != BLOCK:
            lines.append(line)
    except KeyboardInterrupt:
        print("\n[cancelled]")
        return ""
    return "\n".join(lines).strip()
