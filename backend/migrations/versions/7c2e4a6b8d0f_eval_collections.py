"""generic eval collections and set catalogue metadata

Revision ID: 7c2e4a6b8d0f
Revises: 4b7d8e9f0a1b
Create Date: 2026-08-20 08:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "7c2e4a6b8d0f"
down_revision: str | None = "4b7d8e9f0a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite DDL is non-transactional. If a process is interrupted during a
    # batch table rewrite, Alembic can leave the new table and its temporary
    # copy behind while the version remains at the previous revision. Make the
    # migration safely restartable without touching the original eval_set rows.
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "eval_collection" not in table_names:
        op.create_table(
            "eval_collection",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "visibility",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="primary",
            ),
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
            sa.ForeignKeyConstraint(["parent_id"], ["eval_collection.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key", name="uq_eval_collection_key"),
        )
        op.create_index("ix_eval_collection_key", "eval_collection", ["key"])
        op.create_index("ix_eval_collection_name", "eval_collection", ["name"])
        op.create_index("ix_eval_collection_parent_id", "eval_collection", ["parent_id"])
        op.create_index(
            "ix_eval_collection_parent_position",
            "eval_collection",
            ["parent_id", "position"],
        )
        op.create_index("ix_eval_collection_visibility", "eval_collection", ["visibility"])

    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "_alembic_tmp_eval_set" in table_names:
        op.drop_table("_alembic_tmp_eval_set")
    eval_set_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("eval_set")}
    if "collection_id" not in eval_set_columns:
        # eval_set is referenced by historical run rows. SQLite's batch rewrite
        # drops the original table, which is rejected while foreign-key checks
        # are enabled and references contain data. Toggle the connection pragma
        # outside a transaction, perform the lossless copy, then restore it.
        context = op.get_context()
        with context.autocommit_block():
            op.execute("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table("eval_set", schema=None) as batch_op:
                batch_op.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
                batch_op.add_column(
                    sa.Column("logical_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
                )
                batch_op.add_column(
                    sa.Column("variant", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
                )
                batch_op.add_column(
                    sa.Column(
                        "visibility",
                        sqlmodel.sql.sqltypes.AutoString(),
                        nullable=False,
                        server_default="primary",
                    )
                )
                batch_op.create_foreign_key(
                    "fk_eval_set_collection_id_eval_collection",
                    "eval_collection",
                    ["collection_id"],
                    ["id"],
                )
                batch_op.create_index("ix_eval_set_collection_id", ["collection_id"], unique=False)
                batch_op.create_index("ix_eval_set_logical_key", ["logical_key"], unique=False)
                batch_op.create_index("ix_eval_set_visibility", ["visibility"], unique=False)
        finally:
            with context.autocommit_block():
                op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    with op.batch_alter_table("eval_set", schema=None) as batch_op:
        batch_op.drop_index("ix_eval_set_visibility")
        batch_op.drop_index("ix_eval_set_logical_key")
        batch_op.drop_index("ix_eval_set_collection_id")
        batch_op.drop_constraint("fk_eval_set_collection_id_eval_collection", type_="foreignkey")
        batch_op.drop_column("visibility")
        batch_op.drop_column("variant")
        batch_op.drop_column("logical_key")
        batch_op.drop_column("collection_id")

    op.drop_index("ix_eval_collection_visibility", table_name="eval_collection")
    op.drop_index("ix_eval_collection_parent_position", table_name="eval_collection")
    op.drop_index("ix_eval_collection_parent_id", table_name="eval_collection")
    op.drop_index("ix_eval_collection_name", table_name="eval_collection")
    op.drop_index("ix_eval_collection_key", table_name="eval_collection")
    op.drop_table("eval_collection")
