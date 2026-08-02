"""eval_set provenance

A set installed from a benchmark has to be able to say, months later, which
dataset it is: the revision it came from, the checksum of what arrived, the
scorer version that graded it. Without that, "we ran IFEval in August" is a
claim nothing in the database supports.

Revision ID: c1a7e93b40df
Revises: a211244b9eea
Create Date: 2026-08-01 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c1a7e93b40df"
down_revision: str | None = "a211244b9eea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_set",
        sa.Column(
            "provenance_json",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_set", "provenance_json")
