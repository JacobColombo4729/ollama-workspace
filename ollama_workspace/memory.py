"""Per-project chats with persistent, compressed memory.

data/projects/<folder>-<hash>/       one per workspace folder
    project.json                     which folder this project is
    notes.md                         notes shared by every chat in the project
    chats/<id>/log.txt               full transcript, append-only, never shortened
    chats/<id>/chat.json             title, timestamps, and summaries of older log

The model sees: project notes + summaries of older log + the recent raw log. When the
recent part grows past MAX_RECENT, its oldest piece is summarized into a NEW dated
summary (older summaries aren't rewritten, so they don't lose detail over time). When
summaries exceed SUMMARY_BUDGET, only the two oldest are merged. Nothing is deleted
from log.txt, and the model can search all of it with the search_history tool.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import ollama

from . import models
from .config import CHUNK, KEEP_RECENT, MAX_RECENT, PROJECTS_DIR, SUMMARY_BUDGET

STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d)\]", re.MULTILINE)
EXCHANGE_START = re.compile(r"\n(?=\[\d{4}-\d\d-\d\d \d\d:\d\d\] USER: )")

active: "Chat | None" = None  # the chat in use; tools read it


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def project_dir(workspace: Path) -> Path:
    digest = hashlib.sha1(str(workspace).lower().encode()).hexdigest()[:8]
    name = re.sub(r"[^\w.-]", "_", workspace.name or "root")
    d = PROJECTS_DIR / f"{name}-{digest}"
    (d / "chats").mkdir(parents=True, exist_ok=True)
    if not (d / "project.json").exists():
        (d / "project.json").write_text(json.dumps({"path": str(workspace)}, indent=2), "utf-8")
    (d / "notes.md").touch()
    return d


def list_chats(project: Path) -> list["Chat"]:
    """Chats in a project, most recently used first."""
    chats = [Chat(d) for d in (project / "chats").iterdir() if (d / "chat.json").exists()]
    # chat folders are named by creation time, so they break ties within the same minute
    return sorted(chats, key=lambda c: (c.meta["updated"], c.dir.name), reverse=True)


def _ask(prompt: str) -> str:
    m = models.current
    r = ollama.chat(model=m.name, messages=[{"role": "user", "content": prompt}],
                    options={"num_ctx": m.num_ctx}, think=m.think_value("off"))  # summaries don't need reasoning
    return r["message"]["content"].strip()


def _summarize(text: str) -> str:
    return _ask(
        "Summarize this part of a conversation for long-term memory. Keep every fact, "
        "decision, name, number, file path, preference, code detail and open task. "
        "Drop small talk. Reply with only concise bullet points, no intro line.\n\n" + text)


def _merge(older: str, newer: str) -> str:
    return _ask(
        "Combine these two consecutive memory summaries into one shorter summary. Keep "
        "every distinct fact, decision, name, preference and open task; remove repetition "
        "and anything the newer part says was replaced or finished. Reply with only concise "
        "bullet points, no intro line."
        f"\n\nOLDER:\n{older}\n\nNEWER:\n{newer}")


class Chat:
    def __init__(self, path: Path):
        self.dir = path
        self.log_path = path / "log.txt"
        self.meta_path = path / "chat.json"
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text("utf-8"))
        else:
            self.meta = {"title": "", "created": _now(), "updated": _now(),
                         "upto": 0, "summaries": []}  # upto = log chars already summarized

    @classmethod
    def create(cls, project: Path, title: str = "") -> "Chat":
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        path, n = project / "chats" / base, 1
        while path.exists():
            n += 1
            path = project / "chats" / f"{base}-{n}"
        path.mkdir()
        chat = cls(path)
        chat.log_path.touch()
        chat.meta["title"] = title
        chat.save()
        return chat

    @property
    def project(self) -> Path:
        return self.dir.parent.parent

    @property
    def title(self) -> str:
        return self.meta["title"] or "(untitled)"

    def save(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta, indent=2), "utf-8")

    def log(self) -> str:
        return self.log_path.read_text("utf-8") if self.log_path.exists() else ""

    def exchanges(self) -> list[str]:
        log = self.log().strip()
        return EXCHANGE_START.split(log) if log else []

    def append(self, user_msg: str, reply: str) -> None:
        stamp = _now()
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n[{stamp}] USER: {user_msg}\n[{stamp}] AI: {reply}\n")
        if not self.meta["title"]:
            self.meta["title"] = user_msg[:60] + ("..." if len(user_msg) > 60 else "")
        self.meta["updated"] = stamp
        self.save()

    def memory_prompt(self, budget: int, searchable: bool) -> str:
        """Notes + summaries + recent log, cut to about `budget` chars so small-context
        models still fit. What's cut stays on disk (and in search_history)."""
        notes = (self.project / "notes.md").read_text("utf-8").strip()
        if len(notes) > budget // 4:
            notes = notes[:budget // 4] + "\n...[notes cut off to fit the model's context]"
        left = budget - len(notes)
        shown, used = [], 0
        for s in reversed(self.meta["summaries"]):  # newest summaries first
            block = f"[{s['from']} to {s['to']}]\n{s['text']}"
            if used + len(block) > left * 0.4:
                break
            shown.insert(0, block)
            used += len(block)
        summaries = "\n\n".join(shown)
        if len(shown) < len(self.meta["summaries"]):
            summaries = "...[older summaries left out to fit the model's context]\n\n" + summaries
        recent, room = self.log()[self.meta["upto"]:], left - used
        if len(recent) > room:
            start = recent.find("\n[", len(recent) - room)  # begin at a full log line
            recent = "...[earlier part left out]" + recent[start if start != -1 else -room:]
        recall = (" The summaries are compressed; if you need an exact earlier detail, "
                  "use search_history." if searchable else "")
        return (
            "You are a helpful assistant with long-term memory of past conversations "
            f"with this user. Use it naturally; don't recite it unless asked.{recall}\n\n"
            f"=== PROJECT NOTES (shared by all chats in this project) ===\n{notes or '(none)'}\n\n"
            f"=== SUMMARIES OF OLDER CONVERSATION ===\n{summaries or '(none yet)'}\n\n"
            f"=== RECENT CONVERSATION LOG ===\n{recent or '(none yet)'}"
        )

    def compact_if_needed(self) -> None:
        log, upto = self.log(), self.meta["upto"]
        if len(log) - upto <= MAX_RECENT:
            return
        cut = log.rfind("\n", upto, len(log) - KEEP_RECENT)  # cut on a line break
        if cut <= upto:
            cut = len(log) - KEEP_RECENT
        print("\033[2m[compressing older history into memory...]\033[0m", flush=True)
        while upto < cut:
            end = log.rfind("\n", upto + 1, min(upto + CHUNK, cut)) if upto + CHUNK < cut else cut
            if end <= upto:
                end = min(upto + CHUNK, cut)
            piece = log[upto:end]
            stamps = STAMP.findall(piece) or ["undated"]
            self.meta["summaries"].append(
                {"from": stamps[0], "to": stamps[-1], "text": _summarize(piece)})
            self.meta["upto"] = upto = end
            self.save()  # after every piece, so a crash keeps progress
        s = self.meta["summaries"]
        while len(s) > 1 and sum(len(x["text"]) for x in s) > SUMMARY_BUDGET:
            print("\033[2m[merging oldest memory summaries...]\033[0m", flush=True)
            a, b = s[0], s[1]
            s[0:2] = [{"from": a["from"], "to": b["to"], "text": _merge(a["text"], b["text"])}]
            self.save()
