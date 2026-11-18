"""Output validator (DESIGN §2 core rule, §8.3): every dollar amount, percentage, star rating and plan ID in the
model's answer must come from a tool output in this conversation; plus the policy checks.

Matching is tolerant of formatting only: `$1,234.50`, `$1234.5` and `$1,235` (whole-dollar rounding) all match a
tool value of 123450 cents. Phone numbers, years and small counts are not checked.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from selector.agent.policy import policy_problems

MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
PCT = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,2})?)\s?%")
STARS = re.compile(r"(?<![\w.])([1-5](?:\.[05])?)[\s-]*(?:out of 5\s*)?stars?\b", re.I)
PLAN_ID = re.compile(r"\b([HRSE]\d{4})[-_ ](\d{3})(?:[-_ ](\d{1,3}))?\b")
ALWAYS_OK_MONEY = {Decimal("0"), Decimal("35")}  # $0 and the $35/month insulin cap are statutory facts


@dataclass
class Facts:
    money: set[Decimal] = field(default_factory=set)
    numbers: set[Decimal] = field(default_factory=set)
    plan_keys: set[str] = field(default_factory=set)

    def add(self, obj: Any, key: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                self.add(v, str(k))
        elif isinstance(obj, list | tuple):
            for v in obj:
                self.add(v, key)
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, int | float | Decimal):
            d = Decimal(str(obj))
            if key.endswith("_cents") or key.endswith("_cents_list"):
                self.money.add(d / 100)
            else:
                self.numbers.add(d)
        elif isinstance(obj, str):
            for m in PLAN_ID.finditer(obj):
                self.plan_keys.add(normalize_plan_id(m))
            if key in ("coins_pct", "coins_max_pct"):
                with contextlib.suppress(InvalidOperation):
                    self.numbers.add(Decimal(obj))

    def extend(self, results: Iterable[Any]) -> None:
        for r in results:
            self.add(r)


def normalize_plan_id(m: re.Match[str]) -> str:
    return f"{m.group(1)}_{m.group(2)}_{int(m.group(3) or 0)}"


def _money_ok(v: Decimal, facts: Facts, whole: bool) -> bool:
    if v in ALWAYS_OK_MONEY or v in facts.money:
        return True
    if whole:
        return any(f.quantize(Decimal("1"), rounding=ROUND_HALF_UP) == v for f in facts.money)
    return False


@dataclass
class Validation:
    ok: bool
    problems: list[str]


def validate(text: str, facts: Facts) -> Validation:
    problems: list[str] = []
    for m in MONEY.finditer(text):
        v = Decimal(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        if not _money_ok(v, facts, whole=m.group(2) is None):
            problems.append(f"unsupported amount {m.group(0)}")
    for m in PCT.finditer(text):
        v = Decimal(m.group(1))
        if v not in facts.numbers and v not in (Decimal(20), Decimal(100)):
            problems.append(f"unsupported percentage {m.group(0)}")
    for m in STARS.finditer(text):
        if Decimal(m.group(1)) not in facts.numbers:
            problems.append(f"unsupported star rating {m.group(0)}")
    for m in PLAN_ID.finditer(text):
        if normalize_plan_id(m) not in facts.plan_keys:
            problems.append(f"unknown plan id {m.group(0)}")
    problems += policy_problems(text)
    return Validation(not problems, problems)
