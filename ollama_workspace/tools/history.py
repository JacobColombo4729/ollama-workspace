"""Memory tools: search the full transcript of past conversations, save lasting project
notes, and post to the shared agent board."""
from datetime import datetime

from .. import agents, memory


def search_history(query: str, all_chats: bool = False) -> str:
    """Search the full saved transcript of past conversations AND the full project
    decisions log (every save_note ever saved, not just the recent slice shown in your
    context), including parts that are only summarized in your memory. Use it to recover
    an exact earlier detail or an older decision that's aged out of what's shown to you.

    Args:
        query: Words to look for (case-insensitive); an exchange/entry matches if it has
            all of them.
        all_chats: Also search the other chats in this project (decisions.md is always
            searched either way - it's project-wide, not per-chat).

    Returns:
        Up to 15 matching exchanges/entries with their dates, most recent last.
    """
    words = [w.lower() for w in str(query).split()]
    if not words:
        return "Error: empty query."
    every = str(all_chats).lower() in ("true", "1", "yes")
    chats = memory.list_chats(memory.active.project) if every else [memory.active]
    hits = []
    for chat in chats:
        for ex in chat.exchanges():
            low = ex.lower()
            if all(w in low for w in words):
                stamp = memory.STAMP.search(ex)
                if len(ex) > 1500:  # show the part around the first match
                    s = max(0, low.find(words[0]) - 600)
                    ex = ("..." if s else "") + ex[s:s + 1500] + "..."
                hits.append((stamp.group(1) if stamp else "",
                             f"--- chat: {chat.title} ---\n{ex.strip()}"))
    decisions_path = memory.active.project / "decisions.md"
    if decisions_path.exists():
        for line in decisions_path.read_text("utf-8").splitlines():
            low = line.lower()
            if line.strip() and all(w in low for w in words):
                stamp = memory.STAMP.search(line)
                hits.append((stamp.group(1) if stamp else "",
                             f"--- project decisions log ---\n{line.strip()}"))
    if not hits:
        return "No matches."
    shown = [h for _, h in sorted(hits, key=lambda h: h[0])][-15:]
    return f"{len(hits)} matches" + (", showing the last 15" if len(hits) > 15 else "") + \
        ":\n\n" + "\n\n".join(shown)


def save_note(note: str) -> str:
    """Save a lasting fact about this project (decision, convention, user preference) to
    the project's decisions log, which every chat in this project sees (the recent part
    directly, older entries via search_history). Use sparingly, for things that matter
    beyond this conversation. Never deleted or rewritten - a permanent, timestamped record.

    Args:
        note: One short sentence.

    Returns:
        Confirmation.
    """
    note = " ".join(str(note).split())
    with (memory.active.project / "decisions.md").open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M}] {note}\n")
    print(f"\033[2m[noted] {note}\033[0m")
    return "Saved to the project decisions log."


def post_to_board(message: str) -> str:
    """Post a short status update to this project's shared board, which every chat and
    agent here sees automatically next turn - progress, findings, or anything another
    agent working on this project should know about. Unlike save_note (lasting facts,
    used sparingly), the board is for frequent updates and only keeps the most recent ones.

    Args:
        message: One short line.

    Returns:
        Confirmation.
    """
    message = " ".join(str(message).split())
    who = agents.active.name if agents.active else memory.active.title
    with (memory.active.project / "board.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M}] {who}: {message}\n")
    print(f"\033[2m[board] {who}: {message}\033[0m")
    return "Posted to the board."
