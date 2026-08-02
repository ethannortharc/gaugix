"""EvalCase, EvalSet and their many-to-many membership (PRD §5, ARCHITECTURE §3).

Cases are independent entities reusable across sets; membership carries the
ordering, so the same case can sit at different positions in different sets.
Deletion is soft — `deleted_at` moves a row to the Trash, from where it can be
restored or purged (PRD F1.2).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlmodel import Field, Index, SQLModel

from gaugix.domain import CaseSnapshot, Message, ScorerSpec
from gaugix.models.base import (
    TimestampMixin,
    dump_json,
    load_models,
    load_str_list,
)


class EvalCase(TimestampMixin, table=True):
    """One test: input messages, an optional reference, and how to score it."""

    __tablename__ = "eval_case"
    __table_args__ = (Index("ix_eval_case_deleted_at", "deleted_at"),)

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    input_json: str = Field(default="[]")
    reference: str | None = Field(default=None)
    scoring_json: str = Field(default="[]")
    tags_json: str = Field(default="[]")
    notes: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)

    # -- typed accessors ---------------------------------------------------

    @property
    def input(self) -> list[Message]:
        return load_models(self.input_json, Message)

    @input.setter
    def input(self, value: list[Message]) -> None:
        self.input_json = dump_json([m.model_dump(mode="json") for m in value])

    @property
    def scoring(self) -> list[ScorerSpec]:
        return load_models(self.scoring_json, ScorerSpec)

    @scoring.setter
    def scoring(self, value: list[ScorerSpec]) -> None:
        self.scoring_json = dump_json([s.model_dump(mode="json") for s in value])

    @property
    def tags(self) -> list[str]:
        return load_str_list(self.tags_json)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = dump_json(sorted({t.strip() for t in value if t.strip()}))

    def to_snapshot(self, scoring: list[ScorerSpec] | None = None) -> CaseSnapshot:
        """Freeze this case for a run.

        `scoring` lets the planner pass the *resolved* config (the set default when
        the case has none), which is what actually gets recorded — see PRD F4.2.
        """
        return CaseSnapshot(
            case_id=self.id,
            title=self.title,
            input=self.input,
            reference=self.reference,
            scoring=scoring if scoring is not None else self.scoring,
            tags=self.tags,
            notes=self.notes,
        )


class EvalSet(TimestampMixin, table=True):
    """A named, ordered collection of cases, with an optional default scoring config."""

    __tablename__ = "eval_set"
    __table_args__ = (Index("ix_eval_set_deleted_at", "deleted_at"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = Field(default=None)
    tags_json: str = Field(default="[]")
    default_scoring_json: str = Field(default="[]")
    #: Where this set's cases came from, when it was installed from a benchmark:
    #: revision, checksum, licence, scorer version. Empty for hand-made sets.
    provenance_json: str = Field(default="{}")
    deleted_at: datetime | None = Field(default=None)

    @property
    def provenance(self) -> dict[str, Any]:
        loaded = json.loads(self.provenance_json or "{}")
        return loaded if isinstance(loaded, dict) else {}

    @provenance.setter
    def provenance(self, value: dict[str, Any]) -> None:
        self.provenance_json = dump_json(value)

    @property
    def tags(self) -> list[str]:
        return load_str_list(self.tags_json)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = dump_json(sorted({t.strip() for t in value if t.strip()}))

    @property
    def default_scoring(self) -> list[ScorerSpec]:
        return load_models(self.default_scoring_json, ScorerSpec)

    @default_scoring.setter
    def default_scoring(self, value: list[ScorerSpec]) -> None:
        self.default_scoring_json = dump_json([s.model_dump(mode="json") for s in value])


class SetMembership(SQLModel, table=True):
    """Case ↔ set membership with an explicit position (manual ordering, PRD F1.1)."""

    __tablename__ = "set_membership"
    __table_args__ = (
        Index("ix_set_membership_set_position", "set_id", "position"),
        Index("ix_set_membership_case", "case_id"),
        Index("uq_set_membership", "set_id", "case_id", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    set_id: int = Field(foreign_key="eval_set.id", index=True)
    case_id: int = Field(foreign_key="eval_case.id", index=True)
    position: int = Field(default=0)


class AppSetting(TimestampMixin, table=True):
    """Key/value application settings: pricing table, defaults, rubric library."""

    __tablename__ = "app_setting"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value_json: str = Field(default="null")
