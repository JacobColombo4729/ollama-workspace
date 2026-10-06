"""Tools for deleting files and folders, which go to the project's trash, and bringing
them back (see trash.py)."""
import os
import pathlib

from .. import config, guard, memory, trash
from .base import _confirm, _rel, _resolve, _size, changed


def delete_path(path: str) -> str:
    """Delete a file, or a folder with everything in it. It goes to the project's trash,
    so restore_deleted can bring it back.

    Args:
        path: File or folder relative to the workspace.

    Returns:
        Whether it was deleted.
    """
    p = _resolve(path)
    if not p.exists():
        return f"Error: {path} doesn't exist."
    if p == config.WORKSPACE or p == pathlib.Path(p.anchor) or p == pathlib.Path.home():
        return f"Error: can't delete {_rel(p)} (the workspace, a drive, or your home folder)."
    rel = _rel(p)
    if p.is_dir():
        n = sum(len(files) for _, _, files in os.walk(p))
        what = f"folder {rel}/ and the {n} files in it"
    else:
        what = f"{rel} ({_size(p.stat().st_size)})"
    print(f"\033[31m- {what}\033[0m")
    if rejected := _confirm(f"Delete {what}?"):
        return rejected
    trash.put(memory.active.project, p, rel)
    changed.add(f"{rel} (deleted)")
    return f"Deleted {rel} (moved to the trash; restore_deleted can bring it back)."


def list_deleted() -> str:
    """List files and folders deleted in this project that can still be restored.

    Returns:
        Numbered entries, most recently deleted first.
    """
    items = trash.entries(memory.active.project)
    return "\n".join(f"{i}. {e.describe()}" for i, e in enumerate(items, 1)) \
        or "The trash is empty."


def restore_deleted(item: str, destination: str = "") -> str:
    """Bring back a deleted file or folder. Use it when the user wants something back.

    Args:
        item: Its original path, part of that path, or its number from list_deleted.
        destination: Where to restore it, relative to the workspace; empty means its
            original location.

    Returns:
        Where it was restored.
    """
    matches = trash.find(memory.active.project, item)
    if len(matches) > 1 and len({e.path for e in matches}) > 1:
        return ("Several deleted items match; pick one by number:\n"
                + "\n".join(f"- {e.describe()}" for e in matches))
    if not matches:
        return f"Nothing in the trash matches {item}; call list_deleted to see what's there."
    entry = matches[0]  # the same path deleted more than once: the most recent copy
    target = _rel(_resolve(destination or entry.path))
    if _resolve(target).exists():
        return (f"Error: {target} already exists. Ask the user whether to restore it under "
                "another name (pass destination) or delete the current one first.")
    print(f"\033[32m+ {target}{'/' if entry.meta['folder'] else ''}  "
          f"(deleted {entry.meta['deleted']})\033[0m")
    if rejected := _confirm(f"Restore {entry.path} to {target}?"):
        return rejected
    restored = trash.restore(entry, config.WORKSPACE, target, anywhere=not guard.restricted())
    changed.add(f"{restored} (restored)")
    return f"Restored {restored}."
