"""Generic collection hierarchy above eval sets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlmodel import Session, col, select

from gaugix.collection_hierarchy import (
    collection_descendant_ids,
    collection_map,
    collection_path,
    collections,
)
from gaugix.db import get_session
from gaugix.errors import ConflictError, ValidationError
from gaugix.models.cases import EvalCollection, EvalSet
from gaugix.repo import case_count, get_or_404
from gaugix.schemas.collections import CollectionCreate, CollectionRead, CollectionUpdate
from gaugix.schemas.common import CountResponse

router = APIRouter(prefix="/collections", tags=["collections"])
SessionDep = Annotated[Session, Depends(get_session)]


def _next_position(session: Session, parent_id: int | None) -> int:
    statement = select(func.max(EvalCollection.position))
    if parent_id is None:
        statement = statement.where(col(EvalCollection.parent_id).is_(None))
    else:
        statement = statement.where(EvalCollection.parent_id == parent_id)
    highest = session.exec(statement).one()
    return 0 if highest is None else int(highest) + 1


def _validate_parent(
    session: Session,
    parent_id: int | None,
    *,
    current_id: int | None = None,
) -> None:
    if parent_id is None:
        return
    get_or_404(session, EvalCollection, parent_id, "Collection")
    if current_id is None:
        return
    if parent_id == current_id:
        raise ValidationError("a collection cannot be its own parent")
    descendants = collection_descendant_ids(collections(session), current_id)
    if parent_id in descendants:
        raise ValidationError("moving this collection there would create a cycle")


def _to_reads(session: Session, rows: list[EvalCollection]) -> list[CollectionRead]:
    all_rows = collections(session)
    by_id = collection_map(all_rows)
    live_sets = list(session.exec(select(EvalSet).where(col(EvalSet.deleted_at).is_(None))).all())
    set_counts = {row.id: case_count(session, row.id or 0) for row in live_sets}
    result: list[CollectionRead] = []
    for row in rows:
        row_id = row.id or 0
        descendants = collection_descendant_ids(all_rows, row_id)
        direct_sets = [item for item in live_sets if item.collection_id == row_id]
        descendant_sets = [item for item in live_sets if item.collection_id in descendants]
        path = collection_path(by_id, row_id)
        result.append(
            CollectionRead(
                id=row_id,
                key=row.key,
                name=row.name,
                description=row.description,
                parent_id=row.parent_id,
                position=row.position,
                visibility=row.visibility,  # type: ignore[arg-type]
                tags=row.tags,
                provenance=row.provenance,
                path=[item.name for item in path],
                depth=max(0, len(path) - 1),
                direct_set_count=len(direct_sets),
                descendant_set_count=len(descendant_sets),
                direct_case_count=sum(set_counts.get(item.id, 0) for item in direct_sets),
                descendant_case_count=sum(set_counts.get(item.id, 0) for item in descendant_sets),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return result


def _sort_key(row: EvalCollection, by_id: dict[int, EvalCollection]) -> tuple[tuple[int, str], ...]:
    path = collection_path(by_id, row.id)
    return tuple((item.position, item.name.casefold()) for item in path)


@router.get("", response_model=list[CollectionRead])
def list_collections(
    session: SessionDep,
    response: Response,
    visibility: list[str] | None = Query(default=None),
    roots_only: bool = Query(default=False),
) -> list[CollectionRead]:
    rows = collections(session)
    if visibility:
        rows = [row for row in rows if row.visibility in visibility]
    if roots_only:
        rows = [row for row in rows if row.parent_id is None]
    by_id = collection_map(collections(session))
    rows.sort(key=lambda row: _sort_key(row, by_id))
    response.headers["X-Total-Count"] = str(len(rows))
    return _to_reads(session, rows)


@router.post("", response_model=CollectionRead, status_code=201)
def create_collection(payload: CollectionCreate, session: SessionDep) -> CollectionRead:
    if session.exec(select(EvalCollection).where(EvalCollection.key == payload.key)).first():
        raise ConflictError(f"a collection with key {payload.key!r} already exists")
    _validate_parent(session, payload.parent_id)
    row = EvalCollection(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        parent_id=payload.parent_id,
        position=(
            payload.position
            if payload.position is not None
            else _next_position(session, payload.parent_id)
        ),
        visibility=payload.visibility,
    )
    row.tags = payload.tags
    row.provenance = payload.provenance
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_reads(session, [row])[0]


@router.get("/{collection_id}", response_model=CollectionRead)
def get_collection(collection_id: int, session: SessionDep) -> CollectionRead:
    row = get_or_404(session, EvalCollection, collection_id, "Collection")
    return _to_reads(session, [row])[0]


@router.patch("/{collection_id}", response_model=CollectionRead)
def update_collection(
    collection_id: int, payload: CollectionUpdate, session: SessionDep
) -> CollectionRead:
    row = get_or_404(session, EvalCollection, collection_id, "Collection")
    data = payload.model_dump(exclude_unset=True)
    if "key" in data and data["key"] != row.key:
        clash = session.exec(
            select(EvalCollection).where(EvalCollection.key == data["key"])
        ).first()
        if clash:
            raise ConflictError(f"a collection with key {data['key']!r} already exists")
        row.key = data["key"]
    if "parent_id" in data:
        _validate_parent(session, data["parent_id"], current_id=collection_id)
        row.parent_id = data["parent_id"]
    if "name" in data:
        row.name = data["name"]
    if "description" in data:
        row.description = data["description"]
    if "position" in data:
        row.position = data["position"]
    if "visibility" in data:
        row.visibility = data["visibility"]
    if payload.tags is not None:
        row.tags = payload.tags
    if payload.provenance is not None:
        row.provenance = payload.provenance
    row.touch()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_reads(session, [row])[0]


@router.delete("/{collection_id}", response_model=CountResponse)
def delete_collection(collection_id: int, session: SessionDep) -> CountResponse:
    row = get_or_404(session, EvalCollection, collection_id, "Collection")
    child = session.exec(
        select(EvalCollection).where(EvalCollection.parent_id == collection_id)
    ).first()
    member = session.exec(select(EvalSet).where(EvalSet.collection_id == collection_id)).first()
    if child or member:
        raise ConflictError("move the collection's folders and eval sets before deleting it")
    session.delete(row)
    session.commit()
    return CountResponse(count=1, message="deleted")
