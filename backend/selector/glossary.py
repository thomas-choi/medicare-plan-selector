"""Plain-language meaning of the comparison table's columns and terms. One source for the "Important info" dialog
(`GET /api/config` → `glossary`), the assistant's system prompt and the Demo (fake) provider.

The text matches how `selector.cost.engine` computes each value. It holds no dollar amounts, percentages or plan IDs:
the chat validator only lets numbers through when a tool returned them, and the amounts change every plan year.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    id: str
    title: str
    text: str
    aliases: tuple[str, ...]  # lower-case phrases that name this term in a user's question


GLOSSARY: tuple[Term, ...] = (
    Term(
        "est_yearly_cost",
        "Est. yearly cost",
        "What a typical year could cost you with this plan: the plan premium, the standard Part B premium, your "
        "drugs and your medical care for the usage level you chose (low, medium or high). It is shown as a range "
        "from a low to a high estimate, and the midpoint of that range is used to rank plans. It is an estimate, "
        "not a quote.",
        (
            "est. yearly cost",
            "est yearly cost",
            "estimated yearly cost",
            "yearly cost",
            "annual cost",
            "total cost",
            "estimated cost",
            "est. yearly",
            "estimate",
        ),
    ),
    Term(
        "worst_case",
        "Worst case",
        "What a very bad year could cost: the premiums, the high end of your drug costs, and the plan's maximum "
        "out-of-pocket limit (MOOP) for medical care, as if you needed a lot of care. For a Medicare Advantage "
        "plan this is the most you would pay in a year for covered, in-network care. Out-of-network care and "
        "services the plan doesn't cover don't count toward the limit, so a real year could cost more. Original "
        'Medicare without a Medigap plan has no yearly limit, so its worst case shows "No limit".',
        ("worst case", "worst-case", "worst"),
    ),
    Term(
        "moop",
        "Maximum out-of-pocket (MOOP)",
        "The most you pay in a year for covered, in-network medical care in a Medicare Advantage plan. After you "
        "reach it, the plan pays for covered in-network care for the rest of the year. Premiums and drug costs "
        "don't count toward it. It is the medical part of the Worst case column.",
        (
            "moop",
            "maximum out-of-pocket",
            "maximum out of pocket",
            "max out of pocket",
            "out-of-pocket limit",
            "out of pocket limit",
            "out-of-pocket maximum",
        ),
    ),
    Term(
        "deductible",
        "Deductible",
        "What you pay yourself before the plan starts paying its share. It is the opposite end from the MOOP: the "
        "deductible matters at the start of the year, the MOOP only in a bad year. The Part D deductible (drugs) "
        "is already part of the drug cost in both Est. yearly cost and Worst case, and any medical deductible "
        "counts toward the MOOP, so neither is added again.",
        ("deductible", "part d deductible"),
    ),
    Term(
        "premium",
        "Premium/mo",
        "The plan's own monthly premium from the CMS plan data. You also keep paying the standard Part B premium, "
        "which every yearly total includes. For the standard row the premium is the drug plan's, plus Part B.",
        ("premium/mo", "premium", "monthly premium"),
    ),
    Term(
        "stars",
        "Stars",
        "The plan's overall Medicare star rating from CMS, from one to five stars. New or small plans can be "
        '"not rated".',
        ("stars", "star rating", "star"),
    ),
    Term(
        "drugs_covered",
        "Drugs covered",
        "How many of the drugs you entered are on the plan's drug list (formulary). Plans that don't cover all of "
        "your drugs are shown as not ranked.",
        ("drugs covered", "formulary", "covered drugs"),
    ),
    Term(
        "dental",
        "Dental",
        "The plan's routine dental benefit from the CMS plan benefit data. Dental costs are not part of the yearly "
        "estimates. Original Medicare, Medigap and stand-alone drug plans don't cover routine dental.",
        ("dental",),
    ),
    Term(
        "your_doctors",
        "Your doctors",
        "Whether the plan's public provider directory lists the doctors you entered, with the date it was checked. "
        "Directories can be out of date: call the plan to confirm.",
        ("your doctors", "doctors", "provider directory", "network"),
    ),
    Term(
        "vs_standard",
        "vs. standard",
        "How much more or less this plan's estimated yearly cost is than the standard option, Original Medicare "
        "plus the lowest-cost stand-alone drug plan for your drugs.",
        ("vs. standard", "vs standard", "versus standard", "standard option", "standard row", "baseline"),
    ),
    Term(
        "rank",
        "Rank",
        "The order of the plans. It mostly follows the estimated yearly cost, then the worst case, the star rating "
        "and how many of your drugs are covered. No plan or company pays to be ranked higher.",
        ("rank", "ranking", "ranked"),
    ),
)

_QUESTION = re.compile(r"\?|\b(what|mean|means|meaning|explain|define|definition|difference|how is|how are)\b", re.I)


def as_list() -> list[dict[str, str]]:
    return [{"id": t.id, "title": t.title, "text": t.text} for t in GLOSSARY]


def prompt_block() -> str:
    """The glossary for the system prompt (Markdown list)."""
    return "\n".join(f"- **{t.title}**: {t.text}" for t in GLOSSARY)


def terms_asked(text: str) -> list[Term]:
    """Terms a general question asks about ("What is the column Est. yearly cost?"), best match first; [] when the
    text isn't a question about a term. The longest alias wins, so "worst case" doesn't also match "estimate"."""
    if not _QUESTION.search(text):
        return []
    low = text.lower()
    hits: list[tuple[int, int, Term]] = []
    for t in GLOSSARY:
        best = max((len(a) for a in t.aliases if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", low)), default=0)
        if best:
            hits.append((low.find(next(a for a in t.aliases if len(a) == best and a in low)), -best, t))
    hits.sort(key=lambda h: (h[0], h[1]))
    out: list[Term] = []
    covered: list[tuple[int, int]] = []
    for pos, neg_len, t in hits:
        span = (pos, pos - neg_len)
        if any(s <= span[0] < e for s, e in covered):  # inside a longer match ("worst case" vs "case")
            continue
        covered.append(span)
        out.append(t)
    return out
