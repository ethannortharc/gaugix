"""Helpers for EvalSet's optional organisational tree."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlmodel import Session, col, select

from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.cases import EvalSetNode


def nodes_for_set(session: Session, set_id: int) -> list[EvalSetNode]:
    return list(
        session.exec(
            select(EvalSetNode)
            .where(EvalSetNode.set_id == set_id)
            .order_by(col(EvalSetNode.parent_id), col(EvalSetNode.position), col(EvalSetNode.id))
        ).all()
    )


def node_map(nodes: Iterable[EvalSetNode]) -> dict[int, EvalSetNode]:
    return {node.id: node for node in nodes if node.id is not None}


def get_set_node(session: Session, set_id: int, node_id: int) -> EvalSetNode:
    node = session.get(EvalSetNode, node_id)
    if node is None or node.set_id != set_id:
        raise NotFoundError(f"Node {node_id} does not exist in set {set_id}")
    return node


def path_nodes(nodes: dict[int, EvalSetNode], node_id: int | None) -> list[EvalSetNode]:
    """Return root → leaf, rejecting corrupted cycles instead of looping forever."""
    if node_id is None:
        return []
    path: list[EvalSetNode] = []
    seen: set[int] = set()
    current_id: int | None = node_id
    while current_id is not None:
        if current_id in seen:
            raise ValidationError("eval set hierarchy contains a cycle")
        seen.add(current_id)
        current = nodes.get(current_id)
        if current is None:
            break
        path.append(current)
        current_id = current.parent_id
    path.reverse()
    return path


def descendant_ids(nodes: Iterable[EvalSetNode], node_id: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for node in nodes:
        if node.id is not None and node.parent_id is not None:
            children.setdefault(node.parent_id, []).append(node.id)
    found = {node_id}
    pending = [node_id]
    while pending:
        current = pending.pop()
        for child_id in children.get(current, []):
            if child_id not in found:
                found.add(child_id)
                pending.append(child_id)
    return found


def effective_provenance(
    nodes: dict[int, EvalSetNode],
    node_id: int | None,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge set → ancestors → leaf, so a branch only states its overrides."""
    merged = dict(base or {})
    for node in path_nodes(nodes, node_id):
        merged.update(node.provenance)
    return merged


def frozen_nodes(
    nodes: list[EvalSetNode], base: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Stable node metadata stored in a run's set snapshot."""
    by_id = node_map(nodes)
    return [
        {
            "id": node.id,
            "parent_id": node.parent_id,
            "name": node.name,
            "description": node.description,
            "position": node.position,
            "tags": node.tags,
            "path": [part.name for part in path_nodes(by_id, node.id)],
            "path_ids": [part.id for part in path_nodes(by_id, node.id) if part.id is not None],
            "provenance": effective_provenance(by_id, node.id, base),
        }
        for node in nodes
    ]


def ensure_node_path(
    session: Session,
    set_id: int,
    names: list[str],
    *,
    parent_id: int | None = None,
) -> int | None:
    """Find or create a path below ``parent_id`` and return its leaf id.

    Imports normally provide a root-relative ``group_path``.  A caller adding
    cases from inside an existing branch can provide ``parent_id`` so imported
    subgroups are created below that branch instead of at the set root.
    """
    if parent_id is not None:
        get_set_node(session, set_id, parent_id)
    if not names:
        return parent_id
    nodes = nodes_for_set(session, set_id)
    by_sibling = {(node.parent_id, node.name): node for node in nodes}
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            raise ValidationError("group path parts must not be blank")
        existing = by_sibling.get((parent_id, name))
        if existing is not None:
            parent_id = existing.id
            continue
        sibling_positions = [node.position for node in nodes if node.parent_id == parent_id]
        node = EvalSetNode(
            set_id=set_id,
            parent_id=parent_id,
            name=name,
            position=max(sibling_positions, default=-1) + 1,
        )
        session.add(node)
        session.flush()
        nodes.append(node)
        by_sibling[(parent_id, name)] = node
        parent_id = node.id
    return parent_id
