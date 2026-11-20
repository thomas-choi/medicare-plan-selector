"""plan_dental: dental benefits per plan from CMS PBP b16

Design v0.4 addendum A4 / WP12. Plan data keyed by plan_year (swapped by the ingest like the other S2 tables).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERIODS = ("year", "2y", "3y", "6m", "3m", "month", "other")


def upgrade() -> None:
    op.create_table(
        "plan_dental",
        sa.Column("plan_year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("plan_key", sa.String(length=16), nullable=False),
        sa.Column("has_medicare_covered", sa.Boolean(), nullable=False),
        sa.Column("has_preventive", sa.Boolean(), nullable=False),
        sa.Column("has_comprehensive", sa.Boolean(), nullable=False),
        sa.Column("preventive_max_cents", sa.BigInteger(), nullable=True),
        sa.Column("preventive_max_period", sa.Enum(*PERIODS, name="dental_period"), nullable=True),
        sa.Column("comprehensive_max_cents", sa.BigInteger(), nullable=True),
        sa.Column("comprehensive_max_period", sa.Enum(*PERIODS, name="dental_period"), nullable=True),
        sa.Column("comprehensive_max_shared", sa.Boolean(), nullable=True),
        sa.Column("optional_supplemental", sa.Boolean(), nullable=False),
        sa.Column("services_json", sa.JSON(), nullable=False),
        sa.Column("src_ref", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("plan_year", "plan_key", name=op.f("pk_plan_dental")),
    )


def downgrade() -> None:
    op.drop_table("plan_dental")
