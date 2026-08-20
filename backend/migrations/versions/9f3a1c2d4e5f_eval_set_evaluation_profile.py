"""eval set evaluation profile

Revision ID: 9f3a1c2d4e5f
Revises: c1a7e93b40df
Create Date: 2026-08-19 22:15:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "9f3a1c2d4e5f"
down_revision: str | None = "c1a7e93b40df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_set",
        sa.Column(
            "evaluation_profile_json",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_set", "evaluation_profile_json")
