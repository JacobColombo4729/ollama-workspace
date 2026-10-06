"""Talking to the model: builds each request, keeps it within the context window, streams
the reply (Ctrl+C pauses it), and sizes the thinking budget."""
import platform
import queue
import threading

import ollama

from . import config, guard, memory, models
from .config import CHARS_PER_TOKEN, MEMORY_SHARE, STYLE, THINK_BUDGET, THINK_LEVEL
from .prompts import CODING, NO_TOOLS, RESTRICTED, UNLEASHED
from .tools import SHELL, TOOLS


TRIMMED = "[old tool output removed to save context; call the tool again if you need it]"


def think_level() -> str:
    """This chat's /think choice: off, low, medium or high."""
    level = memory.active.meta.get("think") if memory.active else None
    return level if level in models.THINK_CHOICES else THINK_LEVEL


def think_budget() -> int:
    """Extra tokens reserved for reasoning: scales with the thinking level."""
    if models.current.think_value(think_level()) in (None, False):
        return 0
    return {"low": THINK_BUDGET // 2, "high": THINK_BUDGET * 2}.get(think_level(), THINK_BUDGET)


def describe_thinking() -> str:
    m, level = models.current, think_level()
    if not m.thinking:
        return "this model doesn't think, so /think has no effect"
    sent = m.think_value(level)
    detail = ("on/off only" if not m.levels
              else "levels: " + ", ".join((["off"] if m.can_disable else []) + m.levels))
    note = f" -> sends {sent!r}" if isinstance(sent, str) and sent != level else ""
    if level == "off" and not m.can_disable:
        note = " -> this model always thinks"
    return f"thinking: {level}{note} ({detail})"


def build_messages(user_msg: str) -> list:
    m = models.current
    return [
        {"role": "system", "content": memory.active.memory_prompt(m.chars(MEMORY_SHARE), m.tools)},
        {"role": "system", "content": CODING.format(
            workspace=config.WORKSPACE, os=platform.system(), shell=SHELL,
            paths=("all paths are relative to the workspace" if guard.restricted() else
                   "paths are relative to the workspace, or absolute"),
            mode_note=RESTRICTED if guard.restricted() else UNLEASHED)
                                      if m.tools else NO_TOOLS},
        # style rules go last so they aren't buried under the long log
        {"role": "system", "content": "Response style: " + STYLE},
        {"role": "user", "content": user_msg},
    ]


def fit_context(messages: list, num_predict: int) -> None:
    """Ollama silently drops the start of the conversation when it overflows, which would
    lose the memory and instructions. Clear the oldest tool outputs first instead."""
    budget = (models.current.num_ctx - num_predict - think_budget()) * CHARS_PER_TOKEN
    size = sum(len(m["content"] or "") + len(str(m.get("tool_calls") or "")) for m in messages)
    for m in messages:
        if size <= budget:
            return
        if m["role"] == "tool" and m["content"] != TRIMMED:
            size -= len(m["content"]) - len(TRIMMED)
            m["content"] = TRIMMED
            print("\033[2m[cleared an old tool output to stay within the context window]\033[0m")


def stream_step(messages: list, num_predict: int) -> tuple[str, str, list, str | None]:
    """Stream one model response. Returns (reply text, reasoning, tool calls, done reason);
    done reason is "interrupted" if the user pressed Ctrl+C."""
    content, reasoning, calls, in_think, reply_tokens, done_reason = "", "", [], False, 0, None
    # num_predict counts thinking + reply together, so give thinking its own budget
    # and cap the reply ourselves (each streamed content chunk is ~1 token)
    m = models.current
    stream = ollama.chat(model=m.name, messages=messages, stream=True,
                         tools=TOOLS if m.tools else None, think=m.think_value(think_level()),
                         options={"num_ctx": m.num_ctx,
                                  "num_predict": num_predict + think_budget()})
    parts = responsive(stream)
    try:
        for part in parts:
            done_reason = part.get("done_reason") or done_reason
            calls += part["message"].get("tool_calls") or []
            think_chunk = part["message"].get("thinking") or ""
            if think_chunk:
                if not in_think:
                    print("\033[2m[thinking]\n", end="", flush=True)  # dim
                    in_think = True
                print(think_chunk, end="", flush=True)
                reasoning += think_chunk
            chunk = part["message"]["content"] or ""
            if chunk:
                if in_think:
                    print("\033[0m\n\n", end="", flush=True)  # reset dim, blank line before answer
                    in_think = False
                print(chunk, end="", flush=True)
                content += chunk
                reply_tokens += 1
                if reply_tokens >= num_predict:
                    done_reason = "length"
                    break
    except KeyboardInterrupt:
        done_reason = "interrupted"
    finally:
        parts.close()  # tells the reader thread to close the connection, stopping Ollama
    print("\033[0m" + ("\n" if in_think or done_reason == "interrupted" else ""),
          end="", flush=True)
    return content, reasoning, calls, done_reason


def responsive(stream):
    """Yield the stream's parts, read on a background thread. On Windows a Ctrl+C can't
    interrupt a blocking network read, so reading in the main thread ignored it until the
    model's next token, which can be minutes while a model loads or reads a long prompt.
    Here the main thread only waits in short steps, so Ctrl+C works at once."""
    parts, stop = queue.Queue(), threading.Event()
    done = object()

    def read():
        try:
            for part in stream:
                parts.put((None, part))
                if stop.is_set():
                    break
        except Exception as e:  # e.g. ollama.ResponseError: re-raised in the main thread
            parts.put((e, None))
        finally:
            if hasattr(stream, "close"):
                stream.close()  # closes the connection, which makes Ollama stop generating
            parts.put((done, None))

    threading.Thread(target=read, daemon=True).start()
    try:
        while True:
            try:
                error, part = parts.get(timeout=0.1)
            except queue.Empty:
                continue
            if error is done:
                return
            if error:
                raise error
            yield part
    finally:
        stop.set()


INTERJECT_REASONING = 6000  # chars of interrupted reasoning carried over (the most recent part)


def interjection(reasoning: str, note: str) -> str:
    """The message that hands the model its interrupted reasoning plus the user's note."""
    so_far = reasoning.strip()
    if len(so_far) > INTERJECT_REASONING:
        so_far = "..." + so_far[-INTERJECT_REASONING:]
    return ("[The user interrupted you to add information.]\n\n"
            + (f"Your reasoning so far:\n{so_far}\n\n" if so_far else "")
            + f"The user adds: {note}\n\n"
            "Continue from where you were, taking this into account. Don't restart your "
            "reasoning from scratch or apologize for the interruption.")
