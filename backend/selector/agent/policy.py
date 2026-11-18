"""Output policy (DESIGN §6.3 guardrails, §8.3): no enrollment promises, no network claims, no medical advice,
never discourage calling Medicare/SHIP/the plan; sanitize HTML and links. Input limits (DESIGN §8.2)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

ALLOWED_LINK_HOSTS = ("medicare.gov", "cms.gov", "shiphelp.org")
ESTIMATE_DISCLAIMER = (
    "These are estimates, not guarantees. Confirm in Medicare Plan Finder, at 1-800-MEDICARE, or with your SHIP."
)

_HEDGE = re.compile(r"\b(confirm|check|verify|whether|if|ask|call)\b", re.I)
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("enrollment_promise", re.compile(
        r"\b(i|we)\s*(?:'ll|will|can|could)?\s+(?:enroll|sign)\s+you\b|\bclick\s+(?:here\s+)?to\s+enroll\b"
        r"|(?<!not\s)(?<!no\s)\bguarantee[sd]?\b", re.I)),
    ("network_claim", re.compile(
        r"\b(?:dr\.?\s+\w+|your\s+doctors?|your\s+providers?|he|she|they|it)\s+(?:is|are)\s+"
        r"(?:definitely\s+)?(?:in|within|part\s+of)\s+(?:the\s+|its\s+|this\s+plan'?s?\s+|their\s+)?network\b"
        r"|\bin[- ]network\s+for\s+(?:dr\.?|your\s+doctor)", re.I)),
    ("medical_advice", re.compile(
        r"\byou\s+should\s+(?:stop|start|switch|change|reduce|increase)\s+(?:taking\s+)?(?:your\s+)?\w+"
        r"|\bstop\s+taking\b", re.I)),
    ("discourages_help", re.compile(
        r"\b(?:no\s+need|don'?t\s+need|do\s+not\s+need)\s+to\s+(?:call|contact|check)\b", re.I)),
]  # fmt: skip


def policy_problems(text: str) -> list[str]:
    problems: list[str] = []
    for name, rx in RULES:
        for mt in rx.finditer(text):
            if name == "network_claim" and _HEDGE.search(text[max(0, mt.start() - 60) : mt.start()]):
                continue
            if name == "medical_advice" and re.search(r"\bdoctor\b|\bpharmacist\b", text[mt.end() : mt.end() + 60]):
                continue
            problems.append(f"{name}: {mt.group(0)[:60]!r}")
            break
    return problems


def needs_estimate_disclaimer(text: str) -> bool:
    return bool(re.search(r"\bbest\s+plan", text, re.I)) and not re.search(r"\bestimate", text, re.I)


_TAG = re.compile(r"<[^>]{0,200}>")
_MD_LINK = re.compile(r"!?\[([^\]]{0,200})\]\(([^)\s]{1,500})\)")
_URL = re.compile(r"\bhttps?://[^\s)>\]]+", re.I)


def link_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return urlparse(url).scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_LINK_HOSTS)


def sanitize(text: str) -> str:
    """No raw HTML, images or off-allowlist links in model output (the frontend sanitizes again)."""
    text = _TAG.sub("", text)
    text = _MD_LINK.sub(lambda m: f"[{m.group(1)}]({m.group(2)})" if link_allowed(m.group(2)) and not
                        m.group(0).startswith("!") else m.group(1), text)  # fmt: skip
    return _URL.sub(lambda m: m.group(0) if link_allowed(m.group(0)) else "[link removed]", text)


def wrap_user_text(text: str, max_chars: int) -> str:
    """User text is data, never instructions (DESIGN §8.3)."""
    clipped = text[:max_chars].replace("</user_message", "<\\/user_message")
    return f"<user_message>\n{clipped}\n</user_message>"
