"""Workspace tools the model can call. ollama builds each tool's schema from its
signature and docstring, so the docstrings are what the model reads."""
import difflib
import os
import pathlib
import re

from . import config, memory, models
from .console import ask
from .config import AUTO_APPROVE, DATA_DIR, READ_SHARE, ROOT, SKIP_DIRS

changed: set[str] = set()  # files edited during the current message

CODE_OUTLINE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub\s+)?(?:async\s+)?"
    r"(?:def|class|function|interface|type|enum|struct|impl|trait|fn|func|module)\b"
    r"|^\s*(?:public|private|protected|internal|static)\s[^=;]*\("
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\(|function)"
)
DOC_OUTLINE = re.compile(r"^#{1,6}\s|^[^\s].*\n(?:=+|-+)\s*$")
DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt"}


def _inside(p: pathlib.Path, folder: pathlib.Path) -> bool:
    return p == folder or folder in p.parents


def _hidden() -> set[pathlib.Path]:
    """Folders the model may not see: chat memory (other projects' chats live there too),
    and this chat tool itself when it's copied inside the project being worked on."""
    hidden = {DATA_DIR.resolve()}
    if ROOT != config.WORKSPACE and _inside(ROOT, config.WORKSPACE):
        hidden.add(ROOT)
    return hidden


def _resolve(path: str) -> pathlib.Path:
    path = str(path).strip().strip("\"'")
    p = (config.WORKSPACE / path).resolve()
    if not p.exists() and "\\ " in path:  # shell-escaped spaces, e.g. My\ File.py
        p = (config.WORKSPACE / path.replace("\\ ", " ")).resolve()
    if not _inside(p, config.WORKSPACE):
        raise ValueError(f"{path} is outside the workspace {config.WORKSPACE}")
    if any(_inside(p, h) for h in _hidden()):
        raise ValueError(f"{path} belongs to the chat tool and is off limits")
    return p


def _read(p: pathlib.Path) -> tuple[str, bool]:
    """Read with \\n line endings; also report whether the file used \\r\\n."""
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        raw = f.read()
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def _walk():
    hidden = _hidden()
    for root, dirs, files in os.walk(config.WORKSPACE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and pathlib.Path(root, d).resolve() not in hidden)
        for name in sorted(files):
            yield pathlib.Path(root, name)


def _apply(p: pathlib.Path, old: str, new: str, crlf: bool) -> str:
    """Show a diff, ask the user, and write the file if approved."""
    rel = p.relative_to(config.WORKSPACE).as_posix()
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
                                f"a/{rel}", f"b/{rel}", lineterm="")
    for line in diff:
        color = "32" if line.startswith("+") else "31" if line.startswith("-") else "2"
        print(f"\033[{color}m{line}\033[0m")
    if not AUTO_APPROVE:
        answer = ask(f"Apply to {rel}? [y/N or type feedback]: ")
        if answer.lower() not in ("y", "yes"):
            note = f" Feedback: {answer}" if answer.lower() not in ("", "n", "no") else ""
            return f"User rejected the change to {rel}.{note}"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new.replace("\n", "\r\n") if crlf else new)
    changed.add(rel)
    return f"Saved {rel}."


def _size(n: int) -> str:
    return f"{n} bytes" if n < 1024 else f"{n / 1024:.1f} KB" if n < 2**20 else f"{n / 2**20:.1f} MB"


def list_files() -> str:
    """List every file in the workspace with its size.

    Returns:
        One 'path (size)' per line.
    """
    paths = [f"{p.relative_to(config.WORKSPACE).as_posix()} ({_size(p.stat().st_size)})"
             for p in _walk()]
    more = f"\n...and {len(paths) - 500} more" if len(paths) > 500 else ""
    return "\n".join(paths[:500]) + more if paths else "(workspace is empty)"


def search_files(pattern: str) -> str:
    """Search all workspace files for a regex (case-insensitive).

    Args:
        pattern: Regular expression to look for.

    Returns:
        Matches as path:line: text, up to 100.
    """
    rx, hits = re.compile(pattern, re.IGNORECASE), []
    for p in _walk():
        try:
            text, _ = _read(p)
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{p.relative_to(config.WORKSPACE).as_posix()}:{n}: {line.strip()[:200]}")
                if len(hits) >= 100:
                    return "\n".join(hits) + "\n...(stopped at 100 matches)"
    return "\n".join(hits) or "No matches."


def file_outline(path: str) -> str:
    """Show a file's structure (classes, functions, headings) with line numbers instead of
    its full text. Use it first on large files, then read_file only the lines you need.

    Args:
        path: File path relative to the workspace.

    Returns:
        Line count, size, and one 'line: definition or heading' per structural line.
    """
    p = _resolve(path)
    text, _ = _read(p)
    lines = text.splitlines()
    if p.suffix.lower() in DOC_SUFFIXES:
        # setext headings need the next line, so match on line pairs
        hits = [n for n, l in enumerate(lines, 1)
                if DOC_OUTLINE.match(l + "\n" + (lines[n] if n < len(lines) else ""))]
    else:
        hits = [n for n, l in enumerate(lines, 1) if CODE_OUTLINE.match(l)]
    body = "\n".join(f"{n:>6}: {lines[n - 1].rstrip()[:160]}" for n in hits[:400])
    return (f"{path}: {len(lines)} lines, {len(text):,} chars\n"
            + (body or "(no structure found; use read_file with line ranges)"))


def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read a text file from the workspace, whole or a line range.

    Args:
        path: File path relative to the workspace.
        start_line: First line to return (1-based).
        end_line: Last line to return; 0 means the end of the file.

    Returns:
        The file's text for those lines (very long reads are cut off with a note).
    """
    text, _ = _read(_resolve(path))
    lines = text.splitlines(keepends=True)
    start = max(int(start_line), 1)
    end = min(int(end_line) or len(lines), len(lines))
    out, used, limit = [], 0, models.current.chars(READ_SHARE)
    for i in range(start - 1, end):
        if used + len(lines[i]) > limit and out:
            out.append(f"\n...[cut off at line {i}; use file_outline, or read_file with "
                       f"start_line={i + 1} for more]")
            break
        out.append(lines[i])
        used += len(lines[i])
    if not out:
        return f"(no content: file has {len(lines)} lines)"
    whole = start == 1 and end == len(lines) and len(out) == end
    return "".join(out) if whole else f"[lines {start}-{end} of {len(lines)}]\n" + "".join(out)


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact piece of text in an existing file. Read that part first.

    Args:
        path: File path relative to the workspace.
        old_text: Exact text to replace, including indentation; must appear exactly once.
        new_text: Text to put in its place.

    Returns:
        Whether the change was saved or rejected.
    """
    p = _resolve(path)
    text, crlf = _read(p)
    count = text.count(old_text)
    if count != 1:
        return (f"Error: old_text found {count} times in {path}; it must match exactly once. "
                "Re-read that part of the file and include more surrounding lines.")
    return _apply(p, text, text.replace(old_text, new_text), crlf)


def write_file(path: str, content: str) -> str:
    """Create a new file, or overwrite a whole file. Prefer edit_file for changes.

    Args:
        path: File path relative to the workspace.
        content: The complete file contents.

    Returns:
        Whether the file was saved or rejected.
    """
    p = _resolve(path)
    old, crlf = _read(p) if p.exists() else ("", False)
    return _apply(p, old, content, crlf)


def search_history(query: str, all_chats: bool = False) -> str:
    """Search the full saved transcript of past conversations, including parts that are
    only summarized in your memory. Use it to recover exact earlier details.

    Args:
        query: Words to look for (case-insensitive); an exchange matches if it has all of them.
        all_chats: Also search the other chats in this project.

    Returns:
        Up to 15 matching exchanges with their dates, most recent last.
    """
    words = [w.lower() for w in str(query).split()]
    if not words:
        return "Error: empty query."
    every = str(all_chats).lower() in ("true", "1", "yes")
    chats = memory.list_chats(memory.active.project) if every else [memory.active]
    hits = []
    for chat in chats:
        for ex in chat.exchanges():
            low = ex.lower()
            if all(w in low for w in words):
                stamp = memory.STAMP.search(ex)
                if len(ex) > 1500:  # show the part around the first match
                    s = max(0, low.find(words[0]) - 600)
                    ex = ("..." if s else "") + ex[s:s + 1500] + "..."
                hits.append((stamp.group(1) if stamp else "",
                             f"--- chat: {chat.title} ---\n{ex.strip()}"))
    if not hits:
        return "No matches."
    shown = [h for _, h in sorted(hits, key=lambda h: h[0])][-15:]
    return f"{len(hits)} matches" + (", showing the last 15" if len(hits) > 15 else "") + \
        ":\n\n" + "\n\n".join(shown)


def save_note(note: str) -> str:
    """Save a lasting fact about this project (decision, convention, user preference) to the
    project notes that every chat in this project sees. Use sparingly, for things that matter
    beyond this conversation.

    Args:
        note: One short sentence.

    Returns:
        Confirmation.
    """
    note = " ".join(str(note).split())
    with (memory.active.project / "notes.md").open("a", encoding="utf-8") as f:
        f.write(f"- {note}\n")
    print(f"\033[2m[noted] {note}\033[0m")
    return "Saved to project notes."


TOOLS = [list_files, search_files, file_outline, read_file, edit_file, write_file,
         search_history, save_note]
TOOL_MAP = {f.__name__: f for f in TOOLS}


def run_tool(call) -> str:
    name, args = call.function.name, dict(call.function.arguments or {})
    target = args.get("path") or args.get("pattern") or args.get("query") or ""
    if "start_line" in args or "end_line" in args:
        target += f" [{args.get('start_line', 1)}-{args.get('end_line') or 'end'}]"
    print(f"\033[36m[{name}] {target}\033[0m", flush=True)
    fn = TOOL_MAP.get(name)
    if fn is None:
        return f"Error: unknown tool {name}"
    try:
        return fn(**args)
    except Exception as e:  # report back to the model instead of crashing the chat
        return f"Error: {e}"
