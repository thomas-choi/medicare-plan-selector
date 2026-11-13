"""S1 CMS Landscape (one row per plan × county). Produces one `plan` row per plan_key."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from selector.ingest.normalize import blank, money_to_cents, plan_key, src_ref, star, yn
from selector.ingest.parsers import read_delimited

SOURCE = "S1"
EXPECTED_HEADER = (
    "Contract Year", "Contract Category Type", "US Territory", "State Territory Abbreviation",
    "State Territory Name", "County Name", "Contract ID", "Plan ID", "Segment ID", "Contract Plan ID",
    "Contract Plan Segment ID", "Sanctioned Plan", "Parent Organization Name", "Contract Name",
    "Organization Marketing Name", "Organization Type", "Plan Name", "Plan Type",
    "Enrollment Capacity Limit Accepted", "Enrollment Capacity Limit Amount",
    "Special Needs Plan (SNP) Indicator", "SNP Type", "SNP Institutional Type",
    "Dual Eligible SNP (D-SNP) Integration Status", "D-SNP Applicable Integrated Plan (AIP) Identifier",
    "Chronic or Disabling Condition SNP (C-SNP) Condition Type", "Medicare Zero-Dollar Cost Sharing D-SNP",
    "Part D Coverage Indicator", "National PDP", "Drug Benefit Category", "Drug Benefit Type",
    "Voluntary De Minimis Program Participant", "Part D Basic Premium At or Below Regional Benchmark",
    "Low Income Subsidy (LIS) Auto Enrollment", "Offers Drug Tier with No Part D Deductible",
    "Annual Part D Deductible Amount", "Part D Basic Premium", "Part D Supplemental Premium",
    "Part D Total Premium", "Low Income Premium Subsidy (LIPS) Amount", "Part D LIPS (CMS Pays)",
    "Part D Low Income Beneficiary Premium Amount", "Part D Out-of-Pocket (OOP) Threshold", "Part C Premium",
    "Monthly Consolidated Premium (Part C + D)", "In-Network Maximum Out-of-Pocket (MOOP) Amount",
    "Part C Summary Star Rating", "Part D Summary Star Rating", "Overall Star Rating", "MA Region Code",
    "MA Region", "PDP Region Code", "PDP Region",
)  # fmt: skip

CATEGORY = {"MA-PD": "MAPD", "MA": "MA", "PDP": "PDP", "SNP": "SNP", "Cost": "COST"}


def parse(text: str, vintage: str) -> Iterator[dict[str, Any]]:
    """Yield one plan row per plan_key (the first county row; plan-level fields are identical across counties)."""
    seen: set[str] = set()
    for r in read_delimited(text, ",", EXPECTED_HEADER):
        key = plan_key(r["Contract ID"], r["Plan ID"], r["Segment ID"])
        if key in seen:
            continue
        seen.add(key)
        overall, note = star(r["Overall Star Rating"])
        part_c, _ = star(r["Part C Summary Star Rating"])
        part_d, _ = star(r["Part D Summary Star Rating"])
        has_d = yn(r["Part D Coverage Indicator"]) or r["Contract Category Type"] == "PDP"
        yield {
            "plan_key": key,
            "contract_id": r["Contract ID"].strip(),
            "plan_id": f"{int(r['Plan ID']):03d}",
            "segment_id": str(int(r["Segment ID"])),
            "category": CATEGORY[r["Contract Category Type"].strip()],
            "plan_type": r["Plan Type"].strip(),
            "org_marketing_name": r["Organization Marketing Name"].strip(),
            "plan_name": r["Plan Name"].strip(),
            "snp_type": None if blank(r["SNP Type"]) else r["SNP Type"].strip(),
            "sanctioned": yn(r["Sanctioned Plan"]),
            "part_c_premium_cents": money_to_cents(r["Part C Premium"]),
            "part_d_total_premium_cents": money_to_cents(r["Part D Total Premium"]) if has_d else None,
            "part_d_deductible_cents": money_to_cents(r["Annual Part D Deductible Amount"]) if has_d else None,
            "moop_in_network_cents": money_to_cents(r["In-Network Maximum Out-of-Pocket (MOOP) Amount"]),
            "star_overall": overall,
            "star_part_c": part_c,
            "star_part_d": part_d,
            "star_note": note if overall is None else None,
            "pdp_region_code": None if blank(r["PDP Region Code"]) else r["PDP Region Code"].strip(),
            "ma_region_code": None if blank(r["MA Region Code"]) else r["MA Region Code"].strip(),
            "src_ref": src_ref(SOURCE, vintage, key),
            "_oop_threshold_cents": money_to_cents(r["Part D Out-of-Pocket (OOP) Threshold"]),
        }
