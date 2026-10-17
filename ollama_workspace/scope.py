"""Engagement scope for authorized security testing: an explicit, per-project list of
target hosts/ranges/domains. When a project has one defined, restricted mode's
dangerous-command gate (guard.py) also flags any run_command that mentions a target
outside it - a typo'd IP or a hallucinated host doesn't get to run quietly.

data/projects/<project>/scope.txt   one target per line: an IP, a CIDR range (10.0.0.0/24),
                                     a hostname, or a wildcard domain (*.example.com)

Empty or missing (the default for every project) means no scope is defined, so nothing is
checked - this only ever adds friction to a project where you've deliberately set one.
Best-effort, like the rest of guard.py's checks: it reads the command text, so it's a
speed bump against typos and hallucinated targets, not a network-level enforcement wall.
"""
import ipaddress
import re
from pathlib import Path

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
# hostname/domain-looking tokens; common file extensions are excluded so "config.py" or
# "app.js" in an ordinary command isn't mistaken for a target
_NOT_HOST_EXT = {"py", "js", "ts", "json", "md", "txt", "exe", "sh", "bat", "ps1", "yml",
                 "yaml", "toml", "cfg", "ini", "log", "csv", "html", "css", "ps", "ipynb",
                 "jsx", "tsx", "go", "rs", "c", "cpp", "h", "java", "rb", "php", "sql",
                 "xml", "lock", "env", "gitignore", "dockerfile", "mjs", "cjs"}
_HOSTNAME = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")


def path(project: Path) -> Path:
    return project / "scope.txt"


def targets(project: Path) -> list[str]:
    """The project's defined scope, one entry per line; empty if none is set."""
    p = path(project)
    if not p.exists():
        return []
    return [line.strip() for line in p.read_text("utf-8").splitlines() if line.strip()]


def add(project: Path, target: str) -> None:
    with path(project).open("a", encoding="utf-8") as f:
        f.write(target.strip() + "\n")


def remove(project: Path, ref: str) -> str | None:
    """Remove by number (from /scope's listing) or exact text. Returns what was removed,
    or None if nothing matched."""
    items = targets(project)
    if ref.isdigit() and 1 <= int(ref) <= len(items):
        removed = items.pop(int(ref) - 1)
    elif ref in items:
        items.remove(ref)
        removed = ref
    else:
        return None
    path(project).write_text("\n".join(items) + ("\n" if items else ""), "utf-8")
    return removed


def clear(project: Path) -> None:
    path(project).write_text("", "utf-8")


def extract_candidates(command: str) -> list[str]:
    """IP addresses/ranges and hostname-looking tokens mentioned in a command - the things
    worth checking against scope."""
    found = set(_IPV4.findall(command))
    for m in _HOSTNAME.finditer(command):
        token = m.group(0)
        if token.rsplit(".", 1)[-1].lower() not in _NOT_HOST_EXT:
            found.add(token)
    return sorted(found)


def covers(entry: str, candidate: str) -> bool:
    """Whether one scope entry covers one candidate target: an exact match, a *.domain
    wildcard, or (for IPs) falling inside a CIDR range."""
    if entry == candidate:
        return True
    if entry.startswith("*.") and candidate.endswith(entry[1:]):
        return True
    try:
        return ipaddress.ip_address(candidate) in ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return False


def out_of_scope(command: str, project: Path) -> list[str]:
    """Candidate targets in `command` that aren't covered by any entry in this project's
    scope. Empty if the project has no scope defined at all (nothing to check against) or
    every mentioned target is covered."""
    allowed = targets(project)
    if not allowed:
        return []
    return [c for c in extract_candidates(command) if not any(covers(e, c) for e in allowed)]
