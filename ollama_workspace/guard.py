"""Run modes. Every machine must pick one with the OCHAT_MODE environment variable:

    restricted   for your own computer. Commands run freely, except dangerous ones
                 (downloads, admin rights, auto-start, security changes, hidden code, ...),
                 which show why they're risky and need your password. The tool's own code
                 and data are off limits to the model, and it won't start as Administrator.
    unleashed    for a throwaway VM. No restrictions.
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

from .config import DATA_DIR, ROOT

MODES = ("restricted", "unleashed")
mode = ""  # set by init()

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
DANGEROUS = [
    (rf"({_DL}).*(\|\s*{_RUN}|[;&\n].*(\bStart-Process\b|\bstart\b|&\s*['\"]?\.{{0,2}}[\\/]|"
     r"\.[\\/]\S+\.(exe|ps1|bat|cmd|sh|py|msi)\b))",
     "downloads something from the internet and runs it right away, without you "
     "seeing what it is. This is the most common way malware gets in."),
    (_DL,
     "downloads from the internet. A download can bring in malware, and the same tools "
     "can upload your files somewhere."),
    (r"\brunas\b|-Verb\s+['\"]?RunAs|\bg?sudo\b",
     "asks for Administrator rights. With them a command can change anything on the "
     "computer, including security settings and other users' files."),
    (r"\bschtasks\b|Register-ScheduledTask|New-ScheduledTask|New-Service|"
     r"\bsc(\.exe)?\s+(create|config)\b|Register-WmiEvent|__EventFilter|"
     r"Start Menu[\\/]Programs[\\/]Startup|shell:startup|\$PROFILE",
     "sets something up to run automatically (at startup, on a schedule, or in every "
     "PowerShell session). That's how malware survives a restart."),
    (r"\breg(\.exe)?\s+(add|delete|import|load|restore)\b|\b(HKLM|HKCU|HKEY_\w+)\b|"
     r"(New|Set|Remove)-ItemProperty",
     "changes the Windows registry, which controls startup programs, security settings "
     "and how Windows behaves."),
    (r"Set-MpPreference|Add-MpPreference|\bnetsh\b.*\b(advfirewall|firewall)\b|"
     r"(Set|New|Remove|Disable)-NetFirewall|\bbcdedit\b|Set-ExecutionPolicy|"
     r"\bvssadmin\b|\bwbadmin\b|\bwevtutil\b.*\bcl\b|Clear-EventLog|\bcipher\b.*/w",
     "changes Windows security settings, backups or logs (Defender, firewall, boot, "
     "script policy). Disabling these is a typical first step of an attack."),
    (r"\bnet(\.exe)?\s+(user|localgroup)\b|(New|Add|Set)-Local(User|GroupMember)",
     "creates or changes user accounts or their permissions."),
    (r"\bcmdkey\b|\bvaultcmd\b|mimikatz|\blsass\b|[\\/]SAM\b|\.ssh\b|\bid_(rsa|ed25519|ecdsa)\b|"
     r"Login Data|[\\/]Cookies\b|\.aws[\\/]|\.git-credentials|ConvertFrom-SecureString",
     "touches saved passwords, keys or browser logins, which could be stolen."),
    (r"-(e|ec|en|enc|enco|encodedcommand)\s+[A-Za-z0-9+/=]{16,}|FromBase64String|"
     r"\bbase64\s+(-d|--decode)\b|\b(iex|Invoke-Expression)\b|\[ScriptBlock\]::Create",
     "runs hidden or encoded code, so you can't read what it really does."),
    (r"\b(python3?|py|node|perl|ruby)(\.exe)?\s+(-[\w-]+\s+)*-[ce]\b|"
     r"\b(powershell|pwsh)(\.exe)?\b|\bcmd(\.exe)?\s+/[ck]\b|\b(bash|sh|wsl)(\.exe)?\s+-c\b",
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
    """Read the mode; quit with instructions if it's missing, and enforce restricted's
    startup rules."""
    global mode
    raw = os.environ.get("OCHAT_MODE") or _saved_mode()
    mode = raw.strip().lower()
    if mode not in MODES:
        got = f"OCHAT_MODE is '{raw}'" if raw else "OCHAT_MODE isn't set"
        sys.exit(f"{got}. Choose a mode for this computer:\n"
                 "  setx OCHAT_MODE restricted     your own computer: dangerous commands "
                 "need a password\n"
                 "  setx OCHAT_MODE unleashed      a throwaway VM: no restrictions\n"
                 "then run ochat again. (macOS/Linux: add 'export OCHAT_MODE=restricted' "
                 "to your shell profile and open a new terminal.)")
    if restricted():
        if _is_admin():
            sys.exit("Restricted mode won't run as Administrator: commands would inherit "
                     "admin rights. Start ochat from a normal (non-elevated) terminal.")
        if not PASSWORD_FILE.exists():
            _set_password()


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
    if restricted():
        return ("RESTRICTED: commands run freely, but dangerous ones (downloads, admin "
                "rights, auto-start, security or registry changes, hidden or inline code, "
                "touching passwords or keys) need your password. The tool's own code is "
                "off limits, secrets are removed from commands' environment, and deletes "
                "go to the trash.")
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
    print("Restricted mode: set a password for approving dangerous commands.\n"
          "(Only a salted hash is stored, in data/password.json. Forgot it? Delete that "
          "file and you'll be asked for a new one.)")
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
    try:
        stored = json.loads(PASSWORD_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        print("[the password file is missing or damaged; restart ochat to set a new one]")
        return False
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
    if found and found[0] == DANGEROUS[0][1]:
        found.remove(DANGEROUS[1][1])  # download-and-run already says it downloads
    low = command.lower()
    overlap = _inside(workspace, ROOT) or _inside(ROOT, workspace)
    # with no overlap, any mention of the tool's folder is suspicious; with overlap, only
    # its code and data (the rest is ordinary workspace)
    own = PROTECTED + [DATA_DIR] if overlap else [ROOT]
    if any(str(p).lower() in low or p.as_posix().lower() in low for p in own) or \
            (overlap and OWN_NAMES.search(command)):
        found.append("touches this chat tool's own code or data, which could switch off "
                     "these protections.")
    if CHANGE_VERB.search(command):
        outside = [m for m in ABS_PATH.findall(command)
                   if not _inside(Path(m).expanduser().resolve(), workspace)]
        if outside or HOME_REF.search(command):
            where = ", ".join(outside[:3]) or "your user folder"
            found.append(f"changes, moves or deletes files outside the workspace ({where}).")
    return found


def approve(command: str, reasons: list[str]) -> bool:
    """Show why the command is dangerous and ask for the password."""
    print("\033[1;33m!! RESTRICTED: this command needs your password\033[0m")
    for i, why in enumerate(reasons):
        print(f"  {'Why:' if i == 0 else '    '} {why}")
    return _password_ok()


def command_env() -> dict:
    """The environment commands run with: secrets removed in restricted mode."""
    if not restricted():
        return dict(os.environ)
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
