"""Run modes, set with the OCHAT_MODE environment variable. Defaults to restricted if it's
never been set, so a new machine doesn't need any setup to start safely:

    restricted   the default; for your own computer. Commands run freely, except dangerous
                 ones (downloads, admin rights, auto-start, security changes, hidden code,
                 ...), which show why they're risky and need your password. The tool's own
                 code and data are off limits to the model, and it won't start as
                 Administrator.
    unleashed    for a throwaway VM. No restrictions. Must be set explicitly - it's never
                 the default.
"""
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from pathlib import Path

from . import config, memory, scope
from .config import DATA_DIR, ROOT

MODES = ("restricted", "unleashed")
mode = ""  # set by init()
# /unlock: let the model see and edit this tool's own code for the rest of the session
# (restricted mode asks the password first). Chat data and the password stay off limits.
self_edit = False

PASSWORD_FILE = DATA_DIR / "password.json"
ITERATIONS = 300_000

# the tool's own code: hidden from the model in restricted mode, even when it's the workspace
PROTECTED = [ROOT / "ollama_workspace", ROOT / "chat.py", ROOT / "ochat", ROOT / "ochat.bat"]
# names of the tool's own files, for commands that use relative paths when the workspace is
# (or contains) the tool's folder; read from disk so new modules are covered automatically
OWN_NAMES = re.compile(r"\b(" + "|".join(sorted(
    {re.escape(p.name) for p in (ROOT / "ollama_workspace").rglob("*.py")}
    | {"ollama_workspace", r"chat\.py", "ochat", r"ochat\.bat", "tools"})) + r")\b",
    re.IGNORECASE)

# environment variables kept from commands in restricted mode, so a script can't read them
SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE|"
                        r"CREDENTIAL|^AWS_|^AZURE_|^GH_|^GITHUB_|^OPENAI|^ANTHROPIC|^HF_",
                        re.IGNORECASE)

_DL = (r"\b(iwr|irm|curl|wget|Invoke-WebRequest|Invoke-RestMethod|Start-BitsTransfer|"
       r"bitsadmin|DownloadString|DownloadFile|DownloadData)\b|Net\.WebClient|"
       r"certutil(\.exe)?\b.*-urlcache")
_RUN = r"\b(iex|Invoke-Expression|sh|bash|python3?|py|node|powershell|pwsh|cmd)\b"

# (pattern, why it needs your password); checked case-insensitively against the command
# A plain download (curl/wget/iwr to read or save a file) isn't gated on its own - that's
# normal dev work (hitting an API, fetching a dataset or model). Only downloading something
# and running it, which is how malware actually gets in, needs your password.
DANGEROUS = [
    (rf"({_DL}).*(\|\s*{_RUN}|[;&\n].*(\bStart-Process\b|\bstart\b|&\s*['\"]?\.{{0,2}}[\\/]|"
     r"\.[\\/]\S+\.(exe|ps1|bat|cmd|sh|py|msi)\b))",
     "downloads something from the internet and runs it right away, without you "
     "seeing what it is. This is the most common way malware gets in."),
    (r"\brunas\b|-Verb\s+['\"]?RunAs|\bg?sudo\b",
     "asks for Administrator rights. With them a command can change anything on the "
     "computer, including security settings and other users' files."),
    # write/enable verbs only, same reasoning as the registry check below - "crontab -l",
    # "cat ~/.bashrc" or "ls ~/Library/LaunchAgents" are common and harmless; only adding
    # a job, loading a launch agent, enabling a service, or writing into a profile file
    # needs your password.
    (r"\bschtasks\b|Register-ScheduledTask|New-ScheduledTask|New-Service|"
     r"\bsc(\.exe)?\s+(create|config)\b|Register-WmiEvent|__EventFilter|"
     r"Start Menu[\\/]Programs[\\/]Startup|shell:startup|\$PROFILE|"
     r"\bcrontab\b(?!\s*-l\b)|[\\/]etc[\\/]cron|"
     r"\blaunchctl\b\s+(load|bootstrap|enable)|systemctl\s+(enable|start)|"
     r">>?\s*[\"']?(~|\$HOME|\$env:HOME)?[\\/]?\.?(bashrc|bash_profile|zshrc|zprofile|profile)\b|"
     r"\bsed\b.*-i.*\.(bashrc|bash_profile|zshrc|zprofile)\b",
     "sets something up to run automatically (at startup, on a schedule, in every shell "
     "session, or in every PowerShell session). That's how malware survives a restart."),
    # write verbs only - reading the registry (reg query, Get-ItemProperty, Test-Path
    # HKLM:\...) is common and harmless; only changing it needs your password.
    (r"\breg(\.exe)?\s+(add|delete|import|load|restore)\b|(New|Set|Remove)-ItemProperty",
     "changes the Windows registry, which controls startup programs, security settings "
     "and how Windows behaves."),
    (r"Set-MpPreference|Add-MpPreference|\bnetsh\b.*\b(advfirewall|firewall)\b|"
     r"(Set|New|Remove|Disable)-NetFirewall|\bbcdedit\b|Set-ExecutionPolicy|"
     r"\bvssadmin\b|\bwbadmin\b|\bwevtutil\b.*\bcl\b|Clear-EventLog|\bcipher\b.*/w|"
     r"\bufw\s+disable|\biptables\b.*(-F|--flush)|\bpfctl\b.*-d|\bcsrutil\s+disable|"
     r"\bspctl\s+--master-disable|\bsetenforce\s+0|journalctl\b.*--vacuum",
     "changes security settings, backups or logs (Defender/firewall/ufw/iptables, boot or "
     "script policy, SIP, Gatekeeper, SELinux, logs). Disabling these is a typical first "
     "step of an attack."),
    (r"\bnet(\.exe)?\s+(user|localgroup)\b|(New|Add|Set)-Local(User|GroupMember)|"
     r"\buser(add|del|mod)\b|\bgroup(add|del|mod)\b|\bvisudo\b|[\\/]etc[\\/]sudoers|"
     r"\bdscl\b|\bsysadminctl\b|\bdseditgroup\b",
     "creates or changes user accounts, groups, or who's allowed to use sudo."),
    (r"\bcmdkey\b|\bvaultcmd\b|mimikatz|\blsass\b|[\\/]SAM\b|\.ssh\b|\bid_(rsa|ed25519|ecdsa)\b|"
     r"Login Data|[\\/]Cookies\b|\.aws[\\/]|\.git-credentials|ConvertFrom-SecureString|"
     r"\bsecurity\s+(find-\w+-password|dump-keychain|unlock-keychain)\b|"
     r"[\\/]etc[\\/]shadow\b|\.netrc\b|\bsecret-tool\b",
     "touches saved passwords, keys or browser logins (including the macOS Keychain, "
     "/etc/shadow, or .netrc), which could be stolen."),
    (r"-(e|ec|en|enc|enco|encodedcommand)\s+[A-Za-z0-9+/=]{16,}|FromBase64String|"
     r"\bbase64\s+(-d|--decode)\b|\b(iex|Invoke-Expression)\b|\[ScriptBlock\]::Create",
     "runs hidden or encoded code, so you can't read what it really does."),
    # requires an actual invocation flag, not just the word appearing (e.g. in a path or a
    # sentence) - a bare "powershell" mention is common and not itself risky.
    (r"\b(python3?|py|node|perl|ruby)(\.exe)?\s+(-[\w-]+\s+)*-[ce]\b|"
     r"\b(powershell|pwsh)(\.exe)?\b.*-(c|command|encodedcommand|file)\b|"
     r"\bcmd(\.exe)?\s+/[ck]\b|\b(bash|sh|wsl)(\.exe)?\s+-c\b",
     "runs a code snippet or a second shell inline, which can do anything and gets "
     "around these checks."),
    (r"OCHAT_MODE|\bsetx\b|SetEnvironmentVariable|password\.json",
     "changes environment settings, which could switch this tool to unleashed mode or "
     "reset its password."),
    (r"core\.hooksPath|\.git[\\/]hooks|\bgit\b.*\s-c\s+\S*(hooks|alias|sshCommand|editor|pager)",
     "changes git hooks or git settings that make ordinary git commands run other programs."),
    (r"\bformat(\.com)?\s+[a-z]:|\bdiskpart\b|Format-Volume|Clear-Disk|Initialize-Disk|"
     r"\bshutdown\b|Stop-Computer|Restart-Computer",
     "formats disks or shuts the computer down."),
]
DANGEROUS = [(re.compile(p, re.IGNORECASE), why) for p, why in DANGEROUS]

ABS_PATH = re.compile(r"(?<![\w.])([A-Za-z]:[\\/][^\s\"';|&<>]*|\\\\[^\s\"';|&<>]+)")
HOME_REF = re.compile(r"(^|[\s\"'(=])(~|\$HOME|\$env:USERPROFILE|%USERPROFILE%|\$env:APPDATA|"
                      r"%APPDATA%|\$env:LOCALAPPDATA|%LOCALAPPDATA%)", re.IGNORECASE)
CHANGE_VERB = re.compile(r"\b(rm|rmdir|rd|del|erase|Remove-Item|ri|mv|move|Move-Item|"
                         r"Rename-Item|ren|cp|copy|Copy-Item|robocopy|xcopy|Set-Content|"
                         r"Add-Content|Out-File|New-Item|Clear-Content)\b|>", re.IGNORECASE)


def restricted() -> bool:
    return mode == "restricted"


def _inside(p: Path, folder: Path) -> bool:
    return p == folder or folder in p.parents


def init() -> None:
    """Read the mode, defaulting to restricted if it's never been set (so a fresh machine
    starts safely with no setup); quit only if it's set to something that isn't a mode.
    Then enforce restricted's startup rules. No password is required just to start - it's
    only ever asked for (and set, the first time) when a dangerous action actually needs
    approving, so an ordinary session that never hits one needs no setup at all."""
    global mode
    raw = os.environ.get("OCHAT_MODE") or _saved_mode()
    mode = (raw or "restricted").strip().lower()
    if mode not in MODES:
        sys.exit(f"OCHAT_MODE is '{raw}', which isn't a mode. Use:\n"
                 "  setx OCHAT_MODE restricted     your own computer: dangerous commands "
                 "need a password (this is the default if OCHAT_MODE is unset)\n"
                 "  setx OCHAT_MODE unleashed      a throwaway VM: no restrictions\n"
                 "then run ochat again. (macOS/Linux: add 'export OCHAT_MODE=...' to your "
                 "shell profile and open a new terminal.)")
    if restricted() and _is_admin():
        sys.exit("Restricted mode won't run as Administrator: commands would inherit "
                 "admin rights. Start ochat from a normal (non-elevated) terminal.")


def _saved_mode() -> str:
    """On Windows, `setx` saves OCHAT_MODE for terminals opened later but not the current
    one, so read the saved value directly instead of making you open a new terminal."""
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, "OCHAT_MODE")[0])
    except OSError:
        return ""


def describe() -> str:
    code = ("UNLOCKED for this session (/lock to undo): the model can edit this tool's own "
            "code." if self_edit else "The tool's own code is off limits (/unlock to edit it).")
    if restricted():
        return ("RESTRICTED: commands run freely, but dangerous ones (downloads, admin "
                "rights, auto-start, security or registry changes, hidden or inline code, "
                "touching passwords or keys) need your password. " + code + " Secrets are "
                "removed from commands' environment, and deletes go to the trash.")
    return "UNLEASHED: no restrictions. Use only in a VM you can throw away."


def _is_admin() -> bool:
    if os.name == "nt":
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except OSError:
            return False
    return os.geteuid() == 0


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex()


def _set_password() -> None:
    print("No password set yet. This approves this and future dangerous actions, so set "
          "one now.\n(Only a salted hash is stored, in data/password.json. Forgot it? "
          "Delete that file and you'll be asked for a new one.)")
    while True:
        first = getpass.getpass("New password: ")
        if len(first) < 4:
            print("Use at least 4 characters.")
        elif getpass.getpass("Repeat it: ") != first:
            print("They don't match; try again.")
        else:
            break
    salt = secrets.token_bytes(16)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PASSWORD_FILE.write_text(json.dumps({"salt": salt.hex(), "hash": _hash(first, salt),
                                         "iterations": ITERATIONS}), "utf-8")
    print("Password saved.\n")


def _password_ok(attempts: int = 3) -> bool:
    if not PASSWORD_FILE.exists():
        # first dangerous action this install has ever hit: set the password right here,
        # instead of demanding one at startup whether or not it turns out to be needed
        _set_password()
        return True  # just set and confirmed it (typed twice); no need to type it a third time
    try:
        stored = json.loads(PASSWORD_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        print("[the password file is damaged; setting a new one]")
        _set_password()
        return True
    salt = bytes.fromhex(stored["salt"])
    for left in range(attempts, 0, -1):
        typed = getpass.getpass("Password (Enter to cancel): ")
        if not typed:
            return False
        if hmac.compare_digest(_hash(typed, salt), stored["hash"]):
            return True
        print(f"Wrong password{f'; {left - 1} tries left' if left > 1 else ''}.")
    return False


def risks(command: str, workspace: Path) -> list[str]:
    """Why this command is dangerous; empty if it's an ordinary command."""
    found = [why for rx, why in DANGEROUS if rx.search(command)]
    low = command.lower()
    overlap = _inside(workspace, ROOT) or _inside(ROOT, workspace)
    # with no overlap, any mention of the tool's folder is suspicious; with overlap, only
    # its code and data (the rest is ordinary workspace)
    if self_edit:  # /unlock: the code is fair game, but chats and the password aren't
        own, by_name = [DATA_DIR], False
    else:
        own, by_name = (PROTECTED + [DATA_DIR] if overlap else [ROOT]), overlap
    if any(str(p).lower() in low or p.as_posix().lower() in low for p in own) or \
            (by_name and OWN_NAMES.search(command)):
        found.append("touches this chat tool's own code or data, which could switch off "
                     "these protections.")
    if CHANGE_VERB.search(command):
        outside = [m for m in ABS_PATH.findall(command)
                   if not _inside(Path(m).expanduser().resolve(), workspace)]
        if outside or HOME_REF.search(command):
            where = ", ".join(outside[:3]) or "your user folder"
            found.append(f"changes, moves or deletes files outside the workspace ({where}).")
    # only checked at all once a project has defined a scope (see scope.py) - an ordinary,
    # non-pentest project never hits this
    project = memory.project_dir(config.WORKSPACE)
    if out := scope.out_of_scope(command, project):
        found.append(f"touches a target outside this project's defined scope: "
                     f"{', '.join(out[:3])}. /scope add it first if it's authorized.")
    return found


def approve(command: str, reasons: list[str], what: str = "this command") -> bool:
    """Show why the action is dangerous and ask for the password."""
    print(f"\033[1;33m!! RESTRICTED: {what} needs your password\033[0m")
    for i, why in enumerate(reasons):
        print(f"  {'Why:' if i == 0 else '    '} {why}")
    return _password_ok()


def command_env() -> dict:
    """The environment commands run with: secrets removed in restricted mode."""
    if not restricted():
        return dict(os.environ)
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
