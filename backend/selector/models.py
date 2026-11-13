"""MySQL schema (DESIGN §5). SQLAlchemy Core tables; Alembic migrations are the source of truth for DDL.

Deviations from the design text: `ingest_run.rows` → `row_count` and `recommendation.rank` → `rank_pos`,
because ROWS and RANK are reserved words in MySQL 8.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.mysql import MEDIUMBLOB, VARBINARY

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING)

Cents = BigInteger
Blob = LargeBinary().with_variant(MEDIUMBLOB(), "mysql")
SmallBlob = LargeBinary(1024).with_variant(VARBINARY(1024), "mysql")


def _plan_year() -> Column[int]:
    return Column("plan_year", SmallInteger, primary_key=True, autoincrement=False)


# ---------------------------------------------------------------- public plan data (keyed by plan_year)

ingest_run = Table(
    "ingest_run",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("plan_year", SmallInteger, nullable=False),
    Column("source_id", String(32), nullable=False),
    Column("url", String(512), nullable=False),
    Column("vintage", String(32), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("row_count", Integer, nullable=False, default=0),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Index(None, "plan_year", "source_id"),
)

county = Table(
    "county",
    metadata,
    Column("fips", String(5), primary_key=True),
    Column("ssa_code", String(5)),
    Column("state", String(2), nullable=False),
    Column("name", String(64), nullable=False),
    Column("ma_region_code", String(8)),
    Column("pdp_region_code", String(8)),
    Index(None, "state", "name"),
)

zip_county_cache = Table(
    "zip_county_cache",
    metadata,
    Column("zip", String(5), primary_key=True),
    Column("fips", String(5), primary_key=True),
    Column("res_ratio", Numeric(10, 8), nullable=False),
    Column("hud_year", SmallInteger, nullable=False),
    Column("hud_quarter", SmallInteger, nullable=False),
    # Day granularity only: a timestamp would hint at when someone looked a ZIP up.
    Column("fetched_at", Date, nullable=False),
)

plan = Table(
    "plan",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("contract_id", String(5), nullable=False),
    Column("plan_id", String(3), nullable=False),
    Column("segment_id", String(3), nullable=False),
    Column("category", String(8), nullable=False),  # MA | MAPD | PDP
    Column("plan_type", String(64), nullable=False),
    Column("org_marketing_name", String(255), nullable=False),
    Column("plan_name", String(255), nullable=False),
    Column("snp_type", String(32)),
    Column("sanctioned", Boolean, nullable=False, default=False),
    Column("part_c_premium_cents", Cents),
    Column("part_d_total_premium_cents", Cents),
    Column("part_d_deductible_cents", Cents),
    Column("moop_in_network_cents", Cents),
    Column("star_overall", Numeric(2, 1)),
    Column("star_part_c", Numeric(2, 1)),
    Column("star_part_d", Numeric(2, 1)),
    Column("src_ref", JSON, nullable=False),
)

plan_county = Table(
    "plan_county",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("fips", String(5), primary_key=True),
    Index(None, "plan_year", "fips"),
)

pbp_benefit = Table(
    "pbp_benefit",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("service_code", String(16), primary_key=True),
    Column("copay_cents", Cents),
    Column("coins_pct", Numeric(5, 2)),
    Column("notes", String(512)),
    Column("src_ref", JSON, nullable=False),
)

formulary = Table(
    "formulary",
    metadata,
    _plan_year(),
    Column("formulary_id", String(16), primary_key=True),
    Column("ndc", String(11), primary_key=True),
    Column("rxcui", String(16)),
    Column("tier", SmallInteger, nullable=False),
    Column("prior_auth", Boolean, nullable=False, default=False),
    Column("step", Boolean, nullable=False, default=False),
    Column("qty_limit", Boolean, nullable=False, default=False),
    Column("qty_amount", Numeric(12, 3)),
    Column("qty_days", SmallInteger),
    Column("src_ref", JSON, nullable=False),
    Index(None, "plan_year", "rxcui"),
)

plan_formulary = Table(
    "plan_formulary",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("formulary_id", String(16), nullable=False),
)

tier_cost = Table(
    "tier_cost",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("tier", SmallInteger, primary_key=True),
    Column("phase", String(16), primary_key=True),  # deductible | initial
    Column("pharmacy_type", String(24), primary_key=True),  # pref_retail | retail | mail | pref_mail
    Column("days_supply", SmallInteger, primary_key=True),
    Column("copay_cents", Cents),
    Column("coins_pct", Numeric(5, 2)),
    Column("src_ref", JSON, nullable=False),
)

insulin_cost = Table(
    "insulin_cost",
    metadata,
    _plan_year(),
    Column("plan_key", String(16), primary_key=True),
    Column("tier", SmallInteger, primary_key=True),
    Column("pharmacy_type", String(24), primary_key=True),
    Column("days_supply", SmallInteger, primary_key=True),
    Column("copay_cents", Cents, nullable=False),
    Column("src_ref", JSON, nullable=False),
)

drug_price_proxy = Table(
    "drug_price_proxy",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("plan_year", SmallInteger, nullable=False),
    Column("plan_key", String(16)),  # NULL = state/national median proxy
    Column("ndc", String(11), nullable=False),
    Column("days_supply", SmallInteger, nullable=False),
    Column("unit_cost_milli", BigInteger, nullable=False),  # thousandths of a cent per unit
    Column("source_year", SmallInteger, nullable=False),
    Column("src_ref", JSON, nullable=False),
    Index(None, "plan_year", "ndc", "plan_key"),
)

part_d_params = Table(
    "part_d_params",
    metadata,
    Column("plan_year", SmallInteger, primary_key=True, autoincrement=False),
    Column("std_deductible_cents", Cents, nullable=False),
    Column("oop_threshold_cents", Cents, nullable=False),
    Column("src_ref", JSON, nullable=False),
)

PLAN_TABLES = (
    "ingest_run",
    "county",
    "zip_county_cache",
    "plan",
    "plan_county",
    "pbp_benefit",
    "formulary",
    "plan_formulary",
    "tier_cost",
    "insulin_cost",
    "drug_price_proxy",
    "part_d_params",
)

# ---------------------------------------------------------------- user and session data (saved mode only)

session = Table(
    "session",
    metadata,
    Column("id_hash", String(64), primary_key=True),
    Column("created_at", DateTime, nullable=False),
    Column("last_seen_at", DateTime, nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("consent_version", String(16), nullable=False),
    Column("consent_profile", Boolean, nullable=False),
    Column("consent_feedback_phi", Boolean, nullable=False, default=False),
    Column("plan_year", SmallInteger, nullable=False),
    Column("ip_prefix_hash", String(64)),
    Column("deleted_at", DateTime),
    Index(None, "last_seen_at"),
)


def _session_fk(nullable: bool, ondelete: str) -> Column[str]:
    return Column(
        "session_id", String(64), ForeignKey("session.id_hash", ondelete=ondelete), nullable=nullable
    )


profile = Table(
    "profile",
    metadata,
    Column("session_id", String(64), ForeignKey("session.id_hash", ondelete="CASCADE"), primary_key=True),
    Column("county_fips", String(5)),
    Column("path", String(16)),
    Column("budget_json", JSON),
    Column("utilization_json", JSON),
    Column("must_haves_json", JSON),
    Column("zip_enc", SmallBlob),
    Column("drugs_enc", Blob),
    Column("providers_enc", Blob),
    Column("key_version", SmallInteger, nullable=False),
)

chat_msg = Table(
    "chat_msg",
    metadata,
    Column("session_id", String(64), ForeignKey("session.id_hash", ondelete="CASCADE"), primary_key=True),
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("role", String(16), nullable=False),
    Column("content_enc", Blob, nullable=False),
    Column("key_version", SmallInteger, nullable=False),
    Column("tool_calls_json", JSON),
    Column("model_id", String(128)),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("created_at", DateTime, nullable=False),
)

recommendation = Table(
    "recommendation",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    _session_fk(nullable=True, ondelete="SET NULL"),
    Column("plan_year", SmallInteger, nullable=False),
    Column("rank_pos", SmallInteger, nullable=False),
    Column("plan_key", String(16), nullable=False),
    Column("est_total_cents", Cents, nullable=False),
    Column("worst_case_cents", Cents, nullable=False),
    Column("weights_json", JSON, nullable=False),
    Column("data_vintage", String(64), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

feedback = Table(
    "feedback",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    _session_fk(nullable=True, ondelete="SET NULL"),
    Column("kind", String(32), nullable=False),
    Column(
        "recommendation_id", BigInteger, ForeignKey("recommendation.id", ondelete="SET NULL"), nullable=True
    ),
    Column("rating", SmallInteger),
    Column("thumbs", SmallInteger),  # +1 / -1
    Column("chosen_plan_key", String(16)),
    Column("enrolled", Boolean),
    Column("text_redacted", Text),
    Column("text_raw_enc", Blob),
    Column("key_version", SmallInteger),
    Column("phi_opt_in", Boolean, nullable=False, default=False),
    Column("mode", Enum("saved", "nosave", name="feedback_mode"), nullable=False),
    Column("app_version", String(64), nullable=False),
    Column("prompt_version", String(32), nullable=False),
    Column("model_id", String(128), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("triage_status", String(16), nullable=False, default="new"),
    Column("triage_note", String(512)),
    Index(None, "kind", "created_at"),
)

usage_ledger = Table(
    "usage_ledger",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("day", Date, nullable=False),
    Column("session_id_hash", String(64), nullable=False),
    Column("ip_prefix_hash", String(64)),
    Column("provider", String(32), nullable=False),
    Column("model", String(128), nullable=False),
    Column("tokens_in", Integer, nullable=False),
    Column("tokens_out", Integer, nullable=False),
    Column("cost_micro_usd", BigInteger, nullable=False),
    Index(None, "session_id_hash"),
    Index(None, "day"),
)

usage_daily = Table(
    "usage_daily",
    metadata,
    Column("day", Date, primary_key=True),
    Column("provider", String(32), primary_key=True),
    Column("model", String(128), primary_key=True),
    Column("mode", String(8), primary_key=True),
    Column("tokens_in", BigInteger, nullable=False, default=0),
    Column("tokens_out", BigInteger, nullable=False, default=0),
    Column("cost_micro_usd", BigInteger, nullable=False, default=0),
)

feedback_counter = Table(
    "feedback_counter",
    metadata,
    Column("day", Date, primary_key=True),
    Column("plan_year", SmallInteger, primary_key=True, autoincrement=False),
    Column("kind", String(32), primary_key=True),
    Column("value", String(32), primary_key=True),
    Column("prompt_version", String(32), primary_key=True),
    Column("model_id", String(128), primary_key=True),
    Column("count", Integer, nullable=False, default=0),
)

consent_log = Table(
    "consent_log",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    _session_fk(nullable=False, ondelete="CASCADE"),
    Column("consent_version", String(16), nullable=False),
    Column("choice_json", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

admin_audit = Table(
    "admin_audit",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("admin_subject", String(128), nullable=False),
    Column("action", String(64), nullable=False),
    Column("target", String(255), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

# Tables a No-save request must never write (DESIGN §8.5, test N1/N2).
USER_TABLES = frozenset(
    {"session", "profile", "chat_msg", "recommendation", "consent_log", "feedback", "usage_ledger"}
)
# Aggregates without session/IP linkage that a No-save request may write.
NOSAVE_ALLOWED_TABLES = frozenset({"feedback_counter", "usage_daily"})
