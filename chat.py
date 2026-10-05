"""ollama-workspace entry point. Run it from the project folder you want to work on, e.g.

    python path/to/ollama-workspace/chat.py      (shared install)
    python ollama-workspace/chat.py              (a copy inside the project)
    python chat.py --workspace path/to/project   (from anywhere)
"""
from ollama_workspace.chat import main

if __name__ == "__main__":
    main()
