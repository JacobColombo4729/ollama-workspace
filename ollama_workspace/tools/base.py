"""Shared by the tools: what the model may see (workspace limits, hidden paths), reading
files, asking the user, and the state of the current message."""
import os
import pathlib

from .. import config, guard
from ..config import DATA_DIR, ROOT, SKIP_DIRS
from ..console import ask


class State:
    # whether file changes (and, in unleashed mode, commands) ask first; set at startup
    # from the mode and AUTO_APPROVE, and switched with /approve
    ask_first = True


state = State()
changed: set[str] = set()  # files edited during the current message


def _inside(p: pathlib.Path, folder: pathlib.Path) -> bool:
    return p == folder or folder in p.parents


def _hidden() -> set[pathlib.Path]:
    """Paths the model may not see: chat memory (other projects' chats live there too),
    this chat tool itself when it's copied inside the project being worked on, and in
    restricted mode the tool's code always, so the model can't switch off its guardrails."""
    hidden = {DATA_DIR.resolve()}
    if ROOT != config.WORKSPACE and _inside(ROOT, config.WORKSPACE):
        hidden.add(ROOT)
    if guard.restricted():
        hidden.update(guard.PROTECTED)
        # a hook written here would run on an ordinary 'git commit', skipping the password
        hidden.add(config.WORKSPACE / ".git" / "hooks")
    return hidden


def _resolve(path: str) -> pathlib.Path:
    """A workspace-relative path (or, in unleashed mode, any path) checked against limits."""
    path = str(path).strip().strip("\"'")
    # an absolute path replaces the workspace part when joined
    p = (config.WORKSPACE / pathlib.Path(path).expanduser()).resolve()
    if not p.exists() and "\\ " in path:  # shell-escaped spaces, e.g. My\ File.py
        p = (config.WORKSPACE / path.replace("\\ ", " ")).resolve()
    if guard.restricted() and not _inside(p, config.WORKSPACE):
        raise ValueError(f"{path} is outside the workspace {config.WORKSPACE}")
    if any(_inside(p, h) for h in _hidden()):
        raise ValueError(f"{path} belongs to the chat tool and is off limits")
    return p


def _read(p: pathlib.Path) -> tuple[str, bool]:
    """Read with \\n line endings; also report whether the file used \\r\\n."""
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        raw = f.read()
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def _rel(p: pathlib.Path) -> str:
    """Workspace-relative path, or the full path for places outside it (unleashed mode)."""
    if _inside(p, config.WORKSPACE):
        return p.relative_to(config.WORKSPACE).as_posix() or "."
    return p.as_posix()


def _confirm(question: str) -> str | None:
    """Ask the user if approvals are on; None means approved, otherwise the rejection
    message for the model."""
    if not state.ask_first:
        return None
    answer = ask(f"{question} [y/N or type feedback]: ")
    if answer.lower() in ("y", "yes"):
        return None
    note = f" Feedback: {answer}" if answer.lower() not in ("", "n", "no") else ""
    return f"User rejected this.{note}"


def _walk(start: pathlib.Path | None = None):
    hidden = _hidden()
    for root, dirs, files in os.walk(start or config.WORKSPACE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and pathlib.Path(root, d).resolve() not in hidden)
        for name in sorted(files):
            if pathlib.Path(root, name).resolve() not in hidden:
                yield pathlib.Path(root, name)


def _size(n: int) -> str:
    return f"{n} bytes" if n < 1024 else f"{n / 1024:.1f} KB" if n < 2**20 else f"{n / 2**20:.1f} MB"


def _tail(text: str, limit: int) -> str:
    """Keep the end of long output, where errors and results usually are."""
    return text if len(text) <= limit else f"...[{len(text) - limit:,} chars cut]\n" + text[-limit:]
