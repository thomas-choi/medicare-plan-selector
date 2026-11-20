"""The user's intake profile (DESIGN §6.3 slots). Server-validated; limits from DESIGN §8.2."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from selector.cost.engine import CostProfile, MustHaves
from selector.cost.params import Weights
from selector.cost.part_d import DrugInput

MAX_DRUGS = 30
MAX_PROVIDERS = 15


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DrugIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    rxcui: str | None = Field(default=None, pattern=r"^\d{1,10}$")
    ndc: str | None = Field(default=None, pattern=r"^\d{11}$")
    days_supply: Literal[30, 60, 90] = 30
    pharmacy: Literal["retail", "pref_retail", "mail", "pref_mail"] = "retail"
    price_per_fill_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    is_insulin: bool = False

    def to_input(self) -> DrugInput:
        return DrugInput(
            name=self.name,
            rxcui=self.rxcui,
            ndc=self.ndc,
            days_supply=self.days_supply,
            pharmacy=self.pharmacy,
            user_price_cents=self.price_per_fill_cents,
            is_insulin=self.is_insulin or "insulin" in self.name.lower(),
        )


class ProviderIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    npi: str | None = Field(default=None, pattern=r"^\d{10}$")


class MustHavesIn(_Strict):
    all_drugs_covered: bool = False
    plan_types: list[Literal["HMO", "PPO", "PFFS", "MSA", "POS"]] = Field(default_factory=list, max_length=5)
    min_stars: float | None = Field(default=None, ge=1, le=5)
    max_moop_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    max_monthly_premium_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    dental: bool = False
    dental_min_max_cents: int | None = Field(default=None, ge=0, le=10_000_000)


class WeightsIn(_Strict):
    total_cost: float = Field(default=0.6, ge=0, le=1)
    worst_case: float = Field(default=0.2, ge=0, le=1)
    stars: float = Field(default=0.1, ge=0, le=1)
    must_have_fit: float = Field(default=0.1, ge=0, le=1)


class MedigapIn(_Strict):
    """An assumption for the baseline row (addendum A5): which Medigap plan, and the user's own premium quote."""

    plan: Literal["G", "N", "HDG"] | None = None
    monthly_premium_cents: int | None = Field(default=None, ge=0, le=500_000)


class Profile(_Strict):
    zip: str | None = Field(default=None, pattern=r"^\d{5}$")
    county_ssa: str | None = Field(default=None, pattern=r"^\d{5}$")
    county_name: str | None = Field(default=None, max_length=64)
    state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    path: Literal["ma", "original", "both"] = "both"
    drugs: list[DrugIn] = Field(default_factory=list, max_length=MAX_DRUGS)
    providers: list[ProviderIn] = Field(default_factory=list, max_length=MAX_PROVIDERS)
    utilization: Literal["low", "medium", "high"] = "medium"
    pharmacy_preference: Literal["retail", "pref_retail", "mail", "pref_mail"] = "retail"
    must_haves: MustHavesIn = Field(default_factory=MustHavesIn)
    weights: WeightsIn = Field(default_factory=WeightsIn)
    snp_eligible: bool = False
    medigap: MedigapIn = Field(default_factory=MedigapIn)
    current_plan_key: str | None = Field(default=None, pattern=r"^[HRSE]\d{4}_\d{3}_\d{1,3}$")

    @field_validator("drugs")
    @classmethod
    def _drug_ids(cls, v: list[DrugIn]) -> list[DrugIn]:
        for d in v:
            if not (d.rxcui or d.ndc):
                raise ValueError(f"drug {d.name!r} needs an RxCUI or NDC (use the drug search)")
        return v

    def to_cost_profile(self) -> CostProfile:
        mh = self.must_haves
        w = self.weights
        return CostProfile(
            path=self.path,
            drugs=tuple(d.to_input() for d in self.drugs),
            utilization=self.utilization,
            must_haves=MustHaves(
                all_drugs_covered=mh.all_drugs_covered,
                plan_types=tuple(mh.plan_types),
                min_stars=mh.min_stars,
                max_moop_cents=mh.max_moop_cents,
                max_monthly_premium_cents=mh.max_monthly_premium_cents,
                dental=mh.dental,
                dental_min_max_cents=mh.dental_min_max_cents,
            ),
            snp_eligible=self.snp_eligible,
            weights=Weights(w.total_cost, w.worst_case, w.stars, w.must_have_fit),
            medigap_plan=self.medigap.plan,
            medigap_premium_monthly_cents=self.medigap.monthly_premium_cents if self.medigap.plan else None,
        )

    def summary_for_prompt(self) -> dict[str, Any]:
        """What the model sees about the user: slots only, user text wrapped as data by the orchestrator."""
        return {
            "county": f"{self.county_name}, {self.state}" if self.county_name else None,
            "path": self.path,
            "drug_count": len(self.drugs),
            "drugs": [d.name for d in self.drugs],
            "doctor_count": len(self.providers),
            "utilization": self.utilization,
            "must_haves": self.must_haves.model_dump(exclude_defaults=True),
            "snp_eligible": self.snp_eligible,
            "medigap_assumption": self.medigap.plan,
        }
