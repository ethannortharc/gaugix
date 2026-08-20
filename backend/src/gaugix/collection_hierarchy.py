"""Small hierarchy helpers shared by collection and set endpoints."""

from __future__ import annotations

from sqlmodel import Session, select

from gaugix.models.cases import EvalCollection


def collections(session: Session) -> list[EvalCollection]:
    return list(session.exec(select(EvalCollection)).all())


def collection_map(rows: list[EvalCollection]) -> dict[int, EvalCollection]:
    return {row.id: row for row in rows if row.id is not None}


def collection_path(
    by_id: dict[int, EvalCollection], collection_id: int | None
) -> list[EvalCollection]:
    result: list[EvalCollection] = []
    seen: set[int] = set()
    current = collection_id
    while current is not None and current not in seen:
        seen.add(current)
        row = by_id.get(current)
        if row is None:
            break
        result.append(row)
        current = row.parent_id
    return list(reversed(result))


def collection_descendant_ids(rows: list[EvalCollection], root_id: int) -> set[int]:
    children: dict[int | None, list[int]] = {}
    for row in rows:
        if row.id is not None:
            children.setdefault(row.parent_id, []).append(row.id)
    result: set[int] = set()
    stack = [root_id]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result
