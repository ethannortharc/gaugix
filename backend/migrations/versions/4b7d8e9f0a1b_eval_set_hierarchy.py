"""eval set hierarchy and frozen run paths

Revision ID: 4b7d8e9f0a1b
Revises: 9f3a1c2d4e5f
Create Date: 2026-08-19 23:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "4b7d8e9f0a1b"
down_revision: str | None = "9f3a1c2d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_set_node",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tags_json",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "provenance_json",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["eval_set_node.id"]),
        sa.ForeignKeyConstraint(["set_id"], ["eval_set.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_set_node_name", "eval_set_node", ["name"])
    op.create_index("ix_eval_set_node_parent_id", "eval_set_node", ["parent_id"])
    op.create_index(
        "ix_eval_set_node_parent_position",
        "eval_set_node",
        ["set_id", "parent_id", "position"],
    )
    op.create_index("ix_eval_set_node_set_id", "eval_set_node", ["set_id"])

    with op.batch_alter_table("set_membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_set_membership_node_id_eval_set_node", "eval_set_node", ["node_id"], ["id"]
        )
        batch_op.create_index("ix_set_membership_node_id", ["node_id"], unique=False)

    with op.batch_alter_table("run_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "node_path_json",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.add_column(
            sa.Column(
                "node_path_ids_json",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.create_index("ix_run_item_node_id", ["node_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("run_item", schema=None) as batch_op:
        batch_op.drop_index("ix_run_item_node_id")
        batch_op.drop_column("node_path_ids_json")
        batch_op.drop_column("node_path_json")
        batch_op.drop_column("node_id")

    with op.batch_alter_table("set_membership", schema=None) as batch_op:
        batch_op.drop_index("ix_set_membership_node_id")
        batch_op.drop_constraint("fk_set_membership_node_id_eval_set_node", type_="foreignkey")
        batch_op.drop_column("node_id")

    op.drop_index("ix_eval_set_node_set_id", table_name="eval_set_node")
    op.drop_index("ix_eval_set_node_parent_position", table_name="eval_set_node")
    op.drop_index("ix_eval_set_node_parent_id", table_name="eval_set_node")
    op.drop_index("ix_eval_set_node_name", table_name="eval_set_node")
    op.drop_table("eval_set_node")
