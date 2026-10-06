"""Memory tools: search the full transcript of past conversations, and save lasting
project notes."""
from .. import memory


def search_history(query: str, all_chats: bool = False) -> str:
    """Search the full saved transcript of past conversations, including parts that are
    only summarized in your memory. Use it to recover exact earlier details.

    Args:
        query: Words to look for (case-insensitive); an exchange matches if it has all of them.
        all_chats: Also search the other chats in this project.

    Returns:
        Up to 15 matching exchanges with their dates, most recent last.
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
    if not hits:
        return "No matches."
    shown = [h for _, h in sorted(hits, key=lambda h: h[0])][-15:]
    return f"{len(hits)} matches" + (", showing the last 15" if len(hits) > 15 else "") + \
        ":\n\n" + "\n\n".join(shown)


def save_note(note: str) -> str:
    """Save a lasting fact about this project (decision, convention, user preference) to the
    project notes that every chat in this project sees. Use sparingly, for things that matter
    beyond this conversation.

    Args:
        note: One short sentence.

    Returns:
        Confirmation.
    """
    note = " ".join(str(note).split())
    with (memory.active.project / "notes.md").open("a", encoding="utf-8") as f:
        f.write(f"- {note}\n")
    print(f"\033[2m[noted] {note}\033[0m")
    return "Saved to project notes."
