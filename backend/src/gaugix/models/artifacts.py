"""The Artifact table (PRD F6.1, ARCHITECTURE §3).

An artifact is a **file an attempt produced**: the raw output itself, a code
block extracted from it, or a file a CLI agent left in its working directory.

Bytes live on disk under `data/artifacts/{run_id}/{item_id}/{attempt_n}/`; the
row holds metadata and the relative path. Two reasons for that split: a 20MB
workdir file has no business in SQLite, and a file on disk can be opened by the
tools that understand it.

The path is stored *relative* to the artifacts root so the whole directory can
be moved or restored from a backup without rewriting the database.
"""

from __future__ import annotations

from sqlmodel import Field, Index

from gaugix.models.base import TimestampMixin


class Artifact(TimestampMixin, table=True):
    """One file produced by one attempt."""

    __tablename__ = "artifact"
    __table_args__ = (Index("ix_artifact_attempt_kind", "attempt_id", "kind"),)

    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(foreign_key="attempt.id", index=True)
    #: raw_output | code_block | workdir_file | capture
    kind: str = Field(default="raw_output", index=True)
    filename: str = Field(default="")
    mime: str = Field(default="text/plain")
    size_bytes: int = Field(default=0)
    #: Content hash — lets a viewer tell "the same file twice" from "two files".
    sha256: str = Field(default="", index=True)
    #: Relative to the artifacts root, never absolute (see module docstring).
    rel_path: str = Field(default="")
    #: For code_block artifacts: the fence language as written, e.g. `python`.
    language: str | None = Field(default=None)
    #: Where in the output a code block came from, so ordering is stable.
    block_index: int | None = Field(default=None)
