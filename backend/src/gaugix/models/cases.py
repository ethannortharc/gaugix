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

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Index, SQLModel

from gaugix.domain import CaseSnapshot, EvaluationProfile, Message, ScorerSpec
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


class EvalCollection(TimestampMixin, table=True):
    """A reusable hierarchy above eval sets.

    The API calls these collections; the UI presents root collections as
    evaluation suites and nested collections as folders.  Nothing in this
    model is Guardrail-specific, so the same hierarchy works for quality,
    retrieval, agent, safety, latency, and other evaluation programmes.
    """

    __tablename__ = "eval_collection"
    __table_args__ = (
        UniqueConstraint("key", name="uq_eval_collection_key"),
        Index("ix_eval_collection_parent_position", "parent_id", "position"),
    )

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None)
    parent_id: int | None = Field(default=None, foreign_key="eval_collection.id", index=True)
    position: int = Field(default=0)
    visibility: str = Field(default="primary", index=True)
    tags_json: str = Field(default="[]")
    provenance_json: str = Field(default="{}")

    @property
    def tags(self) -> list[str]:
        return load_str_list(self.tags_json)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = dump_json(sorted({t.strip() for t in value if t.strip()}))

    @property
    def provenance(self) -> dict[str, Any]:
        loaded = json.loads(self.provenance_json or "{}")
        return loaded if isinstance(loaded, dict) else {}

    @provenance.setter
    def provenance(self, value: dict[str, Any]) -> None:
        self.provenance_json = dump_json(value)


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
    #: Optional task semantics used by the generic metrics engine.  The empty
    #: object is the backwards-compatible standard pass/fail profile.
    evaluation_profile_json: str = Field(default="{}")
    #: Optional placement in the library's generic collection hierarchy.
    collection_id: int | None = Field(default=None, foreign_key="eval_collection.id", index=True)
    #: Stable identity shared by set variants such as input/output/both.
    logical_key: str | None = Field(default=None, index=True)
    #: Optional variant label beneath ``logical_key``; not interpreted by Gaugix.
    variant: str | None = Field(default=None)
    #: ``primary`` is shown by default; ``fixture`` and ``hidden`` remain accessible.
    visibility: str = Field(default="primary", index=True)
    deleted_at: datetime | None = Field(default=None)

    @property
    def provenance(self) -> dict[str, Any]:
        loaded = json.loads(self.provenance_json or "{}")
        return loaded if isinstance(loaded, dict) else {}

    @provenance.setter
    def provenance(self, value: dict[str, Any]) -> None:
        self.provenance_json = dump_json(value)

    @property
    def evaluation_profile(self) -> EvaluationProfile:
        loaded = json.loads(self.evaluation_profile_json or "{}")
        try:
            return EvaluationProfile.model_validate(loaded if isinstance(loaded, dict) else {})
        except Exception:
            # A malformed profile must not make a set unreadable. Preflight and
            # the editor can surface/fix it; historical pass/fail still works.
            return EvaluationProfile.standard()

    @evaluation_profile.setter
    def evaluation_profile(self, value: EvaluationProfile) -> None:
        self.evaluation_profile_json = dump_json(value.model_dump(mode="json"))

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


class EvalSetNode(TimestampMixin, table=True):
    """One organisational branch inside an eval set.

    Nodes carry navigation and provenance, while the set remains the unit of
    comparison and evaluation semantics.  That distinction lets a large set be
    browsed as a tree without turning every folder into an unrelated dataset.
    """

    __tablename__ = "eval_set_node"
    __table_args__ = (Index("ix_eval_set_node_parent_position", "set_id", "parent_id", "position"),)

    id: int | None = Field(default=None, primary_key=True)
    set_id: int = Field(foreign_key="eval_set.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="eval_set_node.id", index=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None)
    position: int = Field(default=0)
    tags_json: str = Field(default="[]")
    provenance_json: str = Field(default="{}")

    @property
    def tags(self) -> list[str]:
        return load_str_list(self.tags_json)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = dump_json(sorted({t.strip() for t in value if t.strip()}))

    @property
    def provenance(self) -> dict[str, Any]:
        loaded = json.loads(self.provenance_json or "{}")
        return loaded if isinstance(loaded, dict) else {}

    @provenance.setter
    def provenance(self, value: dict[str, Any]) -> None:
        self.provenance_json = dump_json(value)


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
    node_id: int | None = Field(default=None, foreign_key="eval_set_node.id", index=True)
    position: int = Field(default=0)


class AppSetting(TimestampMixin, table=True):
    """Key/value application settings: pricing table, defaults, rubric library."""

    __tablename__ = "app_setting"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value_json: str = Field(default="null")
