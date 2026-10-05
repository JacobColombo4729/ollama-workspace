"""Reading user input."""


def ask(prompt: str) -> str:
    """input() without surrounding whitespace or the byte-order mark Windows PowerShell
    puts at the start of piped text (which would hide a /command)."""
    return input(prompt).replace("\ufeff", "").strip()
