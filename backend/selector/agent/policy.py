"""Output policy (DESIGN §6.3 guardrails, §8.3): no enrollment promises, no medical advice, never discourage calling
Medicare/SHIP/the plan; sanitize HTML and links. Input limits (DESIGN §8.2).

Network claims (addendum A3.6): a sentence may say a doctor is listed / in network only when a
`check_provider_network` (or compare) tool row says `listed` for that doctor, and the sentence carries the check
date and tells the user to call the plan. Everything else about networks must be hedged ("call the plan to check
whether…")."""

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
        r"|\bin[- ]network\s+for\s+(?:dr\.?|your\s+doctor)"
        r"|\b(?:dr\.?\s+\w+|your\s+doctors?|he|she|they)\s+(?:is|are)\s+(?:listed|covered)\b"
        r"|\b(?:dr\.?\s+\w+|your\s+doctors?|he|she|they)\s+accepts?\s+(?:your|this|the|that)\s+plan\b", re.I)),
    ("medical_advice", re.compile(
        r"\byou\s+should\s+(?:stop|start|switch|change|reduce|increase)\s+(?:taking\s+)?(?:your\s+)?\w+"
        r"|\bstop\s+taking\b", re.I)),
    ("discourages_help", re.compile(
        r"\b(?:no\s+need|don'?t\s+need|do\s+not\s+need)\s+to\s+(?:call|contact|check)\b", re.I)),
]  # fmt: skip


# Sentence ends, but not after titles such as "Dr." ("Dr. Test is listed…" is one sentence).
_SENTENCE_END = re.compile(r"(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<=[.!?])\s+|\n+")
_DATED = re.compile(r"\b(?:checked|as of)\b[^.]{0,40}?(?:\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)
_CALL = re.compile(r"\bcall\b", re.I)


def _sentences(text: str, pos: int) -> tuple[str, str]:
    """The sentence around `pos` and the one after it."""
    starts = [0] + [m.end() for m in _SENTENCE_END.finditer(text) if m.end() <= pos]
    start = starts[-1]
    nxt = _SENTENCE_END.search(text, pos)
    end = nxt.start() if nxt else len(text)
    after = ""
    if nxt:
        nxt2 = _SENTENCE_END.search(text, nxt.end())
        after = text[nxt.end() : nxt2.start() if nxt2 else len(text)]
    return text[start:end], after


def _listed_ok(sentence: str, after: str, listed_names: frozenset[str]) -> bool:
    """A listing claim backed by a `listed` tool row: names that doctor and carries the check date, and the same
    or the next sentence tells the user to call (the app's own wording: "… (checked Nov 19). Call to confirm.")."""
    low = sentence.lower()
    named = any(n and n in low for n in listed_names)
    return named and bool(_DATED.search(sentence)) and bool(_CALL.search(sentence) or _CALL.search(after))


def policy_problems(text: str, listed_names: frozenset[str] = frozenset()) -> list[str]:
    """`listed_names`: lower-case names (full and last) of doctors a tool reported as `listed`."""
    problems: list[str] = []
    for name, rx in RULES:
        for mt in rx.finditer(text):
            if name == "network_claim" and _HEDGE.search(text[max(0, mt.start() - 60) : mt.start()]):
                continue
            if name == "network_claim" and _listed_ok(*_sentences(text, mt.start()), listed_names):
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
