"""Which Ollama model is in use and what it supports.

Works with any installed model: tool calling, thinking and context size are read from
Ollama, and the chat adapts (models without tools chat without file access; models
with a small context get smaller memory and file budgets).
"""
import json
from dataclasses import dataclass, field

import ollama

from .console import ask
from .config import CHARS_PER_TOKEN, DATA_DIR, NUM_CTX

SETTINGS = DATA_DIR / "settings.json"  # remembers the last model you picked

THINK_CHOICES = ("off", "low", "medium", "high")  # what the user picks with /think
LEVEL_ORDER = ("low", "medium", "high", "xhigh", "max")  # levels models may report


@dataclass
class Model:
    name: str
    tools: bool      # can call tools (file editing, history search, notes)
    thinking: bool   # streams its reasoning separately
    num_ctx: int     # context window used: NUM_CTX, or less if the model's max is smaller
    levels: list[str] = field(default_factory=list)  # thinking levels it lists; [] = on/off only
    can_disable: bool = True  # False for models that always think

    def think_value(self, choice: str) -> bool | str | None:
        """The `think` option to send for a /think choice; None = don't send it at all."""
        if not self.thinking:
            return None
        if choice == "off":
            return False if self.can_disable else None
        if not self.levels:
            return True
        if choice in self.levels:
            return choice
        if choice == "high":
            return self.levels[-1]  # the model's strongest level, e.g. "xhigh"
        want = LEVEL_ORDER.index(choice)
        return min(self.levels, key=lambda lvl: abs(LEVEL_ORDER.index(lvl) - want)
                   if lvl in LEVEL_ORDER else len(LEVEL_ORDER))

    def chars(self, share: float) -> int:
        """Rough number of characters that fit in this share of the context window."""
        return int(self.num_ctx * CHARS_PER_TOKEN * share)

    def describe(self) -> str:
        features = [f for f, on in (("tools", self.tools), ("thinking", self.thinking)) if on]
        return f"{self.name} ({', '.join(features) or 'chat only'}, {self.num_ctx // 1024}k context)"


current: Model | None = None
installed: list[str] = []  # chat-capable models, filled by refresh()


def refresh() -> list[str]:
    """Reload the installed models, skipping embedding-only ones that can't chat."""
    names = []
    for m in ollama.list().models:
        caps = ollama.show(m.model).capabilities
        if caps is None or "completion" in caps:  # None: older Ollama that doesn't report it
            names.append(m.model)
    installed[:] = sorted(names, key=str.lower)
    return installed


def _thinking_info(name: str) -> dict:
    """Ollama's /api/show lists a model's thinking levels, e.g. {"values": [false, "low",
    "medium", "xhigh"]}, but the Python library drops that field, so ask the API directly."""
    try:
        return ollama.Client()._client.post("/api/show", json={"model": name}).json().get(
            "thinking") or {}
    except Exception:
        return {}


def load(name: str) -> Model:
    info = ollama.show(name)
    caps = info.capabilities or ["completion"]
    max_ctx = next((v for k, v in (info.modelinfo or {}).items()
                    if k.endswith(".context_length")), 0)
    values = _thinking_info(name).get("values") or []
    return Model(name, "tools" in caps, "thinking" in caps,
                 min(NUM_CTX, max_ctx) if max_ctx else NUM_CTX,
                 levels=[v for v in values if isinstance(v, str)],
                 can_disable=not values or False in values)


def use(name: str) -> Model:
    global current
    current = load(name)
    DATA_DIR.mkdir(exist_ok=True)
    SETTINGS.write_text(json.dumps({"model": name}, indent=2), "utf-8")
    return current


def saved_default() -> str | None:
    try:
        return json.loads(SETTINGS.read_text("utf-8")).get("model")
    except (OSError, ValueError):
        return None


def find(ref: str) -> str | None:
    """Match an installed model by list number, exact name, name without ':latest',
    or a unique part of the name."""
    if ref.isdigit() and 1 <= int(ref) <= len(installed):
        return installed[int(ref) - 1]
    low = ref.lower()
    for name in installed:
        if low in (name.lower(), name.lower().removesuffix(":latest")):
            return name
    partial = [n for n in installed if low in n.lower()]
    if len(partial) == 1:
        return partial[0]
    print(f"{'Several models match' if partial else 'No installed model matches'} '{ref}'; "
          "see /models.")
    return None


def print_installed() -> None:
    for i, name in enumerate(installed, 1):
        mark = "*" if current and current.name == name else " "
        print(f"{mark}{i:>3}. {name}")


def pick() -> str:
    """Ask the user to choose an installed model."""
    print("Installed models:")
    print_installed()
    while True:
        if name := find(ask("Model number or name: ") or "?"):
            return name
