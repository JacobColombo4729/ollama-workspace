"""The run_command tool. In restricted mode dangerous commands need the user's password
(see guard.py); in unleashed mode commands ask first only when approvals are on."""
import os
import subprocess

from .. import config, guard, models
from ..config import COMMAND_TIMEOUT, MAX_COMMAND_TIMEOUT, READ_SHARE
from .base import _confirm, _rel, _resolve, _tail, changed


# PowerShell on Windows, so the model can use the same commands it would in a terminal there
SHELL = "PowerShell" if os.name == "nt" else os.environ.get("SHELL", "/bin/sh")


def shell_args(command: str) -> list[str]:
    return (["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
            if os.name == "nt" else [SHELL, "-c", command])


def run_command(command: str, cwd: str = ".", timeout: int = 0) -> str:
    """Run a shell command and wait for it to finish, e.g. tests, a script, git, a build, or
    installing packages. Don't use it to read, search, or edit files: the file tools do that
    better. It waits for the command to finish, so don't start servers or other programs
    that keep running.

    Args:
        command: The command line to run.
        cwd: Folder to run it in, relative to the workspace.
        timeout: Seconds to wait before stopping it; 0 means the default (5 minutes).
            Raise it for long builds or installs (max 1 hour).

    Returns:
        The exit code and the command's output (long output keeps its end).
    """
    limit_s = min(int(timeout or 0) or COMMAND_TIMEOUT, MAX_COMMAND_TIMEOUT)
    folder = _resolve(cwd)
    if not folder.is_dir():
        return f"Error: {cwd} is not a folder."
    print(f"\033[33m$ {command}\033[0m" + (f"\033[2m  (in {_rel(folder)})\033[0m"
                                           if folder != config.WORKSPACE else ""))
    if guard.restricted():
        # ordinary commands run freely; dangerous ones need the user's password
        if (reasons := guard.risks(command, folder)) and not guard.approve(command, reasons):
            return ("Not run: this command needs the user's password in restricted mode and "
                    "they didn't approve it. Don't try to get the same result another way; "
                    "ask the user if it's needed.")
    elif rejected := _confirm("Run this command?"):
        return rejected
    try:
        result = subprocess.run(shell_args(command), cwd=folder, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, timeout=limit_s,
                                env=guard.command_env())
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return (f"Timed out after {limit_s}s and was stopped. Pass a larger timeout if it "
                "needs longer.\n" + _tail(out, 4000))
    out = (result.stdout or "") + (f"\n[stderr]\n{result.stderr}" if result.stderr.strip() else "")
    limit = models.current.chars(READ_SHARE) // 2
    shown = _tail(out.strip(), limit) or "(no output)"
    if out.strip():
        print(f"\033[2m{_tail(out.strip(), 2000)}\033[0m")
    changed.add(f"$ {command}")
    return f"Exit code {result.returncode}\n{shown}"
