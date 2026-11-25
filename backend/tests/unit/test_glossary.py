"""The app glossary: one source for the Important info dialog, the system prompt and the Demo provider."""

from __future__ import annotations

import pytest

from selector.agent.prompts import PROMPT_VERSION, system_prompt
from selector.agent.validator import Facts, validate
from selector.glossary import GLOSSARY, as_list, prompt_block, terms_asked


@pytest.mark.parametrize(
    ("question", "ids"),
    [
        ('What is the column "Est. yearly cost"?', ["est_yearly_cost"]),
        ("Is the worst case my deductible?", ["worst_case", "deductible"]),
        ("What's the difference between Worst case and Est. yearly cost?", ["worst_case", "est_yearly_cost"]),
        ("What does MOOP mean", ["moop"]),
        ("what is vs. standard?", ["vs_standard"]),
        ("Compare plans and rank them", []),  # not a question about a term
        ("Explain the plans", []),
    ],
)
def test_terms_asked(question: str, ids: list[str]) -> None:
    assert [t.id for t in terms_asked(question)] == ids


def test_every_entry_passes_the_chat_validator() -> None:
    """No amounts, percentages, star numbers, plan IDs or policy phrases: the Demo provider and a model can quote it."""
    for t in GLOSSARY:
        v = validate(f"{t.title}: {t.text}", Facts())
        assert v.ok, (t.id, v.problems)


def test_ids_unique_and_exposed() -> None:
    assert len({t.id for t in GLOSSARY}) == len(GLOSSARY)
    assert [e["id"] for e in as_list()] == [t.id for t in GLOSSARY]


def test_system_prompt_carries_the_glossary() -> None:
    assert PROMPT_VERSION == "v3"
    s = system_prompt().format(plan_year=2027, profile="{}", glossary=prompt_block())
    assert "- **Worst case**: " in s and "{glossary}" not in s
