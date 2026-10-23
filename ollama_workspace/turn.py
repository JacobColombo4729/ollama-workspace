"""Running one message through the model currently active (whatever chat/model/agent that
is): builds the request, runs the tool loop to completion - handling a Ctrl+C interrupt and
the token-length cap automatically - logs the exchange in the current chat, and returns the
final reply.

Used by the main loop for what you type, and by dispatch_to_agent (tools/dispatch.py) for a
delegated subtask. Both just talk to whichever chat/model/agent happens to be active, so a
dispatched subtask gets logging, memory and context handling for free - no special-casing.
"""
import re
import sys
import time

import ollama

from . import guard, memory, models
from .attachments import attach_files
from .config import MAX_TOOL_STEPS, REPLY_LIMIT, UNLEASHED_TOOL_STEPS
from .console import ask_message
from .stream import build_messages, continuation, fit_context, interjection, stream_step
from .tools import changed, run_tool
from .tools.base import state

MAX_FAKE_CALL_RETRIES = 3  # a weak/quantized model sometimes prints a tool call as text


_CHAR_RUN = re.compile(r"(.)\1{19,}")  # the same character 20+ times in a row


def _looks_degenerate(text: str) -> bool:
    """True if a reply looks like model degeneration - backtick/symbol salad or a tiny
    vocabulary repeated - rather than real content, so it isn't written to the chat log
    where it would feed back into and poison every later turn. Deliberately conservative,
    and keyed on repetition, not symbol density: code is symbol-heavy but not repetitive,
    so it passes. Ollama's own repeat-limit abort already drops the worst case upstream
    (nothing saved); this catches the milder 'finished but garbled' reply. The milder
    word-salad that still reads as broken English is left to the human + /clear."""
    t = text.strip()
    if len(t) < 60:
        return False  # too short to judge; terse real replies ("Done.", "Hello!") must pass
    if _CHAR_RUN.search(t.replace(" ", "")):
        return True  # a long run of one character, e.g. ``` ` ` ` ``` collapses to backticks
    tokens = t.split()
    if len(tokens) >= 40 and len(set(tokens)) / len(tokens) < 0.15:
        return True  # almost no vocabulary: the same few tokens over and over
    alpha = sum(c.isalpha() for c in t)
    if len(t) >= 100 and alpha / len(t) < 0.25:
        return True  # long reply that's mostly punctuation/digits/whitespace
    return False
                           # ({"type": "function", ...}) instead of making a real one, which
                           # the server never sees and nothing runs. Nudge it to call for
                           # real instead of silently ending the turn, up to this many times
                           # per message - after that, say so plainly instead of looping.
_FAKE_CALL_RE = re.compile(
    r'"(?:type"\s*:\s*"function"|name"\s*:\s*"[a-zA-Z_]+"\s*,\s*"parameters")')
_FAKE_CALL_NUDGE = (
    "You wrote a tool call as plain text/JSON instead of actually calling it through the "
    "tool-calling API. That did nothing - no file was touched, nothing ran. Make the call "
    "for real now: don't describe it or print JSON, call the tool."
)


def _looks_like_fake_tool_call(content: str) -> bool:
    return bool(_FAKE_CALL_RE.search(content))


def run_turn(q: str) -> str:
    """Send q to the current model, run its tool loop to completion, log the exchange in
    the current chat (memory.active), and return the final reply - "" if nothing was said
    (the user stopped it with nothing typed, or it errored); nothing is logged either way."""
    prompt, attached = attach_files(q)
    num_predict = REPLY_LIMIT
    messages = build_messages(prompt)
    changed.clear()
    replies, notes, done_reason = [], [], None
    fake_retries = 0
    max_steps = MAX_TOOL_STEPS if guard.restricted() else UNLEASHED_TOOL_STEPS
    print("[waiting for model... Ctrl+C to interrupt and add info]", flush=True)
    try:
        # the model may call tools several times before it gives its final answer
        for _ in range(max_steps):
            fit_context(messages, num_predict)
            content, reasoning, calls, done_reason = stream_step(messages, num_predict)
            if done_reason == "interrupted":
                try:
                    note = ask_message("[paused] Add info for the model (Enter = just stop): ")
                except KeyboardInterrupt:
                    note = ""
                if content.strip():
                    replies.append(content.strip() + " [interrupted]")
                if not note:
                    print("[stopped]")
                    done_reason = "stopped"
                    break
                notes.append(note)
                if content.strip():
                    messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": interjection(reasoning, note)})
                print("[continuing with your note...]", flush=True)
                continue
            if done_reason == "length" and not calls:
                # cut off by the token cap, not finished: hand the partial reasoning/draft
                # back instead of losing it, so the model continues instead of restarting
                if content.strip():
                    replies.append(content.strip() + " [cut off - continuing]")
                    print()
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": continuation(reasoning, content)})
                print("\033[2m[ran out of room; continuing automatically...]\033[0m", flush=True)
                continue
            if not calls and content.strip() and _looks_like_fake_tool_call(content) \
                    and fake_retries < MAX_FAKE_CALL_RETRIES:
                fake_retries += 1
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": _FAKE_CALL_NUDGE})
                print("\033[2m[model wrote a tool call as text instead of making one; "
                      "asking it to call it for real]\033[0m", flush=True)
                continue
            fake_retries = 0
            if content.strip():
                replies.append(content.strip())
                print()
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if not calls:
                break
            for call in calls:
                messages.append({"role": "tool", "content": run_tool(call),
                                 "tool_name": call.function.name})
            if state.pace:  # /pace: give a human watching time to read each step
                time.sleep(state.pace)
        else:
            print(f"[stopped after {max_steps} tool steps]")
    except KeyboardInterrupt:  # Ctrl+C outside streaming, e.g. at an edit approval prompt
        print("\033[0m\n[stopped]")
        done_reason = "stopped"
    except ollama.ResponseError as e:
        if e.status_code == 404:
            print(f"\033[0m\n[{models.missing_model_message(models.current.name)}]")
            return ""  # nothing to save
        # the error text comes from the model/server and may contain characters the
        # Windows console's codepage can't print - replace them rather than crash
        safe = str(e.error).encode(sys.stdout.encoding or "utf-8", "replace") \
            .decode(sys.stdout.encoding or "utf-8")
        print(f"\033[0m\n[model error: {safe}] - try /model to switch models")
        return ""  # nothing to save
    except ConnectionError:
        print(f"\033[0m\n[{models.unreachable_server_message()}]")
        return ""  # nothing to save
    reply = "\n".join(replies)
    print()
    if not reply and not changed:
        if done_reason == "stopped":
            return ""  # stopped before saying anything: don't clutter the history
        print(f"[no answer - stopped: {done_reason}; raise REPLY_LIMIT or THINK_BUDGET in config.py]")
    # log only file names, not contents, so big files don't flood memory
    logged = q + (f" [attached: {', '.join(attached)}]" if attached else "")
    logged += "".join(f"\n[interjected: {n}]" for n in notes)
    if changed:
        reply += f" [changes: {', '.join(sorted(changed))}]"
    if reply and not changed and _looks_degenerate(reply):
        print("\033[2m[the reply looked garbled, so it was not saved to this chat - a "
              "saved one would feed back into later turns. /clear this chat or /model to "
              "switch if it keeps happening.]\033[0m", flush=True)
        return ("[The model produced garbled output, so nothing was saved to this chat. "
                "Try again - or clear the chat if it keeps happening.]")
    memory.active.meta["model"] = models.current.name
    memory.active.append(logged, reply)  # saved immediately, so nothing is lost on a crash
    memory.active.compact_if_needed()
    return reply
