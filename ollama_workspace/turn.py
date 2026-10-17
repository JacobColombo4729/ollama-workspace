"""Running one message through the model currently active (whatever chat/model/agent that
is): builds the request, runs the tool loop to completion - handling a Ctrl+C interrupt and
the token-length cap automatically - logs the exchange in the current chat, and returns the
final reply.

Used by the main loop for what you type, and by dispatch_to_agent (tools/dispatch.py) for a
delegated subtask. Both just talk to whichever chat/model/agent happens to be active, so a
dispatched subtask gets logging, memory and context handling for free - no special-casing.
"""
import sys

import ollama

from . import guard, memory, models
from .attachments import attach_files
from .config import MAX_TOOL_STEPS, REPLY_LIMIT, UNLEASHED_TOOL_STEPS
from .console import ask_message
from .stream import build_messages, continuation, fit_context, interjection, stream_step
from .tools import changed, run_tool


def run_turn(q: str) -> str:
    """Send q to the current model, run its tool loop to completion, log the exchange in
    the current chat (memory.active), and return the final reply - "" if nothing was said
    (the user stopped it with nothing typed, or it errored); nothing is logged either way."""
    prompt, attached = attach_files(q)
    num_predict = REPLY_LIMIT
    messages = build_messages(prompt)
    changed.clear()
    replies, notes, done_reason = [], [], None
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
            if content.strip():
                replies.append(content.strip())
                print()
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if not calls:
                break
            for call in calls:
                messages.append({"role": "tool", "content": run_tool(call),
                                 "tool_name": call.function.name})
        else:
            print(f"[stopped after {max_steps} tool steps]")
    except KeyboardInterrupt:  # Ctrl+C outside streaming, e.g. at an edit approval prompt
        print("\033[0m\n[stopped]")
        done_reason = "stopped"
    except ollama.ResponseError as e:
        # the error text comes from the model/server and may contain characters the
        # Windows console's codepage can't print - replace them rather than crash
        safe = str(e.error).encode(sys.stdout.encoding or "utf-8", "replace") \
            .decode(sys.stdout.encoding or "utf-8")
        print(f"\033[0m\n[model error: {safe}] - try /model to switch models")
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
    memory.active.meta["model"] = models.current.name
    memory.active.append(logged, reply)  # saved immediately, so nothing is lost on a crash
    memory.active.compact_if_needed()
    return reply
