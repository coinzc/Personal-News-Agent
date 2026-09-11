"""Versioned prompt loading for the News Agent."""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPT_VERSION = "v1"
_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"


@cache
def load_prompt(name: str) -> str:
    """Load a prompt template from the repository's versioned prompt folder."""

    path = _PROMPT_ROOT / name
    if path.suffix != ".txt" or path.parent != _PROMPT_ROOT:
        raise ValueError("prompt name must be a top-level .txt file")
    return path.read_text(encoding="utf-8").strip()


def agent_system_prompt() -> str:
    """Return the current Agent system prompt."""

    return load_prompt("agent_system.txt")
