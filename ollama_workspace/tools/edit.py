"""Tools that change files: edit, write, create folders, move and rename. Each shows the
change and asks first when approvals are on."""
import difflib
import pathlib
import shutil

from .. import config
from .base import _confirm, _read, _rel, _resolve, changed


def _apply(p: pathlib.Path, old: str, new: str, crlf: bool) -> str:
    """Show a diff, ask the user, and write the file if approved."""
    rel = _rel(p)
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
                                f"a/{rel}", f"b/{rel}", lineterm="")
    for line in diff:
        color = "32" if line.startswith("+") else "31" if line.startswith("-") else "2"
        print(f"\033[{color}m{line}\033[0m")
    if rejected := _confirm(f"Apply to {rel}?"):
        return rejected.replace("this", f"the change to {rel}", 1)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new.replace("\n", "\r\n") if crlf else new)
    changed.add(rel)
    return f"Saved {rel}."


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
    if p.is_dir():
        return f"Error: {path} is a folder."
    old, crlf = _read(p) if p.exists() else ("", False)
    return _apply(p, old, content, crlf)


def make_dir(path: str) -> str:
    """Create a folder (and any missing parent folders).

    Args:
        path: Folder path relative to the workspace.

    Returns:
        Whether the folder was created.
    """
    p = _resolve(path)
    if p.exists():
        return f"{_rel(p)} already exists."
    print(f"\033[32m+ {_rel(p)}/\033[0m")
    if rejected := _confirm(f"Create folder {_rel(p)}?"):
        return rejected
    p.mkdir(parents=True)
    changed.add(_rel(p) + "/")
    return f"Created {_rel(p)}/."


def move_path(source: str, destination: str) -> str:
    """Move or rename a file or folder. Missing parent folders of the destination are created.

    Args:
        source: Existing file or folder, relative to the workspace.
        destination: New path, relative to the workspace. If it's an existing folder,
            the source is moved into it.

    Returns:
        Whether it was moved.
    """
    src, dst = _resolve(source), _resolve(destination)
    if not src.exists():
        return f"Error: {source} doesn't exist."
    if src == config.WORKSPACE:
        return "Error: can't move the workspace itself."
    if dst.is_dir():
        dst = _resolve(_rel(dst / src.name))
    if dst.exists():
        return f"Error: {_rel(dst)} already exists; delete it first or choose another name."
    print(f"\033[33m{_rel(src)} -> {_rel(dst)}\033[0m")
    if rejected := _confirm(f"Move {_rel(src)} to {_rel(dst)}?"):
        return rejected
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    changed.add(f"{_rel(src)} -> {_rel(dst)}")
    return f"Moved {_rel(src)} to {_rel(dst)}."
