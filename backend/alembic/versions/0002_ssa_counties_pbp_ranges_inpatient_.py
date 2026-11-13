"""ssa counties, pbp ranges, inpatient intervals, s3 cost fields

CMS plan data is keyed by SSA county code (no FIPS in Landscape/S3/PBP), so `county` is re-keyed on `ssa_code`
and `plan_county` references SSA codes. Both tables only hold rebuildable CMS plan data, so they are recreated.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12 21:19:55.314458

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_county_v2() -> None:
    op.create_table(
        "county",
        sa.Column("ssa_code", sa.String(length=5), nullable=False),
        sa.Column("fips", sa.String(length=5), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("state_name", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("ma_region_code", sa.String(length=8), nullable=True),
        sa.Column("pdp_region_code", sa.String(length=8), nullable=True),
        sa.Column("fips_status", sa.String(length=16), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("src_ref", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("ssa_code", name=op.f("pk_county")),
    )
    op.create_index(op.f("ix_county_fips"), "county", ["fips"], unique=False)
    op.create_index(op.f("ix_county_state_name_name"), "county", ["state_name", "name"], unique=False)


def _create_county_v1() -> None:
    op.create_table(
        "county",
        sa.Column("fips", sa.String(length=5), nullable=False),
        sa.Column("ssa_code", sa.String(length=5), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("ma_region_code", sa.String(length=8), nullable=True),
        sa.Column("pdp_region_code", sa.String(length=8), nullable=True),
        sa.PrimaryKeyConstraint("fips", name=op.f("pk_county")),
    )
    op.create_index(op.f("ix_county_state_name"), "county", ["state", "name"], unique=False)


def _create_plan_county(col: str) -> None:
    op.create_table(
        "plan_county",
        sa.Column("plan_year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("plan_key", sa.String(length=16), nullable=False),
        sa.Column(col, sa.String(length=5), nullable=False),
        sa.PrimaryKeyConstraint("plan_year", "plan_key", col, name=op.f("pk_plan_county")),
    )
    op.create_index(op.f(f"ix_plan_county_plan_year_{col}"), "plan_county", ["plan_year", col], unique=False)


def upgrade() -> None:
    op.drop_table("county")
    _create_county_v2()
    op.drop_table("plan_county")
    _create_plan_county("ssa_code")

    op.create_table(
        "pbp_inpatient_interval",
        sa.Column("plan_year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("plan_key", sa.String(length=16), nullable=False),
        sa.Column("seq", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("begin_day", sa.SmallInteger(), nullable=False),
        sa.Column("end_day", sa.SmallInteger(), nullable=False),
        sa.Column("copay_per_day_cents", sa.BigInteger(), nullable=True),
        sa.Column("coins_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("src_ref", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("plan_year", "plan_key", "seq", name=op.f("pk_pbp_inpatient_interval")),
    )
    op.add_column("insulin_cost", sa.Column("coins_pct", sa.Numeric(precision=5, scale=2), nullable=True))
    op.alter_column("insulin_cost", "copay_cents", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("pbp_benefit", sa.Column("copay_max_cents", sa.BigInteger(), nullable=True))
    op.add_column("pbp_benefit", sa.Column("coins_max_pct", sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column("plan", sa.Column("star_note", sa.String(length=64), nullable=True))
    op.add_column("plan", sa.Column("pdp_region_code", sa.String(length=8), nullable=True))
    op.add_column("plan", sa.Column("ma_region_code", sa.String(length=8), nullable=True))
    op.add_column("plan", sa.Column("part_d_suppressed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tier_cost", sa.Column("coins_min_cents", sa.BigInteger(), nullable=True))
    op.add_column("tier_cost", sa.Column("coins_max_cents", sa.BigInteger(), nullable=True))
    op.add_column("tier_cost", sa.Column("ded_applies", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("tier_cost", sa.Column("specialty", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tier_cost", "specialty")
    op.drop_column("tier_cost", "ded_applies")
    op.drop_column("tier_cost", "coins_max_cents")
    op.drop_column("tier_cost", "coins_min_cents")
    op.drop_column("plan", "part_d_suppressed")
    op.drop_column("plan", "ma_region_code")
    op.drop_column("plan", "pdp_region_code")
    op.drop_column("plan", "star_note")
    op.drop_column("pbp_benefit", "coins_max_pct")
    op.drop_column("pbp_benefit", "copay_max_cents")
    op.execute("DELETE FROM insulin_cost WHERE copay_cents IS NULL")
    op.alter_column("insulin_cost", "copay_cents", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("insulin_cost", "coins_pct")
    op.drop_table("pbp_inpatient_interval")
    op.drop_table("plan_county")
    _create_plan_county("fips")
    op.drop_table("county")
    _create_county_v1()
