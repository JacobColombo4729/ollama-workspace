"""All settings in one place."""
import pathlib

# The model is picked at startup (or with --model / /model) and remembered in
# data/settings.json; any installed Ollama model works. See models.py.
NUM_CTX = 32768            # max context window in tokens; models with less use their own max.
                           # Bigger costs more memory (a 27B model: 32k ~19 GB, 64k ~22 GB)
CHARS_PER_TOKEN = 3.5      # rough average for code/English, used for context budgeting
THINK_BUDGET = 4096        # extra tokens for thinking models, on top of the reply length
REPLY_LIMIT = 4096         # safety cap on reply tokens; the model sizes replies itself (see STYLE)

# Memory (raw log -> dated summaries; the full log is always kept on disk)
MAX_RECENT = 30_000        # chars of raw log the model sees before compressing (~8.5k tokens)
KEEP_RECENT = 15_000       # chars of raw log left after compressing
CHUNK = 15_000             # chars of log per summary
SUMMARY_BUDGET = 12_000    # total summary chars before the two oldest get merged
MEMORY_SHARE = 0.5         # max share of the context for notes + summaries + recent log

# Files and code editing
READ_SHARE = 0.4           # max share of the context one file read/attachment may use
MAX_TOOL_STEPS = 25        # max model->tool round trips per message
AUTO_APPROVE = False       # True = apply file edits without asking
WORKSPACE = pathlib.Path.cwd().resolve()  # the codebase the model may edit: where you launch
SKIP_DIRS = {"__pycache__", "node_modules", "venv", "dist", "build"}  # plus any .hidden dir

# Paths (data lives next to the code, wherever the project is)
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"  # one folder per workspace; see memory.py

STYLE = (
    "Match reply length and depth to the question, not to how much you could say. "
    "Casual or simple questions get 1-3 sentences, plain prose, no markdown. "
    "Save headers, bullet lists, and multi-section answers for when the question is genuinely "
    "complex or the user asked for steps, depth, or code - most answers don't need them. "
    "No filler: don't restate the question, don't preamble, don't add a closing summary "
    "or recap of what you just said. State the answer directly. "
    "If you're not sure what the user wants, give your best direct answer and only ask "
    "a clarifying question when the request is genuinely ambiguous. "
    "Don't over-apologize or hedge excessively; state things plainly."
)
