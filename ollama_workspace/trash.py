"""Deleted files go to a per-project trash instead of disappearing, so they can be restored.

data/projects/<project>/trash/<id>/
    item.json        original path (relative to the workspace), deletion time, file or folder
    item/<name>      the deleted file or folder itself

Entries older than TRASH_DAYS are removed for good when a chat starts.
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import TRASH_DAYS


def _force_remove(func, path, _exc) -> None:
    """Windows won't delete read-only files (e.g. inside .git) until the flag is cleared."""
    os.chmod(path, 0o700)
    func(path)


def remove_tree(p: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=_force_remove)
    else:
        shutil.rmtree(p, onerror=_force_remove)


def _move(src: Path, dst: Path) -> None:
    """Rename when possible; across drives, copy then remove (read-only files included)."""
    try:
        os.rename(src, dst)
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
            remove_tree(src)
        else:
            shutil.copy2(src, dst)
            os.chmod(src, 0o700)
            src.unlink()


class Entry:
    def __init__(self, folder: Path):
        self.dir = folder
        self.meta = json.loads((folder / "item.json").read_text("utf-8"))

    @property
    def path(self) -> str:
        return self.meta["path"]

    @property
    def item(self) -> Path:
        return self.dir / "item" / Path(self.path).name

    def describe(self) -> str:
        kind = "/" if self.meta["folder"] else ""
        return f"{self.path}{kind}  (deleted {self.meta['deleted']})"


def _root(project: Path) -> Path:
    return project / "trash"


def put(project: Path, p: Path, rel: str) -> None:
    """Move p (at workspace path rel) into the trash."""
    folder = _root(project) / f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    (folder / "item").mkdir(parents=True)
    try:
        _move(p, folder / "item" / p.name)
    except BaseException:
        if not (folder / "item" / p.name).exists():
            shutil.rmtree(folder, ignore_errors=True)  # nothing moved: no empty entry
        raise
    # written last, so a half-finished move never shows up as a restorable entry
    (folder / "item.json").write_text(json.dumps({
        "path": rel, "deleted": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "folder": (folder / "item" / p.name).is_dir()}, indent=2), "utf-8")


def entries(project: Path) -> list[Entry]:
    """Trashed items, most recently deleted first."""
    root = _root(project)
    if not root.is_dir():
        return []
    found = [Entry(d) for d in root.iterdir() if (d / "item.json").exists()]
    return sorted(found, key=lambda e: e.dir.name, reverse=True)


def find(project: Path, ref: str) -> list[Entry]:
    """Entries matching a /trash number, an exact original path, or part of one."""
    items = entries(project)
    ref = str(ref).strip().strip("\"'").replace("\\", "/").rstrip("/")
    if ref.isdigit() and 1 <= int(ref) <= len(items):
        return [items[int(ref) - 1]]
    exact = [e for e in items if e.path.lower() == ref.lower()]
    return exact or [e for e in items if ref.lower() in e.path.lower()]


def restore(entry: Entry, workspace: Path, rel: str | None = None,
            anywhere: bool = False) -> str:
    """Put an entry back at its original path (or at rel; absolute paths allowed with
    anywhere). Returns the restored path."""
    rel = rel or entry.path
    target = (workspace / rel).resolve()
    inside = target == workspace or workspace in target.parents
    if not inside and not anywhere:
        raise ValueError(f"{rel} is outside the workspace")
    if target.exists():
        raise FileExistsError(f"{rel} already exists; restore it under another name")
    target.parent.mkdir(parents=True, exist_ok=True)
    _move(entry.item, target)
    shutil.rmtree(entry.dir, ignore_errors=True)
    return target.relative_to(workspace).as_posix() if inside else target.as_posix()


def purge_old(project: Path) -> None:
    cutoff = time.time() - TRASH_DAYS * 86400
    for e in entries(project):
        if e.dir.stat().st_mtime < cutoff:
            remove_tree(e.dir)


def empty(project: Path) -> int:
    items = entries(project)
    for e in items:
        remove_tree(e.dir)
    return len(items)
