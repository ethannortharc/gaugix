"""Tree-shaped organisation inside an EvalSet."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, col, select

from gaugix.db import get_session
from gaugix.errors import ConflictError, ValidationError
from gaugix.hierarchy import (
    descendant_ids,
    effective_provenance,
    get_set_node,
    node_map,
    nodes_for_set,
    path_nodes,
)
from gaugix.models.cases import EvalSet, EvalSetNode, SetMembership
from gaugix.repo import get_live_set
from gaugix.schemas.cases import AssignCasesNode, SetNodeCreate, SetNodeRead, SetNodeUpdate
from gaugix.schemas.common import CountResponse

router = APIRouter(prefix="/sets", tags=["set hierarchy"])
SessionDep = Annotated[Session, Depends(get_session)]


def _read_nodes(session: Session, set_id: int) -> list[SetNodeRead]:
    nodes = nodes_for_set(session, set_id)
    by_id = node_map(nodes)
    eval_set = session.get(EvalSet, set_id)
    base_provenance: dict[str, object] = {}
    if eval_set is not None:
        from gaugix.benchmarks import effective_provenance as set_provenance

        base_provenance = set_provenance(session, eval_set)
    direct = Counter(
        dict(
            session.exec(
                select(SetMembership.node_id, func.count())
                .where(SetMembership.set_id == set_id, col(SetMembership.node_id).is_not(None))
                .group_by(col(SetMembership.node_id))
            ).all()
        )
    )
    result: list[SetNodeRead] = []
    for node in nodes:
        node_id = node.id or 0
        descendants = descendant_ids(nodes, node_id)
        result.append(
            SetNodeRead(
                id=node_id,
                set_id=node.set_id,
                parent_id=node.parent_id,
                name=node.name,
                description=node.description,
                position=node.position,
                tags=node.tags,
                provenance=node.provenance,
                effective_provenance=effective_provenance(by_id, node_id, base_provenance),
                path=[part.name for part in path_nodes(by_id, node_id)],
                depth=max(0, len(path_nodes(by_id, node_id)) - 1),
                direct_case_count=direct[node_id],
                descendant_case_count=sum(direct[part] for part in descendants),
                created_at=node.created_at,
                updated_at=node.updated_at,
            )
        )
    return result


def _assert_unique_sibling(
    session: Session,
    set_id: int,
    parent_id: int | None,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    statement = select(EvalSetNode).where(
        EvalSetNode.set_id == set_id,
        EvalSetNode.name == name.strip(),
    )
    if parent_id is None:
        statement = statement.where(col(EvalSetNode.parent_id).is_(None))
    else:
        statement = statement.where(EvalSetNode.parent_id == parent_id)
    if exclude_id is not None:
        statement = statement.where(EvalSetNode.id != exclude_id)
    if session.exec(statement).first() is not None:
        raise ConflictError(f"a sibling named {name.strip()!r} already exists")


def _next_node_position(session: Session, set_id: int, parent_id: int | None) -> int:
    statement = select(func.max(EvalSetNode.position)).where(EvalSetNode.set_id == set_id)
    if parent_id is None:
        statement = statement.where(col(EvalSetNode.parent_id).is_(None))
    else:
        statement = statement.where(EvalSetNode.parent_id == parent_id)
    highest = session.exec(statement).one()
    return 0 if highest is None else int(highest) + 1


@router.get("/{set_id}/nodes", response_model=list[SetNodeRead])
def list_nodes(set_id: int, session: SessionDep) -> list[SetNodeRead]:
    get_live_set(session, set_id)
    return _read_nodes(session, set_id)


@router.post("/{set_id}/nodes", response_model=SetNodeRead, status_code=201)
def create_node(set_id: int, payload: SetNodeCreate, session: SessionDep) -> SetNodeRead:
    get_live_set(session, set_id)
    if payload.parent_id is not None:
        get_set_node(session, set_id, payload.parent_id)
    name = payload.name.strip()
    _assert_unique_sibling(session, set_id, payload.parent_id, name)
    node = EvalSetNode(
        set_id=set_id,
        parent_id=payload.parent_id,
        name=name,
        description=payload.description,
        position=(
            payload.position
            if payload.position is not None
            else _next_node_position(session, set_id, payload.parent_id)
        ),
    )
    node.tags = payload.tags
    node.provenance = payload.provenance
    session.add(node)
    session.commit()
    return next(item for item in _read_nodes(session, set_id) if item.id == node.id)


@router.patch("/{set_id}/nodes/{node_id}", response_model=SetNodeRead)
def update_node(
    set_id: int, node_id: int, payload: SetNodeUpdate, session: SessionDep
) -> SetNodeRead:
    get_live_set(session, set_id)
    node = get_set_node(session, set_id, node_id)
    data = payload.model_dump(exclude_unset=True)
    parent_id = data.get("parent_id", node.parent_id)
    if parent_id is not None:
        get_set_node(session, set_id, parent_id)
    if parent_id == node_id:
        raise ValidationError("a node cannot be its own parent")
    if parent_id in descendant_ids(nodes_for_set(session, set_id), node_id) - {node_id}:
        raise ValidationError("moving this node there would create a cycle")
    name = str(data.get("name", node.name)).strip()
    _assert_unique_sibling(session, set_id, parent_id, name, exclude_id=node_id)

    if "name" in data:
        node.name = name
    if "parent_id" in data:
        node.parent_id = parent_id
    if "description" in data:
        node.description = data["description"]
    if "position" in data:
        node.position = data["position"]
    if payload.tags is not None:
        node.tags = payload.tags
    if payload.provenance is not None:
        node.provenance = payload.provenance
    node.touch()
    session.add(node)
    session.commit()
    return next(item for item in _read_nodes(session, set_id) if item.id == node_id)


@router.delete("/{set_id}/nodes/{node_id}", response_model=CountResponse)
def delete_node(set_id: int, node_id: int, session: SessionDep) -> CountResponse:
    get_live_set(session, set_id)
    node = get_set_node(session, set_id, node_id)
    if session.exec(select(EvalSetNode.id).where(EvalSetNode.parent_id == node_id)).first():
        raise ConflictError("move or delete this node's children first")
    if session.exec(select(SetMembership.id).where(SetMembership.node_id == node_id)).first():
        raise ConflictError("move this node's cases first")
    session.delete(node)
    session.commit()
    return CountResponse(count=1)


@router.post("/{set_id}/nodes/assign", response_model=CountResponse)
def assign_cases(set_id: int, payload: AssignCasesNode, session: SessionDep) -> CountResponse:
    get_live_set(session, set_id)
    if payload.node_id is not None:
        get_set_node(session, set_id, payload.node_id)
    rows = session.exec(
        select(SetMembership).where(
            SetMembership.set_id == set_id,
            col(SetMembership.case_id).in_(payload.case_ids),
        )
    ).all()
    found = {row.case_id for row in rows}
    missing = [case_id for case_id in payload.case_ids if case_id not in found]
    if missing:
        raise ValidationError(
            f"cases are not in set {set_id}: {missing}", details={"unknown": missing}
        )
    for row in rows:
        row.node_id = payload.node_id
        session.add(row)
    session.commit()
    return CountResponse(count=len(rows))
