"""Tools the model can call. ollama builds each tool's schema from its signature and
docstring, so the docstrings are what the model reads.

    base.py      shared: workspace limits, hidden paths, approvals, reading files
    browse.py    list_dir, list_files, find_files, search_files, file_outline, read_file
    edit.py      edit_file, write_file, make_dir, move_path
    deleting.py  delete_path, list_deleted, restore_deleted (via the trash)
    shell.py     run_command
    history.py   search_history, save_note
"""
from .base import changed, state
from .browse import file_outline, find_files, list_dir, list_files, read_file, search_files
from .deleting import delete_path, list_deleted, restore_deleted
from .edit import edit_file, make_dir, move_path, write_file
from .history import save_note, search_history
from .shell import SHELL, run_command, shell_args

__all__ = ["TOOLS", "SHELL", "active", "changed", "run_tool", "shell_args", "state"]


TOOLS = [list_dir, list_files, find_files, search_files, file_outline, read_file, edit_file,
         write_file, make_dir, move_path, delete_path, list_deleted, restore_deleted,
         run_command, search_history, save_note]


def active() -> list:
    """The tools the model gets in the current mode."""
    return TOOLS


def run_tool(call) -> str:
    name, args = call.function.name, dict(call.function.arguments or {})
    if name == "run_command":  # run_command prints the command itself
        target = ""
    elif "source" in args:
        target = f"{args['source']} -> {args.get('destination', '')}"
    else:
        target = (args.get("pattern") or args.get("path") or args.get("query")
                  or args.get("item") or "")
    if "start_line" in args or "end_line" in args:
        target += f" [{args.get('start_line', 1)}-{args.get('end_line') or 'end'}]"
    print(f"\033[36m[{name}] {target}\033[0m", flush=True)
    fn = {f.__name__: f for f in active()}.get(name)
    if fn is None:
        return f"Error: unknown tool {name}"
    try:
        return fn(**args)
    except Exception as e:  # report back to the model instead of crashing the chat
        return f"Error: {e}"
