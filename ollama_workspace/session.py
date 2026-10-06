"""Which chat and model are in use: listing, finding, opening and switching chats, and
choosing the model."""
import shutil

from . import memory, models
from .stream import describe_thinking


def print_chats(chats: list) -> None:
    if not chats:
        print("No chats yet in this project.")
    for i, c in enumerate(chats, 1):
        mark = "*" if memory.active and c.dir == memory.active.dir else " "
        print(f"{mark}{i:>3}. {c.title}  ({len(c.exchanges())} messages, {c.meta['updated']})")


def drop_if_empty(chat) -> None:
    """Don't keep unnamed chats that never got a message."""
    if chat is not None and not chat.meta["title"] and not chat.log().strip():
        shutil.rmtree(chat.dir, ignore_errors=True)


def set_model(name: str) -> None:
    m = models.use(name)
    print(f"Model: {m.describe()}")
    if m.thinking:
        print(f"\033[2m[{describe_thinking()}; change with /think]\033[0m")
    if not m.tools:
        print("\033[2m[this model can't use tools: file editing, history search and notes "
              "are off]\033[0m")
    if memory.active is not None:
        memory.active.meta["model"] = name  # each chat remembers its model
        memory.active.save()


def switch_to(chat, adopt_model: bool = True) -> None:
    if memory.active is not None and memory.active.dir != chat.dir:
        drop_if_empty(memory.active)
    memory.active = chat
    n = len(chat.exchanges())
    print(f"Chat: {chat.title}" + (f" ({n} messages)" if n else " (new)"))
    want = chat.meta.get("model")
    if adopt_model and want and (models.current is None or want != models.current.name):
        if want in models.installed:
            set_model(want)
        else:
            print(f"\033[2m[this chat used {want}, which isn't installed]\033[0m")
    if models.current is not None:
        chat.compact_if_needed()  # handles an already-large log (needs a model)


def clean_name(text: str) -> str:
    """Normalize a typed chat name: single spaces, and no surrounding quotes, so
    /rename "my chat" gives the same name as `ochat "my chat"` (where the shell drops them)."""
    text = " ".join(text.split())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def named(chats: list, name: str):
    """The chat whose name matches exactly (ignoring case), or None."""
    return next((c for c in chats if clean_name(c.meta["title"]).lower() == name.lower()), None)


def find_chat(chats: list, ref: str):
    """Find a chat by its /chats number, exact name, or a unique part of its name."""
    if ref.isdigit() and 1 <= int(ref) <= len(chats):
        return chats[int(ref) - 1]
    if chat := named(chats, ref):
        return chat
    partial = [c for c in chats if ref.lower() in c.meta["title"].lower()]
    if len(partial) == 1:
        return partial[0]
    print(f"{'Several chats match' if partial else 'No chat matches'} '{ref}'; see /chats.")
    return None


def open_named(project, name: str) -> None:
    """Switch to the chat with this name, or start one with it."""
    if chat := named(memory.list_chats(project), name):
        print(f"[opening existing chat '{chat.title}']")
        switch_to(chat)
    else:
        switch_to(memory.Chat.create(project, name))
