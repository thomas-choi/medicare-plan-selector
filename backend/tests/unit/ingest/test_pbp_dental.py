"""WP12 (addendum A4): the PBP b16 dental parser on the committed 10-row sample, summaries and must-haves."""

from __future__ import annotations

import pytest

from selector.agent.validator import Facts, validate
from selector.benefits.dental import NO_ROUTINE, NOT_LISTED, PlanDental, dental_drop_reason
from selector.cost.baseline import compare_with_baseline
from selector.cost.engine import CostProfile, MustHaves
from selector.ingest.parsers import HeaderMismatch, decode
from selector.ingest.parsers.pbp_dental import cost_text, parse_dental
from tests.cms_fixtures import FIX
from tests.unit.cost.factories import PARAMS, medical, plan_info, plan_rx

ROWS = {r["plan_key"]: r for r in parse_dental(decode((FIX / "b16.txt").read_bytes()), "2027-pbp-20261001")}


def _dental(key: str) -> PlanDental:
    return PlanDental.from_row(ROWS[key])


def test_dn1_parser_maxima_periods_shared_and_optional() -> None:
    assert len(ROWS) == 10
    own = ROWS["H0062_011_0"]  # comprehensive has its own maximum
    assert own["comprehensive_max_shared"] is False and own["comprehensive_max_cents"] == 400_000
    assert own["comprehensive_max_period"] == "year"
    six = ROWS["H1993_001_0"]
    assert six["preventive_max_period"] == "6m" and six["preventive_max_cents"] is not None
    opt = ROWS["H0609_054_0"]  # optional supplemental only
    assert not opt["has_preventive"] and not opt["has_comprehensive"] and opt["optional_supplemental"]
    none = ROWS["H0016_001_0"]
    assert not (none["has_preventive"] or none["has_comprehensive"] or none["optional_supplemental"])
    both = ROWS["H0028_017_0"]
    assert both["has_preventive"] and both["optional_supplemental"]
    assert all(r["src_ref"]["source"] == "S2" and r["src_ref"]["row"].startswith("b16:") for r in ROWS.values())
    assert all(len(s["limit_text"] or "") <= 512 for r in ROWS.values() for s in r["services_json"])


def test_dn2_golden_h0028_028_0() -> None:
    g = ROWS["H0028_028_0"]
    assert g["has_preventive"] and g["has_comprehensive"] and g["has_medicare_covered"]
    assert g["preventive_max_cents"] == 50_000 and g["preventive_max_period"] == "year"
    assert g["comprehensive_max_shared"] is True and g["comprehensive_max_cents"] is None
    svc = {s["code"]: s for s in g["services_json"]}
    assert svc["prm"]["coins_min_pct"] == svc["prm"]["coins_max_pct"] == 50.0  # dentures 50% coinsurance
    assert svc["pc"]["cost"] == "$0" and svc["oe"]["cost"] == "$0" and svc["rs"]["cost"] == "0–50%"
    assert svc["mc"]["copay_min_cents"] == 3_500  # Medicare-covered dental $35 copay
    assert g["src_ref"] == {"source": "S2", "vintage": "2027-pbp-20261001", "row": "b16:H0028_028_0"}
    d = _dental("H0028_028_0")
    assert d.summary() == "Preventive $0 · Comprehensive 0–50% · Max $500/yr (shared)"
    assert d.yearly_max_cents() == 50_000


def test_summaries_for_other_shapes() -> None:
    assert _dental("H0016_001_0").summary() == NO_ROUTINE
    assert _dental("H0609_054_0").summary() == "Optional dental package only (extra premium)"
    assert _dental("H0062_011_0").summary() == "Preventive $0 · Comprehensive $0 · Comprehensive max $4,000/yr"
    six = _dental("H1993_001_0")
    assert "every 6 months" in six.summary()
    assert six.yearly_max_cents() == 2 * ROWS["H1993_001_0"]["preventive_max_cents"]


def test_cost_text() -> None:
    assert cost_text({}) == "$0"
    assert cost_text({"copay_min_cents": 0, "copay_max_cents": 5_000}) == "$0–$50"
    assert cost_text({"coins_min_pct": 50.0, "coins_max_pct": 50.0}) == "50%"
    assert cost_text({"copay_min_cents": 2_000, "copay_max_cents": 2_000, "coins_min_pct": 0.0,
                      "coins_max_pct": 50.0}) == "$20 + 0–50%"  # fmt: skip


def test_header_contract() -> None:
    with pytest.raises(HeaderMismatch):
        list(parse_dental("pbp_a_hnumber\tpbp_a_plan_identifier\tsegment_id\nH0001\t001\t0\n", "v"))


def _county() -> tuple[list, dict, dict, dict]:  # type: ignore[type-arg]
    plans = [
        plan_info("H0028_028_0", org="A"),
        plan_info("H0016_001_0", org="B"),
        plan_info("H0609_054_0", org="C"),
        plan_info("H9999_001_0", org="D"),  # MA plan without a b16 row
        plan_info("S0001_001_0", category="PDP", org="E", premium_c=None, premium_d=500),
    ]
    rx = {p.plan_key: plan_rx({"1": 1}, key=p.plan_key) for p in plans}
    med = {p.plan_key: medical(p.plan_key) for p in plans if p.category != "PDP"}
    dental = {k: _dental(k) for k in ("H0028_028_0", "H0016_001_0", "H0609_054_0")}
    return plans, rx, med, dental


def test_dn3_pdp_and_baseline_no_routine_dental_ma_without_row_not_listed() -> None:
    plans, rx, med, dental = _county()
    ests, b = compare_with_baseline(plans, rx, med, CostProfile(), PARAMS, dental)
    rows = {e.plan.plan_key: e.as_dict()["dental"] for e in ests}
    assert rows["S0001_001_0"]["summary"] == NO_ROUTINE
    assert rows["H9999_001_0"]["summary"] == NOT_LISTED and rows["H9999_001_0"]["listed"] is False
    assert rows["H0028_028_0"]["summary"].startswith("Preventive $0")
    assert b.as_dict()["dental"]["summary"].startswith(NO_ROUTINE)


def test_dn4_includes_dental_drops_only_plans_without_preventive() -> None:
    plans, rx, med, dental = _county()
    profile = CostProfile(path="ma", must_haves=MustHaves(dental=True))
    ests, b = compare_with_baseline(plans, rx, med, profile, PARAMS, dental)
    reasons = {e.plan.plan_key: e.dropped_reason for e in ests}
    assert reasons["H0028_028_0"] is None
    assert reasons["H0016_001_0"] == "No preventive dental benefit (you asked for dental)."
    assert reasons["H9999_001_0"] == "No preventive dental benefit (you asked for dental)."
    assert "optional package" in (reasons["H0609_054_0"] or "")
    assert any("routine dental" in n for n in b.as_dict()["notes"])  # the baseline is never dropped
    hi = CostProfile(path="ma", must_haves=MustHaves(dental_min_max_cents=100_000))
    ests2 = {e.plan.plan_key: e for e in compare_with_baseline(plans, rx, med, hi, PARAMS, dental)[0]}
    assert "below your $1,000" in (ests2["H0028_028_0"].dropped_reason or "")
    assert dental_drop_reason(_dental("H0028_028_0"), False, None) is None


def test_dn5_validator_rejects_dental_amount_not_in_a_tool_row() -> None:
    d = _dental("H0028_028_0").as_detail()
    facts = Facts()
    facts.add({"dental": d})
    assert validate("Its dental maximum is $500 a year and dentures cost 50%.", facts).ok
    bad = validate("Its dental maximum is $1,500 a year.", facts)
    assert not bad.ok and any("$1,500" in p for p in bad.problems)
