"""Case CRUD, search, bulk operations, and import/export (PRD F1)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import or_
from sqlmodel import Session, col, select

from gaugix import caseio, formats
from gaugix.db import get_session
from gaugix.errors import NotFoundError, ValidationError
from gaugix.hierarchy import ensure_node_path, get_set_node, node_map, nodes_for_set, path_nodes
from gaugix.history import case_run_history
from gaugix.models.base import utcnow
from gaugix.models.cases import EvalCase, EvalSet, SetMembership
from gaugix.repo import (
    compact_positions,
    get_live_case,
    get_live_set,
    get_or_404,
    memberships_for_cases,
    next_position,
)
from gaugix.schemas.cases import (
    IMPORT_FORMATS,
    BulkDeleteOp,
    BulkMoveOp,
    BulkTagOp,
    CaseCreate,
    CaseIO,
    CaseRead,
    CaseUpdate,
    FieldMapping,
    ImportRequest,
    ImportResult,
    SetRef,
)
from gaugix.schemas.common import CountResponse
from gaugix.schemas.runs import CaseRunHistoryRead

router = APIRouter(prefix="/cases", tags=["cases"])

SessionDep = Annotated[Session, Depends(get_session)]


# -- serialisation -------------------------------------------------------------


def to_read(
    case: EvalCase,
    sets: list[tuple[int, str, int]] | None = None,
    position: int | None = None,
    node_id: int | None = None,
    node_path: list[str] | None = None,
) -> CaseRead:
    return CaseRead(
        id=case.id or 0,
        title=case.title,
        input=case.input,
        reference=case.reference,
        scoring=case.scoring,
        tags=case.tags,
        notes=case.notes,
        deleted_at=case.deleted_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
        sets=[SetRef(id=s[0], name=s[1], position=s[2]) for s in (sets or [])],
        position=position,
        node_id=node_id,
        node_path=node_path or [],
    )


def to_read_many(session: Session, cases: list[EvalCase]) -> list[CaseRead]:
    """Serialise a page of cases, resolving set membership in one extra query."""
    ids = [c.id for c in cases if c.id is not None]
    memberships = memberships_for_cases(session, ids)
    return [to_read(c, memberships.get(c.id or 0, [])) for c in cases]


# -- list / search -------------------------------------------------------------


@router.get("", response_model=list[CaseRead])
def list_cases(
    session: SessionDep,
    response: Response,
    q: str | None = Query(default=None, description="Free text over title, input and notes"),
    tags: list[str] | None = Query(default=None, description="Case must carry every tag given"),
    set_id: int | None = Query(default=None, description="Only cases in this set"),
    exclude_set_id: int | None = Query(default=None, description="Only cases *not* in this set"),
    unfiled: bool = Query(default=False, description="Only cases that belong to no set at all"),
    trashed: bool = Query(default=False, description="List the Trash instead of live cases"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CaseRead]:
    """Search and filter cases (PRD F1.6)."""
    statement = select(EvalCase)
    count_stmt = select(EvalCase)

    def apply(stmt: Any) -> Any:
        if trashed:
            stmt = stmt.where(col(EvalCase.deleted_at).is_not(None))
        else:
            stmt = stmt.where(col(EvalCase.deleted_at).is_(None))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    col(EvalCase.title).ilike(like),
                    col(EvalCase.input_json).ilike(like),
                    col(EvalCase.notes).ilike(like),
                    col(EvalCase.reference).ilike(like),
                )
            )
        for tag in tags or []:
            # tags_json is a JSON array of strings; the quoted form avoids
            # matching "go" inside "golang".
            stmt = stmt.where(col(EvalCase.tags_json).contains(f'"{tag}"'))
        if set_id is not None:
            stmt = stmt.where(
                col(EvalCase.id).in_(
                    select(SetMembership.case_id).where(SetMembership.set_id == set_id)
                )
            )
        if exclude_set_id is not None:
            stmt = stmt.where(
                col(EvalCase.id).not_in(
                    select(SetMembership.case_id).where(SetMembership.set_id == exclude_set_id)
                )
            )
        if unfiled:
            # Cases removed from a set but not deleted had nowhere to be seen:
            # every listing was scoped to a set, so they existed and were
            # unreachable. This is the filter that finds them (D-043).
            stmt = stmt.where(col(EvalCase.id).not_in(select(SetMembership.case_id)))
        return stmt

    total = len(session.exec(apply(count_stmt)).all())
    rows = session.exec(
        apply(statement).order_by(col(EvalCase.id).desc()).limit(limit).offset(offset)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    return to_read_many(session, list(rows))


@router.get("/export")
def export_cases(
    session: SessionDep,
    fmt: str = Query(
        default="jsonl", pattern="^(jsonl|yaml|json|csv|openai_evals)$", alias="format"
    ),
    set_id: int | None = Query(default=None),
    case_ids: list[int] | None = Query(default=None),
    download: bool = Query(default=True),
) -> Response:
    """Export cases in the canonical schema (PRD F1.3)."""
    if set_id is not None:
        get_live_set(session, set_id)
        grouped_rows = session.exec(
            select(EvalCase, SetMembership.node_id)
            .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
            .where(SetMembership.set_id == set_id, col(EvalCase.deleted_at).is_(None))
            .order_by(col(SetMembership.position))
        ).all()
        by_id = node_map(nodes_for_set(session, set_id))
        io_cases = [
            to_read(
                case,
                node_id=node_id,
                node_path=[part.name for part in path_nodes(by_id, node_id)],
            ).to_io()
            for case, node_id in grouped_rows
        ]
    else:
        statement = select(EvalCase).where(col(EvalCase.deleted_at).is_(None))
        if case_ids:
            statement = statement.where(col(EvalCase.id).in_(case_ids))
        case_rows = session.exec(statement.order_by(col(EvalCase.id))).all()
        io_cases = [to_read(case).to_io() for case in case_rows]

    payload = caseio.dump_cases(io_cases, fmt)

    headers = {}
    if download:
        name = f"gaugix-cases.{caseio.FILE_EXTENSIONS[fmt]}"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return Response(content=payload, media_type=caseio.MEDIA_TYPES[fmt], headers=headers)


# Literal-path routes are declared before the `/{case_id}` ones: FastAPI
# matches in declaration order, so `/cases/bulk/restore` would otherwise be
# swallowed by `/cases/{case_id}/restore`.
# -- bulk operations (PRD F1.2) ------------------------------------------------


@router.post("/bulk/tags", response_model=CountResponse)
def bulk_tags(payload: BulkTagOp, session: SessionDep) -> CountResponse:
    """Add and/or remove tags across a selection."""
    cases = _load_selection(session, payload.case_ids)
    add = {t.strip() for t in payload.add_tags if t.strip()}
    remove = {t.strip() for t in payload.remove_tags if t.strip()}
    if not add and not remove:
        raise ValidationError("provide add_tags and/or remove_tags")

    for case in cases:
        case.tags = sorted((set(case.tags) | add) - remove)
        case.touch()
        session.add(case)
    session.commit()
    return CountResponse(count=len(cases))


@router.post("/bulk/move", response_model=CountResponse)
def bulk_move(payload: BulkMoveOp, session: SessionDep) -> CountResponse:
    """Copy or move a selection into another set."""
    cases = _load_selection(session, payload.case_ids)
    get_live_set(session, payload.target_set_id)
    if payload.target_node_id is not None:
        get_set_node(session, payload.target_set_id, payload.target_node_id)
    if payload.mode == "move" and payload.source_set_id is None:
        raise ValidationError("source_set_id is required when mode='move'")

    existing = set(
        session.exec(
            select(SetMembership.case_id).where(SetMembership.set_id == payload.target_set_id)
        ).all()
    )
    position = next_position(session, payload.target_set_id)
    for case in cases:
        if case.id in existing:
            continue
        session.add(
            SetMembership(
                set_id=payload.target_set_id,
                case_id=case.id or 0,
                node_id=payload.target_node_id,
                position=position,
            )
        )
        position += 1

    if payload.mode == "move" and payload.source_set_id is not None:
        get_live_set(session, payload.source_set_id)
        rows = session.exec(
            select(SetMembership).where(
                SetMembership.set_id == payload.source_set_id,
                col(SetMembership.case_id).in_(payload.case_ids),
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.flush()
        compact_positions(session, payload.source_set_id)

    session.commit()
    return CountResponse(count=len(cases))


@router.post("/bulk/delete", response_model=CountResponse)
def bulk_delete(payload: BulkDeleteOp, session: SessionDep) -> CountResponse:
    """Soft-delete a selection to the Trash."""
    cases = _load_selection(session, payload.case_ids)
    now = utcnow()
    for case in cases:
        if case.deleted_at is None:
            case.deleted_at = now
            case.touch()
            session.add(case)
    session.commit()
    return CountResponse(count=len(cases))


@router.post("/bulk/restore", response_model=CountResponse)
def bulk_restore(payload: BulkDeleteOp, session: SessionDep) -> CountResponse:
    cases = _load_selection(session, payload.case_ids, allow_trashed=True)
    for case in cases:
        case.deleted_at = None
        case.touch()
        session.add(case)
    session.commit()
    return CountResponse(count=len(cases))


@router.post("/bulk/purge", response_model=CountResponse)
def bulk_purge(payload: BulkDeleteOp, session: SessionDep) -> CountResponse:
    """Permanently delete trashed cases and their set memberships."""
    cases = _load_selection(session, payload.case_ids, allow_trashed=True)
    ids = [c.id for c in cases if c.id is not None]
    if ids:
        rows = session.exec(select(SetMembership).where(col(SetMembership.case_id).in_(ids))).all()
        for row in rows:
            session.delete(row)
        session.flush()  # memberships must be gone before the cases they point at
    for case in cases:
        session.delete(case)
    session.commit()
    return CountResponse(count=len(cases), message="purged")


def _load_selection(
    session: Session, case_ids: list[int], allow_trashed: bool = False
) -> list[EvalCase]:
    """Load every requested case, or fail — bulk ops never silently skip ids."""
    rows = session.exec(select(EvalCase).where(col(EvalCase.id).in_(case_ids))).all()
    found = {c.id for c in rows}
    missing = [i for i in case_ids if i not in found]
    if missing:
        raise NotFoundError(f"unknown case ids: {missing}", details={"missing": missing})
    if not allow_trashed:
        trashed = [c.id for c in rows if c.deleted_at is not None]
        if trashed:
            raise ValidationError(
                f"cases are in the trash: {trashed}", details={"trashed": trashed}
            )
    return list(rows)


# -- import (PRD F1.3, atomic) -------------------------------------------------


@router.post("/import", response_model=ImportResult)
def import_cases(payload: ImportRequest, session: SessionDep) -> ImportResult:
    """Import cases from pasted text. All-or-nothing: any row error writes nothing."""
    return _do_import(
        session,
        content=payload.content,
        fmt=payload.format,
        set_id=payload.set_id,
        node_id=payload.node_id,
        dry_run=payload.dry_run,
        mapping=payload.mapping,
    )


@router.post("/import/file", response_model=ImportResult)
async def import_cases_file(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    format: str | None = Query(default=None, pattern=f"^({IMPORT_FORMATS})$"),
    set_id: int | None = Query(default=None),
    node_id: int | None = Query(default=None),
    dry_run: bool = Query(default=False),
) -> ImportResult:
    """Import from an uploaded file; the format is inferred from the extension."""
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"file must be UTF-8 text ({exc.reason})") from exc

    fmt = format or _infer_format(file.filename or "", content)
    return _do_import(
        session,
        content=content,
        fmt=fmt,
        set_id=set_id,
        node_id=node_id,
        dry_run=dry_run,
    )


def _infer_format(filename: str, content: str = "") -> str:
    """Guess from the extension, then from the content when the extension lies.

    `.jsonl` covers both the native shape and openai/evals, and `.yaml` covers
    both native YAML and a promptfoo config — so the extension alone is not
    enough. Sniffing a distinctive key is: `tests:` only appears in promptfoo,
    and `ideal` only in evals files.
    """
    lower = filename.lower()
    if lower.endswith(".csv") or lower.endswith(".tsv"):
        return formats.CSV
    if lower.endswith((".yaml", ".yml")):
        return formats.PROMPTFOO if re.search(r"^\s*tests\s*:", content, re.M) else caseio.YAML
    if lower.endswith(".json"):
        head = content.lstrip()[:400]
        return formats.HUGGINGFACE if '"rows"' in head else caseio.JSON
    if lower.endswith(".jsonl") or lower.endswith(".ndjson") or not lower:
        first = next((ln for ln in content.splitlines() if ln.strip()), "")
        if '"ideal"' in first and '"title"' not in first:
            return formats.OPENAI_EVALS
    return caseio.JSONL


def _do_import(
    session: Session,
    *,
    content: str,
    fmt: str,
    set_id: int | None,
    node_id: int | None,
    dry_run: bool,
    mapping: FieldMapping | None = None,
) -> ImportResult:
    if set_id is not None:
        get_live_set(session, set_id)
        if node_id is not None:
            get_set_node(session, set_id, node_id)
    elif node_id is not None:
        raise ValidationError("node_id requires set_id")

    cases, errors, warnings = caseio.parse_any(content, fmt, mapping)
    if errors:
        # Atomic: report everything wrong and write nothing.
        return ImportResult(ok=False, imported=0, errors=errors, warnings=warnings, dry_run=dry_run)
    if dry_run:
        return ImportResult(ok=True, imported=len(cases), warnings=warnings, dry_run=True)

    created = create_cases(session, cases, set_id=set_id, node_id=node_id)
    session.commit()
    return ImportResult(
        ok=True,
        imported=len(created),
        warnings=warnings,
        case_ids=[c.id for c in created if c.id is not None],
    )


def create_cases(
    session: Session,
    cases: list[CaseIO],
    *,
    set_id: int | None = None,
    node_id: int | None = None,
) -> list[EvalCase]:
    """Persist parsed cases and, optionally, append them to a set.

    Shared with the benchmark installer so a catalogue install lands identically
    to a paste — same ordering, same membership rules, one code path to trust.
    """
    created: list[EvalCase] = []
    for item in cases:
        case = EvalCase(title=item.title, reference=item.reference, notes=item.notes)
        case.input = item.input
        case.scoring = item.scoring
        case.tags = item.tags
        session.add(case)
        created.append(case)
    session.flush()

    if set_id is not None:
        position = next_position(session, set_id)
        for case, item in zip(created, cases, strict=True):
            session.add(
                SetMembership(
                    set_id=set_id,
                    case_id=case.id or 0,
                    node_id=ensure_node_path(
                        session,
                        set_id,
                        item.group_path,
                        parent_id=node_id,
                    ),
                    position=position,
                )
            )
            position += 1
    return created


# -- create / read / update / delete -------------------------------------------


@router.post("", response_model=CaseRead, status_code=201)
def create_case(payload: CaseCreate, session: SessionDep) -> CaseRead:
    case = EvalCase(title=payload.title, reference=payload.reference, notes=payload.notes)
    case.input = payload.input
    case.scoring = payload.scoring
    case.tags = payload.tags
    session.add(case)
    session.flush()

    if payload.set_id is not None:
        get_live_set(session, payload.set_id)
        if payload.node_id is not None:
            get_set_node(session, payload.set_id, payload.node_id)
        session.add(
            SetMembership(
                set_id=payload.set_id,
                case_id=case.id or 0,
                node_id=payload.node_id,
                position=next_position(session, payload.set_id),
            )
        )
    elif payload.node_id is not None:
        raise ValidationError("node_id requires set_id")
    session.commit()
    session.refresh(case)
    return to_read_many(session, [case])[0]


@router.get("/{case_id}", response_model=CaseRead)
def get_case(case_id: int, session: SessionDep) -> CaseRead:
    case = get_or_404(session, EvalCase, case_id, "Case")
    return to_read_many(session, [case])[0]


@router.get("/{case_id}/run-items", response_model=list[CaseRunHistoryRead])
def get_case_run_history(
    case_id: int,
    session: SessionDep,
    response: Response,
    limit: int = Query(default=10, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[CaseRunHistoryRead]:
    """Historical executions of this case, one row per set and executor."""
    get_or_404(session, EvalCase, case_id, "Case")
    rows, total = case_run_history(session, case_id, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [CaseRunHistoryRead.model_validate(row) for row in rows]


@router.patch("/{case_id}", response_model=CaseRead)
def update_case(case_id: int, payload: CaseUpdate, session: SessionDep) -> CaseRead:
    case = get_live_case(session, case_id)
    data = payload.model_dump(exclude_unset=True)

    if "title" in data:
        case.title = data["title"]
    if "reference" in data:
        case.reference = data["reference"]
    if "notes" in data:
        case.notes = data["notes"]
    if payload.input is not None:
        case.input = payload.input
    if payload.scoring is not None:
        case.scoring = payload.scoring
    if payload.tags is not None:
        case.tags = payload.tags

    case.touch()
    session.add(case)
    session.commit()
    session.refresh(case)
    return to_read_many(session, [case])[0]


@router.post("/{case_id}/duplicate", response_model=CaseRead, status_code=201)
def duplicate_case(
    case_id: int,
    session: SessionDep,
    set_id: int | None = None,
    node_id: int | None = None,
) -> CaseRead:
    """Copy a case (PRD F1.7). Optionally drop the copy straight into a set."""
    source = get_live_case(session, case_id)
    copy = EvalCase(
        title=f"{source.title} (copy)",
        reference=source.reference,
        notes=source.notes,
        input_json=source.input_json,
        scoring_json=source.scoring_json,
        tags_json=source.tags_json,
    )
    session.add(copy)
    session.flush()
    if set_id is not None:
        get_live_set(session, set_id)
        if node_id is not None:
            get_set_node(session, set_id, node_id)
        session.add(
            SetMembership(
                set_id=set_id,
                case_id=copy.id or 0,
                node_id=node_id,
                position=next_position(session, set_id),
            )
        )
    elif node_id is not None:
        raise ValidationError("node_id requires set_id")
    session.commit()
    session.refresh(copy)
    return to_read_many(session, [copy])[0]


@router.delete("/{case_id}", response_model=CountResponse)
def delete_case(case_id: int, session: SessionDep, purge: bool = False) -> CountResponse:
    """Soft-delete to the Trash, or purge permanently with `?purge=true`."""
    case = get_or_404(session, EvalCase, case_id, "Case")
    if purge:
        for row in session.exec(
            select(SetMembership).where(SetMembership.case_id == case_id)
        ).all():
            session.delete(row)
        # Flush first: without a declared ORM relationship SQLAlchemy does not
        # know memberships must go before the case, and SQLite enforces the FK.
        session.flush()
        session.delete(case)
        session.commit()
        return CountResponse(count=1, message="purged")

    if case.deleted_at is None:
        case.deleted_at = utcnow()
        case.touch()
        session.add(case)
        session.commit()
    return CountResponse(count=1, message="moved to trash")


@router.post("/{case_id}/restore", response_model=CaseRead)
def restore_case(case_id: int, session: SessionDep) -> CaseRead:
    case = get_or_404(session, EvalCase, case_id, "Case")
    if case.deleted_at is not None:
        case.deleted_at = None
        case.touch()
        session.add(case)
        session.commit()
        session.refresh(case)
    return to_read_many(session, [case])[0]


__all__ = ["CaseIO", "EvalSet", "router", "to_read", "to_read_many"]
