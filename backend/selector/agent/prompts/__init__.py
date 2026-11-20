"""Versioned system prompts. Bump PROMPT_VERSION with any prompt change (recorded on feedback rows)."""

from __future__ import annotations

from pathlib import Path

PROMPT_VERSION = "v2"
_DIR = Path(__file__).resolve().parent


def system_prompt(version: str = PROMPT_VERSION) -> str:
    return (_DIR / f"system_{version}.md").read_text(encoding="utf-8")
