"""memory.py: compaction thresholds. The summarizer/merger are stubbed (monkeypatched) so
no model call happens; MAX_RECENT/KEEP_RECENT/SUMMARY_BUDGET are monkeypatched to tiny
values so a handful of short exchanges is enough to cross them."""
from ollama_workspace import memory


def test_compact_if_needed_does_nothing_below_threshold(isolated_project, monkeypatch):
    _, project = isolated_project
    monkeypatch.setattr(memory, "MAX_RECENT", 10_000)
    chat = memory.Chat.create(project, title="t")
    chat.append("hi", "hello back")

    chat.compact_if_needed()

    assert chat.meta["upto"] == 0
    assert chat.meta["summaries"] == []


def test_compact_if_needed_summarizes_past_max_recent(isolated_project, monkeypatch):
    _, project = isolated_project
    monkeypatch.setattr(memory, "_summarize", lambda piece: "SUMMARY")
    monkeypatch.setattr(memory, "MAX_RECENT", 50)
    monkeypatch.setattr(memory, "KEEP_RECENT", 10)
    monkeypatch.setattr(memory, "CHUNK", 30)
    chat = memory.Chat.create(project, title="t")
    for i in range(10):
        chat.append(f"message number {i}", f"reply number {i}")
    full_log_before = chat.log()
    assert len(full_log_before) - chat.meta["upto"] > 50

    chat.compact_if_needed()

    assert chat.meta["upto"] > 0
    assert chat.meta["summaries"]
    assert all(s["text"] == "SUMMARY" for s in chat.meta["summaries"])
    # the raw log on disk is never shortened - only what's shown is cut
    assert chat.log() == full_log_before


def test_compact_if_needed_merges_oldest_summaries_past_budget(isolated_project, monkeypatch):
    _, project = isolated_project
    monkeypatch.setattr(memory, "_summarize", lambda piece: "X")
    monkeypatch.setattr(memory, "_merge", lambda older, newer: "MERGED")
    monkeypatch.setattr(memory, "MAX_RECENT", 10)
    monkeypatch.setattr(memory, "KEEP_RECENT", 5)
    monkeypatch.setattr(memory, "CHUNK", 30)
    monkeypatch.setattr(memory, "SUMMARY_BUDGET", 30)
    chat = memory.Chat.create(project, title="t")
    chat.meta["summaries"] = [
        {"from": "d1", "to": "d1", "text": "A" * 20},
        {"from": "d2", "to": "d2", "text": "B" * 20},
    ]
    chat.append("a longer message to push the log past max_recent", "and a reply too")

    chat.compact_if_needed()

    # the two oversized pre-seeded summaries got merged into one
    assert any(s["text"] == "MERGED" for s in chat.meta["summaries"])
    assert sum(len(s["text"]) for s in chat.meta["summaries"]) <= 30 + len("MERGED")
