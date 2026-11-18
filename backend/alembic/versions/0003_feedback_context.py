"""feedback: confidence and context_json

DESIGN §7: the session-outcome card asks how confident the user is, and bug reports carry page/view state, app,
prompt and model versions and the last tool-call ids (never message content). Neither had a column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("confidence", sa.SmallInteger(), nullable=True))
    op.add_column("feedback", sa.Column("context_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "context_json")
    op.drop_column("feedback", "confidence")
