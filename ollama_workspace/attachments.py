"""Attach files whose paths appear in a message (drag-and-drop or Ctrl+V of a copied file)."""
import pathlib
import re

from . import models
from .config import READ_SHARE

# quoted paths, or unquoted ones where spaces may be escaped as "\ " (macOS drag-and-drop)
PATH_TOKEN = re.compile(r'"([^"]+)"|\'([^\']+)\'|((?:\\ |\S)+)')


def _as_file(token: str) -> pathlib.Path | None:
    token = token.lstrip("@")
    for candidate in (token, token.replace("\\ ", " ")):
        p = pathlib.Path(candidate).expanduser()
        if p.is_file():
            return p
    return None


def attach_files(text: str) -> tuple[str, list[str]]:
    """Append the contents of any existing files named in the message.
    Returns (message for the model, attached file names)."""
    blocks, names = [], []
    for m in PATH_TOKEN.finditer(text):
        p = _as_file(next(g for g in m.groups() if g))
        if p is None:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[couldn't read {p}: {e}]")
            continue
        limit = models.current.chars(READ_SHARE)
        if len(content) > limit:
            print(f"[{p.name} truncated to {limit:,} of {len(content):,} chars to fit the model]")
            content = content[:limit] + "\n...[truncated]"
        blocks.append(f"=== ATTACHED FILE: {p.name} (full contents below; no need to open it) "
                      f"===\n{content}\n=== END FILE ===")
        names.append(p.name)
    if names:
        print(f"[attached: {', '.join(names)}]")
    return ("\n\n".join([text, *blocks]) if blocks else text), names
