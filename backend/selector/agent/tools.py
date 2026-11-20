"""Read-only agent tools (DESIGN §6.2, §8.3).

- Every tool output carries `src_ref[]`, `plan_year` and `data_vintage`.
- Arguments are schema-validated (pydantic, `extra="forbid"`) and server-bounded (≤5 plans per compare).
- There is no `session_id` argument anywhere: the server injects the session's `ToolContext`; tools can only read
  that session's profile and write its own canvas state.
- No tool fetches arbitrary URLs, runs code, or reaches other sessions. External lookups send only a drug or
  doctor name (RxNav, NPPES) or a ZIP (HUD).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, select

from selector import models as m
from selector.agent.providers.base import ToolCall, ToolSpec
from selector.benefits.dental import NO_ROUTINE, NOT_LISTED, no_dental_row
from selector.config import Settings
from selector.cost import repo
from selector.cost.baseline import Baseline, compare_with_baseline
from selector.cost.engine import PlanEstimate, approximation_notes
from selector.cost.params import CostParams
from selector.geo.hud import HudClient
from selector.geo.resolve import resolve_zip
from selector.lookups import LookupError_, NppesClient, RxNavClient
from selector.profile import MedigapIn, MustHavesIn, Profile, WeightsIn

MAX_COMPARE = 5
CHECKLIST = [
    "Confirm each finalist's premium, drug costs and pharmacy in Medicare Plan Finder (medicare.gov/plan-compare).",
    "Call each plan (phone number on Plan Finder) to confirm your doctors and hospitals are in its network.",
    "Check prior authorization, step therapy and quantity limits for your drugs.",
    "Optional: free, unbiased review with your State Health Insurance Assistance Program (SHIP): 1-877-839-2675.",
    "Questions about Medicare itself: 1-800-MEDICARE (1-800-633-4227).",
]


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResolveLocationArgs(ToolArgs):
    zip: str = Field(pattern=r"^\d{5}$", description="5-digit ZIP code")


class ResolveDrugArgs(ToolArgs):
    name: str = Field(min_length=2, max_length=80, description="Drug name as the user wrote it")


class LookupProviderArgs(ToolArgs):
    last_name: str = Field(min_length=2, max_length=60)
    first_name: str = Field(default="", max_length=60)
    state: str = Field(default="", pattern=r"^([A-Z]{2})?$")


class SearchPlansArgs(ToolArgs):
    category: Literal["all", "ma", "pdp"] = "all"


class FilterPlansArgs(ToolArgs):
    path: Literal["ma", "original", "both"] | None = None
    must_haves: MustHavesIn | None = None
    weights: WeightsIn | None = None
    utilization: Literal["low", "medium", "high"] | None = None
    medigap: MedigapIn | None = Field(default=None, description="Medigap assumption for the baseline row only")


class EstimateCostsArgs(ToolArgs):
    plan_keys: list[str] = Field(min_length=1, max_length=MAX_COMPARE)


class ComparePlansArgs(ToolArgs):
    limit: int = Field(default=3, ge=1, le=MAX_COMPARE)


class ExplainPlanArgs(ToolArgs):
    plan_key: str = Field(pattern=r"^[HRSE]\d{4}_\d{3}_\d{1,3}$")


class GetPlanBenefitsArgs(ToolArgs):
    plan_key: str = Field(pattern=r"^[HRSE]\d{4}_\d{3}_\d{1,3}$")
    category: Literal["dental"] = "dental"


class UpdateCanvasArgs(ToolArgs):
    tab: Literal["table", "chart", "side_by_side", "checklist"]
    plan_keys: list[str] = Field(default_factory=list, max_length=MAX_COMPARE)


class RecordFeedbackArgs(ToolArgs):
    plan_key: str = Field(pattern=r"^[HRSE]\d{4}_\d{3}_\d{1,3}$")
    thumbs: Literal[1, -1]


@dataclass
class ToolContext:
    """Server-side session context. Built by the API from the session store; never from model output."""

    engine: Engine
    settings: Settings
    profile: Profile
    canvas: dict[str, Any] = field(default_factory=dict)
    mode: str = "nosave"
    hud: HudClient | None = None
    rxnav: RxNavClient | None = None
    nppes: NppesClient | None = None
    feedback_hook: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    _vintage: str | None = None

    @property
    def plan_year(self) -> int:
        return self.settings.plan_year

    def data_vintage(self) -> str:
        if self._vintage is None:
            with self.engine.connect() as c:
                rows = c.execute(
                    select(m.ingest_run.c.source_id, m.ingest_run.c.vintage)
                    .where(m.ingest_run.c.plan_year == self.plan_year, m.ingest_run.c.status == "ok")
                    .order_by(m.ingest_run.c.id.desc())
                ).all()
            latest: dict[str, str] = {}
            for sid, v in rows:
                latest.setdefault(sid, v)
            self._vintage = "; ".join(f"{k} {v}" for k, v in sorted(latest.items())) or "not loaded"
        return self._vintage


class ToolFailure(Exception):
    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def _need_county(ctx: ToolContext) -> str:
    if not ctx.profile.county_ssa:
        raise ToolFailure("profile_incomplete", "Please enter your ZIP code and pick your county in the intake form.")
    return ctx.profile.county_ssa


def run_compare_full(ctx: ToolContext) -> tuple[list[PlanEstimate], Baseline, CostParams]:
    """Rank every plan in the county and build the pinned Original Medicare + Part D baseline (addendum A5)."""
    ssa = _need_county(ctx)
    prof = ctx.profile.to_cost_profile()
    with ctx.engine.connect() as c:
        params = repo.load_params(c, ctx.plan_year, ctx.settings)
        plans = repo.plans_in_county(c, ctx.plan_year, ssa)
        rx = repo.load_plan_rx(c, ctx.plan_year, plans, list(prof.drugs))
        med = repo.load_plan_medical(c, ctx.plan_year, plans)
        dental = repo.load_plan_dental(c, ctx.plan_year, plans)
    ests, baseline = compare_with_baseline(plans, rx, med, prof, params, dental)
    return ests, baseline, params


def run_compare(ctx: ToolContext) -> list[PlanEstimate]:
    return run_compare_full(ctx)[0]


def _short(e: dict[str, Any]) -> dict[str, Any]:
    keep = ("plan_key", "plan_name", "organization", "plan_type", "category", "rank", "star_overall",
            "monthly_premium_cents", "total_est_cents", "total_low_cents", "total_high_cents", "worst_case_cents",
            "drug_low_cents", "drug_high_cents", "drugs_covered", "drugs_total", "dropped_reason",
            "delta_vs_baseline_cents")  # fmt: skip
    return {k: e[k] for k in keep}


def _t_resolve_location(ctx: ToolContext, a: ResolveLocationArgs) -> dict[str, Any]:
    with ctx.engine.connect() as c:
        res = resolve_zip(c, a.zip, hud=ctx.hud, may_write_cache=False)
    return {
        "zip": res.zip,
        "counties": [o.as_dict() for o in res.counties],
        "note": res.note,
        "src_ref": [{"source": "S12", "vintage": "HUD USPS ZIP-County", "row": f"zip:{a.zip}", "via": res.source}],
    }


def _t_resolve_drug(ctx: ToolContext, a: ResolveDrugArgs) -> dict[str, Any]:
    if ctx.rxnav is None:
        raise ToolFailure("lookup_unavailable", "Drug search is off. Enter the drug's RxCUI in the intake form.")
    try:
        cands = ctx.rxnav.search(a.name)
    except LookupError_ as e:
        raise ToolFailure("lookup_failed", "The drug search is unavailable right now. Try again shortly.") from e
    with ctx.engine.connect() as c:
        out = [
            {"rxcui": d.rxcui, "name": d.name, "on_a_formulary": repo.drug_on_any_formulary(c, ctx.plan_year, d.rxcui)}
            for d in cands
        ]
    return {"query": a.name, "candidates": out, "src_ref": [{"source": "S10", "vintage": "RxNav live", "row": "drugs"}]}


def _t_lookup_provider(ctx: ToolContext, a: LookupProviderArgs) -> dict[str, Any]:
    if ctx.nppes is None:
        raise ToolFailure("lookup_unavailable", "Doctor search is off.")
    try:
        cands = ctx.nppes.search(a.last_name, a.first_name, a.state or (ctx.profile.state or ""))
    except LookupError_ as e:
        raise ToolFailure("lookup_failed", "The doctor search is unavailable right now.") from e
    return {
        "candidates": [c.__dict__ for c in cands],
        "network_status": "unknown",
        "note": "CMS public files don't include provider networks. Call each plan to confirm this doctor.",
        "src_ref": [{"source": "S11", "vintage": "NPPES live", "row": "npi_search"}],
    }


def _t_search_plans(ctx: ToolContext, a: SearchPlansArgs) -> dict[str, Any]:
    ssa = _need_county(ctx)
    with ctx.engine.connect() as c:
        plans = repo.plans_in_county(c, ctx.plan_year, ssa)
    if a.category == "ma":
        plans = [p for p in plans if p.category != "PDP"]
    elif a.category == "pdp":
        plans = [p for p in plans if p.category == "PDP"]
    return {
        "county_ssa": ssa,
        "plans": [
            {
                "plan_key": p.plan_key,
                "plan_name": p.plan_name,
                "organization": p.org_marketing_name,
                "category": p.category,
                "plan_type": p.plan_type,
                "snp_type": p.snp_type,
                "monthly_premium_cents": p.monthly_premium_cents,
                "moop_cents": p.moop_in_network_cents,
                "star_overall": float(p.star_overall) if p.star_overall is not None else None,
            }
            for p in plans
        ],
        "src_ref": [p.src_ref for p in plans],
    }


def _t_filter_plans(ctx: ToolContext, a: FilterPlansArgs) -> dict[str, Any]:
    upd: dict[str, Any] = {}
    if a.path:
        upd["path"] = a.path
    if a.must_haves is not None:
        upd["must_haves"] = a.must_haves
    if a.weights is not None:
        upd["weights"] = a.weights
    if a.utilization:
        upd["utilization"] = a.utilization
    if a.medigap is not None:
        upd["medigap"] = a.medigap
    ctx.profile = ctx.profile.model_copy(update=upd)
    ctx.canvas["profile_changed"] = True
    ests = run_compare(ctx)
    kept = [e for e in ests if e.rank]
    return {
        "kept": len(kept),
        "dropped": [{"plan_key": e.plan.plan_key, "reason": e.dropped_reason} for e in ests if not e.rank],
        "src_ref": [e.plan.src_ref for e in ests],
    }


def _t_estimate_costs(ctx: ToolContext, a: EstimateCostsArgs) -> dict[str, Any]:
    ests = {e.plan.plan_key: e for e in run_compare(ctx)}
    unknown = [k for k in a.plan_keys if k not in ests]
    if unknown:
        raise ToolFailure("unknown_plan", f"These plans aren't offered in your county: {', '.join(unknown)}.")
    rows = [ests[k].as_dict() for k in a.plan_keys]
    return {"estimates": rows, "src_ref": [r for e in rows for r in e["src_ref"]]}


def _baseline_short(b: dict[str, Any]) -> dict[str, Any]:
    keep = ("plan_key", "plan_name", "organization", "plan_type", "pdp_plan_key", "pdp_plan_name",
            "monthly_premium_cents", "part_b_annual_cents", "part_b_deductible_cents", "part_a_deductible_cents",
            "total_est_cents", "total_low_cents", "total_high_cents", "worst_case_cents", "drug_low_cents",
            "drug_high_cents", "drugs_covered", "drugs_total", "components", "medigap", "notes")  # fmt: skip
    return {k: b[k] for k in keep}


def _t_compare_plans(ctx: ToolContext, a: ComparePlansArgs) -> dict[str, Any]:
    ests, baseline, params = run_compare_full(ctx)
    rows = [e.as_dict() for e in ests]
    base = baseline.as_dict()
    top = [r for r in rows if r["rank"]][: a.limit]
    ctx.canvas.update({"tab": "table", "rows": rows, "baseline": base, "top": [r["plan_key"] for r in top],
                       "notes": approximation_notes(params)})  # fmt: skip
    return {
        "baseline": _baseline_short(base),
        "top": [_short(r) for r in top],
        "ranked_count": sum(1 for r in rows if r["rank"]),
        "dropped": [{"plan_key": r["plan_key"], "reason": r["dropped_reason"]} for r in rows if not r["rank"]],
        "checklist": CHECKLIST,
        "approximation_notes": approximation_notes(params),
        "src_ref": [*base["src_ref"], *(ref for r in top for ref in r["src_ref"])],
    }


def _t_explain_plan(ctx: ToolContext, a: ExplainPlanArgs) -> dict[str, Any]:
    ests = {e.plan.plan_key: e for e in run_compare(ctx)}
    e = ests.get(a.plan_key)
    if e is None:
        raise ToolFailure("unknown_plan", "That plan isn't offered in your county.")
    with ctx.engine.connect() as c:
        benefits = c.execute(
            select(m.pbp_benefit).where(
                m.pbp_benefit.c.plan_year == ctx.plan_year, m.pbp_benefit.c.plan_key == a.plan_key
            )  # fmt: skip
        ).mappings()
        ben = [
            {
                "service": b["service_code"],
                "copay_cents": b["copay_cents"],
                "copay_max_cents": b["copay_max_cents"],
                "coins_pct": float(b["coins_pct"]) if b["coins_pct"] is not None else None,
                "notes": b["notes"],
                "src_ref": b["src_ref"],
            }
            for b in benefits
        ]
    d = e.as_dict()
    d["moop_cents"] = e.plan.moop_in_network_cents
    return {"plan": d, "benefits": ben, "src_ref": [*d["src_ref"], *[b["src_ref"] for b in ben]]}


def plan_benefits(ctx: ToolContext, plan_key: str, category: str = "dental") -> dict[str, Any]:
    """The `plan_dental` row with its src_ref (addendum A4.4). Raises ToolFailure for an unknown plan."""
    with ctx.engine.connect() as c:
        plans = repo.plans_by_key(c, ctx.plan_year, [plan_key])
        if not plans:
            raise ToolFailure("unknown_plan", "That plan isn't in the plan data.")
        d = repo.plan_dental_one(c, ctx.plan_year, plan_key)
    p = plans[0]
    if d is not None:
        dental = d.as_detail()
    else:
        dental = {**no_dental_row(NO_ROUTINE if p.category == "PDP" else NOT_LISTED), "services": []}
    return {
        "plan_key": plan_key,
        "plan_name": p.plan_name,
        "plan_year": ctx.plan_year,
        "category": category,
        "dental": dental,
        "note": "Dental costs are not included in the yearly estimate. Confirm details with the plan.",
        "src_ref": [r for r in (dental.get("src_ref"), p.src_ref) if r],
    }


def _t_get_plan_benefits(ctx: ToolContext, a: GetPlanBenefitsArgs) -> dict[str, Any]:
    return plan_benefits(ctx, a.plan_key, a.category)


def _t_update_canvas(ctx: ToolContext, a: UpdateCanvasArgs) -> dict[str, Any]:
    ctx.canvas["tab"] = a.tab
    if a.plan_keys:
        ctx.canvas["selected"] = a.plan_keys
    return {"ok": True, "tab": a.tab, "selected": a.plan_keys, "src_ref": []}


def _t_record_feedback(ctx: ToolContext, a: RecordFeedbackArgs) -> dict[str, Any]:
    if ctx.feedback_hook is None:
        raise ToolFailure("unavailable", "Use the thumbs buttons on the plan cards to give feedback.")
    res = ctx.feedback_hook("recommendation_rating", {"plan_key": a.plan_key, "thumbs": a.thumbs})
    return {"ok": True, **res, "src_ref": []}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[ToolArgs]
    fn: Callable[[ToolContext, Any], dict[str, Any]]

    def spec(self) -> ToolSpec:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(self.name, self.description, schema)


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("resolve_location", "Map a ZIP code to its county or counties (HUD crosswalk).", ResolveLocationArgs,
             _t_resolve_location),
        Tool("resolve_drug", "Find RxNorm drug candidates for a drug name.", ResolveDrugArgs, _t_resolve_drug),
        Tool("lookup_provider", "Find a doctor's NPI. Network status is never known: tell the user to call the plan.",
             LookupProviderArgs, _t_lookup_provider),
        Tool("search_plans", "List every plan offered in the user's county with basic facts.", SearchPlansArgs,
             _t_search_plans),
        Tool("filter_plans", "Change the user's path, must-haves, weights, utilization or the baseline's Medigap "
             "assumption and re-rank.",
             FilterPlansArgs, _t_filter_plans),
        Tool("estimate_costs", "Estimated yearly costs for up to 5 plans in the user's county.", EstimateCostsArgs,
             _t_estimate_costs),
        Tool("compare_plans", "Rank all plans in the user's county and return the top N (max 5) with the checklist, "
             "plus the pinned 'Original Medicare + Part D (standard)' baseline (unranked; compare plans against it).",
             ComparePlansArgs, _t_compare_plans),
        Tool("explain_plan", "Details for one plan: costs, benefits, drug coverage.", ExplainPlanArgs,
             _t_explain_plan),
        Tool("get_plan_benefits", "Dental benefits of one plan from the CMS plan benefit file: preventive and "
             "comprehensive cost sharing, yearly maximum and limits. Not included in cost estimates.",
             GetPlanBenefitsArgs, _t_get_plan_benefits),
        Tool("update_canvas", "Switch the comparison canvas tab or the selected plans.", UpdateCanvasArgs,
             _t_update_canvas),
        Tool("record_feedback", "Record a thumbs up/down the user gave a recommended plan.", RecordFeedbackArgs,
             _t_record_feedback),
    )
}  # fmt: skip


def tool_specs() -> list[ToolSpec]:
    return [t.spec() for t in TOOLS.values()]


def execute(ctx: ToolContext, call: ToolCall) -> dict[str, Any]:
    """Run one tool call. Always returns a JSON-able dict with `plan_year`, `data_vintage` and `src_ref`."""
    base = {"plan_year": ctx.plan_year, "data_vintage": ctx.data_vintage()}
    tool = TOOLS.get(call.name)
    if tool is None:
        return {**base, "error": "unknown_tool", "user_message": "That action isn't available.", "src_ref": []}
    if call.raw_arguments is not None:
        return {**base, "error": "bad_arguments", "user_message": "Invalid tool arguments.", "src_ref": []}
    try:
        args = tool.args.model_validate(call.arguments)
    except ValidationError as e:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
        return {**base, "error": "bad_arguments", "fields": fields, "user_message": "Invalid tool arguments.",
                "src_ref": []}  # fmt: skip
    try:
        out = tool.fn(ctx, args)
    except ToolFailure as f:
        return {**base, "error": f.code, "user_message": f.user_message, "src_ref": []}
    except repo.NoPlanData:
        return {**base, "error": "no_data", "user_message": "Plan data isn't loaded yet.", "src_ref": []}
    out.setdefault("src_ref", [])
    return {**base, **out}


def to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, default=str, separators=(",", ":"))
