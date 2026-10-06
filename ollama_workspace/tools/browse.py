"""Tools for finding and reading files: browse folders, find by name, search contents,
outline and read files."""
import fnmatch
import os
import pathlib
import re

from .. import models
from ..config import READ_SHARE, SKIP_DIRS
from .base import _hidden, _read, _rel, _resolve, _size, _walk


CODE_OUTLINE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub\s+)?(?:async\s+)?"
    r"(?:def|class|function|interface|type|enum|struct|impl|trait|fn|func|module)\b"
    r"|^\s*(?:public|private|protected|internal|static)\s[^=;]*\("
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\(|function)"
)


DOC_OUTLINE = re.compile(r"^#{1,6}\s|^[^\s].*\n(?:=+|-+)\s*$")


DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt"}


def list_files(path: str = ".") -> str:
    """List every file under a folder (recursively) with its size.

    Args:
        path: Folder relative to the workspace; "." is the whole workspace.

    Returns:
        One 'path (size)' per line.
    """
    paths = [f"{_rel(p)} ({_size(p.stat().st_size)})" for p in _walk(_resolve(path))]
    more = f"\n...and {len(paths) - 500} more" if len(paths) > 500 else ""
    return "\n".join(paths[:500]) + more if paths else "(no files)"


def list_dir(path: str = ".") -> str:
    """List one folder's direct contents, like 'ls'. Use it to browse the folder tree.

    Args:
        path: Folder relative to the workspace; "." is the workspace root.

    Returns:
        Folders first (ending in '/', with their item counts), then files with sizes.
    """
    folder, hidden = _resolve(path), _hidden()
    if not folder.is_dir():
        return f"Error: {path} is not a folder."
    dirs, files = [], []
    for p in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if p.resolve() in hidden:
            continue
        if p.is_dir():
            try:
                n = sum(1 for _ in p.iterdir())
            except OSError:
                n = "?"
            dirs.append(f"{p.name}/  ({n} item{'' if n == 1 else 's'})")
        else:
            files.append(f"{p.name}  ({_size(p.stat().st_size)})")
    return f"{_rel(folder)}/\n" + ("\n".join(dirs + files) or "(empty folder)")


def find_files(pattern: str, path: str = ".") -> str:
    """Find files or folders by name with a wildcard pattern, e.g. '*.py', 'test_*',
    'config.*', or a path pattern like 'src/**/utils*'. Case-insensitive.

    Args:
        pattern: Wildcard pattern matched against names (or relative paths if it has a '/').
        path: Folder to search in, relative to the workspace.

    Returns:
        Matching paths, folders ending in '/', up to 200.
    """
    start, hits = _resolve(path), []
    pat = pattern.replace("\\", "/").lower()
    hidden = _hidden()
    for root, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and pathlib.Path(root, d).resolve() not in hidden)
        files = [f for f in sorted(files) if pathlib.Path(root, f).resolve() not in hidden]
        for name, slash in [(d, "/") for d in dirs] + [(f, "") for f in files]:
            rel = _rel(pathlib.Path(root, name))
            target = rel.lower() if "/" in pat else name.lower()
            if fnmatch.fnmatch(target, pat) or ("/" in pat and fnmatch.fnmatch(
                    target, pat.replace("**/", ""))):
                hits.append(rel + slash)
                if len(hits) >= 200:
                    return "\n".join(hits) + "\n...(stopped at 200 matches)"
    return "\n".join(hits) or "No matches."


def search_files(pattern: str, path: str = ".") -> str:
    """Search the contents of all files under a folder for a regex (case-insensitive).

    Args:
        pattern: Regular expression to look for.
        path: Folder to search in, relative to the workspace; "." is the whole workspace.

    Returns:
        Matches as path:line: text, up to 100.
    """
    rx, hits = re.compile(pattern, re.IGNORECASE), []
    for p in _walk(_resolve(path)):
        try:
            text, _ = _read(p)
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{_rel(p)}:{n}: {line.strip()[:200]}")
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
