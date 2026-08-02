"""The Score table (PRD §5, ARCHITECTURE §3).

Scores are append-only and versioned: re-scoring after a config fix writes a new
row rather than overwriting, so "what did this look like before I fixed the regex?"
stays answerable. Views use the latest version per (item, scorer_index).
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Field, Index

from gaugix.domain import ScoreSource
from gaugix.models.base import TimestampMixin, dump_json, load_json


class Score(TimestampMixin, table=True):
    """One scorer's result for one run item, bound to the attempt it judged."""

    __tablename__ = "score"
    __table_args__ = (Index("ix_score_item_scorer", "run_item_id", "scorer_index", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    run_item_id: int = Field(foreign_key="run_item.id", index=True)
    attempt_id: int | None = Field(default=None, foreign_key="attempt.id", index=True)
    scorer_index: int = Field(default=0)
    scorer_type: str = Field(default="")
    scorer_config_hash: str = Field(default="")
    passed: bool | None = Field(default=None)
    value: float | None = Field(default=None)
    rationale: str = Field(default="")
    source: str = Field(default=str(ScoreSource.auto), index=True)
    judge_meta_json: str | None = Field(default=None)
    version: int = Field(default=1)
    created_by: str = Field(default="system")

    @property
    def judge_meta(self) -> dict[str, Any] | None:
        raw = load_json(self.judge_meta_json, None)
        return raw if isinstance(raw, dict) else None

    @judge_meta.setter
    def judge_meta(self, value: dict[str, Any] | None) -> None:
        self.judge_meta_json = None if value is None else dump_json(value)
