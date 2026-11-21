"""medicare_params: Original Medicare and Medigap amounts per plan year

Design v0.4 addendum A5.2 / WP10: the 2027 Part A/B amounts (Federal Register 2026-23601 and 2026-23603) and the
Medigap high-deductible and Plan N amounts, loaded by the ingest from cited values in sources/<year>.yaml. Replaces
the "2026 placeholder" Part B settings.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "medicare_params",
        sa.Column("plan_year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("part_b_premium_cents", sa.BigInteger(), nullable=False),
        sa.Column("part_b_deductible_cents", sa.BigInteger(), nullable=False),
        sa.Column("part_b_coins_pct", sa.SmallInteger(), nullable=False),
        sa.Column("part_a_deductible_cents", sa.BigInteger(), nullable=False),
        sa.Column("part_a_day61_cents", sa.BigInteger(), nullable=False),
        sa.Column("part_a_lifetime_cents", sa.BigInteger(), nullable=False),
        sa.Column("snf_day21_cents", sa.BigInteger(), nullable=False),
        sa.Column("medigap_hd_deductible_cents", sa.BigInteger(), nullable=False),
        sa.Column("medigap_n_office_copay_cents", sa.BigInteger(), nullable=False),
        sa.Column("medigap_n_er_copay_cents", sa.BigInteger(), nullable=False),
        sa.Column("src_ref", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("plan_year", name=op.f("pk_medicare_params")),
    )


def downgrade() -> None:
    op.drop_table("medicare_params")
