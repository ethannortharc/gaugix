"""DTOs for cases and sets.

`CaseIO` is the canonical import/export shape from PRD Appendix B — it is
deliberately separate from `CaseRead` (which carries ids and timestamps) so that
an export round-trips byte-for-byte through import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gaugix.domain import EvaluationProfile, Message, ScorerSpec


def _clean_tags(tags: list[str]) -> list[str]:
    """Trim, drop blanks, de-duplicate, sort — tags are a set with a stable order."""
    return sorted({t.strip() for t in tags if t and t.strip()})


class CaseIO(BaseModel):
    """Canonical JSONL/YAML case schema (PRD Appendix B). No ids, no timestamps."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    input: list[Message]
    reference: str | None = None
    scoring: list[ScorerSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    group_path: list[str] = Field(
        default_factory=list,
        description="Optional EvalSet branch path used during set-scoped import/export",
    )

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)

    @field_validator("group_path")
    @classmethod
    def _group_path(cls, v: list[str]) -> list[str]:
        cleaned = [part.strip() for part in v]
        if any(not part for part in cleaned):
            raise ValueError("group_path parts must not be blank")
        return cleaned


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    input: list[Message] = Field(default_factory=list)
    reference: str | None = None
    scoring: list[ScorerSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    set_id: int | None = Field(default=None, description="Optionally attach to this set")
    node_id: int | None = Field(default=None, description="Optional branch within set_id")

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class CaseUpdate(BaseModel):
    """PATCH body — every field optional; omitted fields are left untouched."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1)
    input: list[Message] | None = None
    reference: str | None = None
    scoring: list[ScorerSpec] | None = None
    tags: list[str] | None = None
    notes: str | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return _clean_tags(v) if v is not None else None


class SetRef(BaseModel):
    """Which set a case belongs to, and where in it."""

    id: int
    name: str
    position: int
    node_id: int | None = None


class CaseRead(BaseModel):
    id: int
    title: str
    input: list[Message]
    reference: str | None
    scoring: list[ScorerSpec]
    tags: list[str]
    notes: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sets: list[SetRef] = Field(default_factory=list)
    position: int | None = Field(
        default=None, description="Position within the set being listed, when applicable"
    )
    node_id: int | None = Field(default=None, description="Leaf branch in the listed set")
    node_path: list[str] = Field(default_factory=list)

    def to_io(self) -> CaseIO:
        return CaseIO(
            title=self.title,
            input=self.input,
            reference=self.reference,
            scoring=self.scoring,
            tags=self.tags,
            notes=self.notes,
            group_path=self.node_path,
        )


class SetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    default_scoring: list[ScorerSpec] = Field(default_factory=list)
    evaluation_profile: EvaluationProfile = Field(default_factory=EvaluationProfile.standard)
    collection_id: int | None = None
    logical_key: str | None = Field(default=None, min_length=1)
    variant: str | None = Field(default=None, min_length=1)
    visibility: Literal["primary", "fixture", "hidden"] = "primary"

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class SetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    tags: list[str] | None = None
    default_scoring: list[ScorerSpec] | None = None
    evaluation_profile: EvaluationProfile | None = None
    collection_id: int | None = None
    logical_key: str | None = Field(default=None, min_length=1)
    variant: str | None = Field(default=None, min_length=1)
    visibility: Literal["primary", "fixture", "hidden"] | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return _clean_tags(v) if v is not None else None


class SetRead(BaseModel):
    id: int
    name: str
    description: str | None
    tags: list[str]
    default_scoring: list[ScorerSpec]
    evaluation_profile: EvaluationProfile
    collection_id: int | None = None
    collection_key: str | None = None
    collection_path: list[str] = Field(default_factory=list)
    logical_key: str | None = None
    variant: str | None = None
    visibility: Literal["primary", "fixture", "hidden"] = "primary"
    case_count: int = 0
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    #: Where this set's cases came from, for a benchmark install: revision,
    #: checksum, licence, scorer version — plus `modified`, computed live, when
    #: the set no longer holds what was installed. Empty for hand-made sets.
    provenance: dict[str, Any] = Field(default_factory=dict)


# -- set hierarchy ------------------------------------------------------------


class SetNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    parent_id: int | None = None
    description: str | None = None
    position: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class SetNodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    parent_id: int | None = None
    description: str | None = None
    position: int | None = Field(default=None, ge=0)
    tags: list[str] | None = None
    provenance: dict[str, Any] | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return _clean_tags(v) if v is not None else None


class SetNodeRead(BaseModel):
    id: int
    set_id: int
    parent_id: int | None
    name: str
    description: str | None
    position: int
    tags: list[str]
    provenance: dict[str, Any]
    effective_provenance: dict[str, Any]
    path: list[str]
    depth: int
    direct_case_count: int
    descendant_case_count: int
    created_at: datetime
    updated_at: datetime


class AssignCasesNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)
    node_id: int | None = None


# -- membership ---------------------------------------------------------------


class AttachCases(BaseModel):
    """Attach cases to a set; they land at the end in the order given."""

    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)
    node_id: int | None = None


class DetachCases(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)


class ReorderCases(BaseModel):
    """Full or partial reorder; listed cases take positions 0..n-1 in this order."""

    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)


# -- bulk operations (PRD F1.2) -----------------------------------------------


class BulkTagOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)


class BulkMoveOp(BaseModel):
    """Copy or move cases into another set."""

    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)
    target_set_id: int
    target_node_id: int | None = None
    source_set_id: int | None = Field(
        default=None, description="Required when mode='move' — the set to detach from"
    )
    mode: str = Field(default="copy", pattern="^(copy|move)$")


class BulkDeleteOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[int] = Field(min_length=1)


# -- import / export ----------------------------------------------------------


#: Native shapes plus every foreign format `gaugix.formats` can read.
IMPORT_FORMATS = "jsonl|yaml|json|csv|openai_evals|huggingface|promptfoo"


class FieldMapping(BaseModel):
    """Which source column becomes which part of a case.

    Only needed for tabular formats (CSV, HuggingFace rows), where the file has
    no idea what a "prompt" is. Any field left unset is guessed from the first
    row; an explicit value is never overridden by the guess.
    """

    model_config = ConfigDict(extra="forbid")

    input: str | None = Field(default=None, description="Column holding the prompt")
    reference: str | None = Field(default=None, description="Column holding the expected answer")
    title: str | None = None
    system: str | None = Field(default=None, description="Optional system-prompt column")
    tags: str | None = None
    notes: str | None = None
    title_prefix: str = Field(default="Row", description="Used when there is no title column")


class ImportRequest(BaseModel):
    """Paste-based import. File upload uses the multipart variant of the endpoint."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    format: str = Field(default="jsonl", pattern=f"^({IMPORT_FORMATS})$")
    set_id: int | None = None
    node_id: int | None = Field(
        default=None,
        description="Optional destination branch; imported group_path values are nested below it",
    )
    dry_run: bool = False
    mapping: FieldMapping | None = None


class ImportRowError(BaseModel):
    """One rejected row, addressed by 1-based line number (PRD F1.3)."""

    line: int
    message: str
    raw: str | None = None


class ImportResult(BaseModel):
    """Import is atomic: when `errors` is non-empty nothing was written."""

    ok: bool
    imported: int
    errors: list[ImportRowError] = Field(default_factory=list)
    #: Things that were imported but lost meaning on the way — a promptfoo
    #: assertion with no Gaugix equivalent, say. Non-blocking by design: a case
    #: that silently loses a check is worse than one that says it did.
    warnings: list[ImportRowError] = Field(default_factory=list)
    case_ids: list[int] = Field(default_factory=list)
    dry_run: bool = False


# -- AI-assisted generation (PRD F1.4 / F1.5) ---------------------------------


class GenPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, description="What the new cases should cover")
    count: int = Field(default=10, ge=1, le=100)
    set_id: int | None = Field(default=None, description="Sample existing cases from this set")
    example_count: int = Field(default=3, ge=0, le=10)
    instructions: str | None = None


class GenPromptResponse(BaseModel):
    prompt: str
    example_case_ids: list[int] = Field(default_factory=list)


class GenDirectRequest(BaseModel):
    """F1.5 — generate candidates with a configured executor instead of copy/paste."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1)
    count: int = Field(default=10, ge=1, le=100)
    set_id: int | None = None
    example_count: int = Field(default=3, ge=0, le=10)
    instructions: str | None = None
    executor_id: int


class GenDirectResponse(BaseModel):
    """Candidates are previewed before commit — nothing is written by this call."""

    cases: list[CaseIO]
    errors: list[ImportRowError] = Field(default_factory=list)
    raw_output: str
    usage: dict[str, Any] = Field(default_factory=dict)
