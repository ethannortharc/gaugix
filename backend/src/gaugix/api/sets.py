"""EvalSet CRUD and membership management (PRD F1.1)."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_
from sqlmodel import Session, col, select

from gaugix import benchmarks
from gaugix.api.cases import to_read
from gaugix.collection_hierarchy import (
    collection_descendant_ids,
    collection_map,
    collection_path,
    collections,
)
from gaugix.db import get_session
from gaugix.errors import ConflictError, NotFoundError, ValidationError
from gaugix.hierarchy import descendant_ids, get_set_node, node_map, nodes_for_set, path_nodes
from gaugix.history import set_run_history
from gaugix.models.base import utcnow
from gaugix.models.cases import EvalCase, EvalCollection, EvalSet, SetMembership
from gaugix.repo import (
    case_count,
    compact_positions,
    get_live_set,
    get_or_404,
    next_position,
)
from gaugix.schemas.cases import (
    AttachCases,
    CaseRead,
    DetachCases,
    ReorderCases,
    SetCreate,
    SetRead,
    SetUpdate,
)
from gaugix.schemas.common import CountResponse
from gaugix.schemas.runs import SetRunHistoryRead

router = APIRouter(prefix="/sets", tags=["sets"])

SessionDep = Annotated[Session, Depends(get_session)]


def to_set_read(
    session: Session,
    eval_set: EvalSet,
    collection_by_id: dict[int, EvalCollection] | None = None,
) -> SetRead:
    by_collection = collection_by_id or collection_map(collections(session))
    collection = by_collection.get(eval_set.collection_id or 0)
    path = collection_path(by_collection, eval_set.collection_id)
    return SetRead(
        id=eval_set.id or 0,
        name=eval_set.name,
        description=eval_set.description,
        tags=eval_set.tags,
        default_scoring=eval_set.default_scoring,
        evaluation_profile=eval_set.evaluation_profile,
        collection_id=eval_set.collection_id,
        collection_key=collection.key if collection else None,
        collection_path=[part.name for part in path],
        logical_key=eval_set.logical_key,
        variant=eval_set.variant,
        visibility=cast(Literal["primary", "fixture", "hidden"], eval_set.visibility),
        case_count=case_count(session, eval_set.id or 0),
        deleted_at=eval_set.deleted_at,
        created_at=eval_set.created_at,
        updated_at=eval_set.updated_at,
        # Stored provenance, a legacy stand-in when there is none, and a live
        # drift check — the same record the planner freezes into a run, so the
        # set page and the run's report cannot disagree (D-066).
        provenance=benchmarks.effective_provenance(session, eval_set),
    )


@router.get("", response_model=list[SetRead])
def list_sets(
    session: SessionDep,
    response: Response,
    q: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    collection_id: int | None = Query(default=None),
    include_descendants: bool = Query(default=True),
    visibility: list[str] | None = Query(default=None),
    unfiled: bool = Query(default=False),
    trashed: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[SetRead]:
    statement = select(EvalSet)
    if trashed:
        statement = statement.where(col(EvalSet.deleted_at).is_not(None))
    else:
        statement = statement.where(col(EvalSet.deleted_at).is_(None))
    if q:
        like = f"%{q}%"
        statement = statement.where(
            or_(col(EvalSet.name).ilike(like), col(EvalSet.description).ilike(like))
        )
    for tag in tags or []:
        statement = statement.where(col(EvalSet.tags_json).contains(f'"{tag}"'))
    if collection_id is not None and unfiled:
        raise ValidationError("choose a collection or unfiled sets, not both")
    if collection_id is not None:
        get_or_404(session, EvalCollection, collection_id, "Collection")
        selected = (
            collection_descendant_ids(collections(session), collection_id)
            if include_descendants
            else {collection_id}
        )
        statement = statement.where(col(EvalSet.collection_id).in_(selected))
    elif unfiled:
        statement = statement.where(col(EvalSet.collection_id).is_(None))
    if visibility:
        statement = statement.where(col(EvalSet.visibility).in_(visibility))

    total = len(session.exec(statement).all())
    rows = session.exec(statement.order_by(col(EvalSet.name)).limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)
    by_collection = collection_map(collections(session))
    return [to_set_read(session, s, by_collection) for s in rows]


@router.post("", response_model=SetRead, status_code=201)
def create_set(payload: SetCreate, session: SessionDep) -> SetRead:
    if session.exec(select(EvalSet).where(EvalSet.name == payload.name)).first():
        raise ConflictError(f"a set named {payload.name!r} already exists")

    if payload.collection_id is not None:
        get_or_404(session, EvalCollection, payload.collection_id, "Collection")
    eval_set = EvalSet(
        name=payload.name,
        description=payload.description,
        collection_id=payload.collection_id,
        logical_key=payload.logical_key,
        variant=payload.variant,
        visibility=payload.visibility,
    )
    eval_set.tags = payload.tags
    eval_set.default_scoring = payload.default_scoring
    eval_set.evaluation_profile = payload.evaluation_profile
    session.add(eval_set)
    session.commit()
    session.refresh(eval_set)
    return to_set_read(session, eval_set)


@router.get("/{set_id}", response_model=SetRead)
def get_set(set_id: int, session: SessionDep) -> SetRead:
    return to_set_read(session, get_or_404(session, EvalSet, set_id, "Set"))


@router.get("/{set_id}/runs", response_model=list[SetRunHistoryRead])
def get_set_run_history(
    set_id: int,
    session: SessionDep,
    response: Response,
    limit: int = Query(default=10, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[SetRunHistoryRead]:
    """Runs that measured this set, with set-scoped rather than run-wide metrics."""
    get_or_404(session, EvalSet, set_id, "Set")
    rows, total = set_run_history(session, set_id, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [SetRunHistoryRead.model_validate(row) for row in rows]


@router.patch("/{set_id}", response_model=SetRead)
def update_set(set_id: int, payload: SetUpdate, session: SessionDep) -> SetRead:
    eval_set = get_live_set(session, set_id)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] != eval_set.name:
        clash = session.exec(select(EvalSet).where(EvalSet.name == data["name"])).first()
        if clash:
            raise ConflictError(f"a set named {data['name']!r} already exists")
        eval_set.name = data["name"]
    if "description" in data:
        eval_set.description = data["description"]
    if payload.tags is not None:
        eval_set.tags = payload.tags
    if payload.default_scoring is not None:
        eval_set.default_scoring = payload.default_scoring
    if payload.evaluation_profile is not None:
        eval_set.evaluation_profile = payload.evaluation_profile
    if "collection_id" in data:
        if data["collection_id"] is not None:
            get_or_404(session, EvalCollection, data["collection_id"], "Collection")
        eval_set.collection_id = data["collection_id"]
    if "logical_key" in data:
        eval_set.logical_key = data["logical_key"]
    if "variant" in data:
        eval_set.variant = data["variant"]
    if "visibility" in data:
        eval_set.visibility = data["visibility"]

    eval_set.touch()
    session.add(eval_set)
    session.commit()
    session.refresh(eval_set)
    return to_set_read(session, eval_set)


@router.delete("/{set_id}", response_model=CountResponse)
def delete_set(set_id: int, session: SessionDep, purge: bool = False) -> CountResponse:
    """Soft-delete a set. Cases are never deleted with it — they are shared entities."""
    eval_set = get_or_404(session, EvalSet, set_id, "Set")
    if purge:
        rows = session.exec(select(SetMembership).where(SetMembership.set_id == set_id)).all()
        for row in rows:
            session.delete(row)
        session.flush()  # memberships must be gone before the set they point at
        nodes = nodes_for_set(session, set_id)
        by_id = node_map(nodes)
        for node in sorted(nodes, key=lambda item: len(path_nodes(by_id, item.id)), reverse=True):
            session.delete(node)
            # Flush each depth: without an ORM relationship SQLAlchemy may
            # batch self-referential deletes in primary-key order.
            session.flush()
        session.delete(eval_set)
        session.commit()
        return CountResponse(count=1, message="purged")

    if eval_set.deleted_at is None:
        eval_set.deleted_at = utcnow()
        eval_set.touch()
        session.add(eval_set)
        session.commit()
    return CountResponse(count=1, message="moved to trash")


@router.post("/{set_id}/restore", response_model=SetRead)
def restore_set(set_id: int, session: SessionDep) -> SetRead:
    eval_set = get_or_404(session, EvalSet, set_id, "Set")
    if eval_set.deleted_at is not None:
        eval_set.deleted_at = None
        eval_set.touch()
        session.add(eval_set)
        session.commit()
        session.refresh(eval_set)
    return to_set_read(session, eval_set)


# -- membership ----------------------------------------------------------------


@router.get("/{set_id}/cases", response_model=list[CaseRead])
def list_set_cases(
    set_id: int,
    session: SessionDep,
    response: Response,
    q: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    node_id: int | None = Query(default=None, description="Only this branch"),
    include_descendants: bool = Query(default=True),
    ungrouped: bool = Query(default=False, description="Only cases outside every branch"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[CaseRead]:
    """Cases in this set, in membership order."""
    get_or_404(session, EvalSet, set_id, "Set")

    statement = (
        select(EvalCase, SetMembership.position, SetMembership.node_id)
        .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
        .where(SetMembership.set_id == set_id, col(EvalCase.deleted_at).is_(None))
    )
    nodes = nodes_for_set(session, set_id)
    by_id = node_map(nodes)
    if node_id is not None and ungrouped:
        raise ValidationError("choose a branch or ungrouped cases, not both")
    if node_id is not None:
        get_set_node(session, set_id, node_id)
        selected_nodes = descendant_ids(nodes, node_id) if include_descendants else {node_id}
        statement = statement.where(col(SetMembership.node_id).in_(selected_nodes))
    elif ungrouped:
        statement = statement.where(col(SetMembership.node_id).is_(None))
    if q:
        like = f"%{q}%"
        statement = statement.where(
            or_(
                col(EvalCase.title).ilike(like),
                col(EvalCase.input_json).ilike(like),
                col(EvalCase.notes).ilike(like),
            )
        )
    for tag in tags or []:
        statement = statement.where(col(EvalCase.tags_json).contains(f'"{tag}"'))

    total = len(session.exec(statement).all())
    rows = session.exec(
        statement.order_by(col(SetMembership.position)).limit(limit).offset(offset)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    return [
        to_read(
            case,
            position=position,
            node_id=current_node_id,
            node_path=[part.name for part in path_nodes(by_id, current_node_id)],
        )
        for case, position, current_node_id in rows
    ]


@router.post("/{set_id}/cases", response_model=CountResponse)
def attach_cases(set_id: int, payload: AttachCases, session: SessionDep) -> CountResponse:
    """Attach cases to the end of the set, skipping ones already present."""
    get_live_set(session, set_id)
    _assert_cases_exist(session, payload.case_ids)
    if payload.node_id is not None:
        get_set_node(session, set_id, payload.node_id)

    existing = set(
        session.exec(select(SetMembership.case_id).where(SetMembership.set_id == set_id)).all()
    )
    position = next_position(session, set_id)
    attached = 0
    for case_id in payload.case_ids:
        if case_id in existing:
            continue
        session.add(
            SetMembership(
                set_id=set_id,
                case_id=case_id,
                node_id=payload.node_id,
                position=position,
            )
        )
        position += 1
        attached += 1
    session.commit()
    return CountResponse(count=attached)


@router.post("/{set_id}/cases/detach", response_model=CountResponse)
def detach_cases(set_id: int, payload: DetachCases, session: SessionDep) -> CountResponse:
    """Remove cases from the set. The cases themselves survive."""
    get_live_set(session, set_id)
    rows = session.exec(
        select(SetMembership).where(
            SetMembership.set_id == set_id, col(SetMembership.case_id).in_(payload.case_ids)
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.flush()
    compact_positions(session, set_id)
    session.commit()
    return CountResponse(count=len(rows))


@router.post("/{set_id}/cases/reorder", response_model=CountResponse)
def reorder_cases(set_id: int, payload: ReorderCases, session: SessionDep) -> CountResponse:
    """Set explicit positions. Any members not listed keep their relative order after."""
    get_live_set(session, set_id)
    rows = session.exec(select(SetMembership).where(SetMembership.set_id == set_id)).all()
    by_case = {row.case_id: row for row in rows}

    unknown = [cid for cid in payload.case_ids if cid not in by_case]
    if unknown:
        raise ValidationError(
            f"cases are not in set {set_id}: {unknown}", details={"unknown": unknown}
        )

    position = 0
    for case_id in payload.case_ids:
        row = by_case[case_id]
        row.position = position
        session.add(row)
        position += 1

    remaining = sorted(
        (r for r in rows if r.case_id not in set(payload.case_ids)),
        key=lambda r: (r.position, r.id or 0),
    )
    for row in remaining:
        row.position = position
        session.add(row)
        position += 1

    session.commit()
    return CountResponse(count=len(payload.case_ids))


def _assert_cases_exist(session: Session, case_ids: list[int]) -> None:
    found = set(
        session.exec(
            select(EvalCase.id).where(
                col(EvalCase.id).in_(case_ids), col(EvalCase.deleted_at).is_(None)
            )
        ).all()
    )
    missing = [i for i in case_ids if i not in found]
    if missing:
        raise NotFoundError(f"unknown or trashed case ids: {missing}", details={"missing": missing})
