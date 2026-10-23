"""Whitespace/encoding hygiene applied at two boundaries: what gets written to a chat log
(Chat.append) and what the model actually sees (Chat.memory_prompt's assembled context).

This is deliberately narrow. It never touches real content, wording, or formatting the
model chose - only whitespace, line endings, and invisible characters that carry no
meaning and only add noise (context-budget waste, ugly diffs, or at the degenerate
extreme, menace) to stored text. It does not decide whether a reply is garbage - that's
turn.py's _looks_degenerate(), which drops a bad reply before it's ever logged. This just
tidies whatever text *does* get logged or read back, model-written or not (notes.txt,
decisions.txt etc. can be hand-edited, and board/findings entries come from several
tools), so the cleanup applies uniformly regardless of where the text came from.
"""
import re
import unicodedata

_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")  # 2+ consecutive blank lines -> 1
# C0 control characters except \t and \n (and \r, already folded into \n below)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# zero-width space/non-joiner/joiner, word joiner, byte-order mark - invisible, no
# rendered effect, but can appear mid-word from a bad encoding pass or model output
_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")


def normalize(text: str) -> str:
    """Canonical Unicode form (NFC), \\n-only line endings, no stray control/invisible
    characters, no trailing whitespace per line, no runs of 2+ blank lines. Idempotent -
    safe to call on text this already ran on, or on text it never touched."""
    if not text:
        return text
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _INVISIBLE.sub("", t)
    t = _CONTROL.sub("", t)
    t = _TRAILING_WS.sub("", t)
    t = _BLANK_RUN.sub("\n\n", t)
    return t
