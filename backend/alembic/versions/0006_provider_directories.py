"""directory_endpoint and insurance_plan_map: public provider directory (Plan-Net FHIR) lookups

Design v0.4 addendum A3.5 / WP13. Plan data only (carrier endpoints and their InsurancePlan → plan_key map);
nothing about users. Practitioner results stay in process memory and are never stored.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19 22:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "directory_endpoint",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("org_patterns", sa.JSON(), nullable=False),
        sa.Column("contract_prefixes", sa.JSON(), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.Enum("none", "app_key", "unsupported", name="directory_auth"), nullable=False),
        sa.Column("plan_id_system", sa.String(length=255), nullable=False),
        sa.Column("plan_id_format", sa.String(length=255), nullable=False),
        sa.Column("npi_search", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.String(length=1024), nullable=True),
        sa.Column("verified_at", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_endpoint")),
    )
    op.create_table(
        "insurance_plan_map",
        sa.Column("plan_year", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("plan_key", sa.String(length=16), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("insurance_plan_id", sa.String(length=128), nullable=False),
        sa.Column("network_refs", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("plan_year", "plan_key", name=op.f("pk_insurance_plan_map")),
    )
    op.create_index(op.f("ix_insurance_plan_map_endpoint_id"), "insurance_plan_map", ["endpoint_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_insurance_plan_map_endpoint_id"), table_name="insurance_plan_map")
    op.drop_table("insurance_plan_map")
    op.drop_table("directory_endpoint")
