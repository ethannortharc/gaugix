"""Shared persistence helpers used by the routers.

Small, boring functions that keep the routers readable and make "not found"
behave identically everywhere.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, SQLModel, col, select

from gaugix.errors import NotFoundError
from gaugix.models.cases import EvalCase, EvalSet, SetMembership


def get_or_404[M: SQLModel](
    session: Session, model: type[M], pk: int, label: str | None = None
) -> M:
    """Fetch by primary key or raise the standard 404."""
    obj = session.get(model, pk)
    if obj is None:
        name = label or model.__name__
        raise NotFoundError(f"{name} {pk} does not exist")
    return obj


def get_live_case(session: Session, case_id: int) -> EvalCase:
    """Fetch a case that is not in the Trash."""
    case = get_or_404(session, EvalCase, case_id, "Case")
    if case.deleted_at is not None:
        raise NotFoundError(f"Case {case_id} is in the trash")
    return case


def get_live_set(session: Session, set_id: int) -> EvalSet:
    eval_set = get_or_404(session, EvalSet, set_id, "Set")
    if eval_set.deleted_at is not None:
        raise NotFoundError(f"Set {set_id} is in the trash")
    return eval_set


def next_position(session: Session, set_id: int) -> int:
    """Position for a case appended to the end of a set."""
    highest = session.exec(
        select(func.max(SetMembership.position)).where(SetMembership.set_id == set_id)
    ).one()
    return 0 if highest is None else int(highest) + 1


def case_count(session: Session, set_id: int) -> int:
    """Number of live (non-trashed) cases in a set."""
    result = session.exec(
        select(func.count())
        .select_from(SetMembership)
        .join(EvalCase, col(EvalCase.id) == col(SetMembership.case_id))
        .where(SetMembership.set_id == set_id, col(EvalCase.deleted_at).is_(None))
    ).one()
    return int(result)


def memberships_for_cases(
    session: Session, case_ids: list[int]
) -> dict[int, list[tuple[int, str, int]]]:
    """Map case id → [(set_id, set_name, position)], for the "which sets" display."""
    if not case_ids:
        return {}
    rows = session.exec(
        select(SetMembership.case_id, EvalSet.id, EvalSet.name, SetMembership.position)
        .join(EvalSet, col(EvalSet.id) == col(SetMembership.set_id))
        .where(col(SetMembership.case_id).in_(case_ids), col(EvalSet.deleted_at).is_(None))
        .order_by(col(EvalSet.name))
    ).all()
    out: dict[int, list[tuple[int, str, int]]] = {}
    for case_id, set_id, set_name, position in rows:
        if set_id is None:
            continue
        out.setdefault(case_id, []).append((set_id, set_name, position))
    return out


def compact_positions(session: Session, set_id: int) -> None:
    """Renumber a set's memberships to 0..n-1, preserving order.

    Called after detaches so positions never develop gaps that would make manual
    reordering confusing.
    """
    rows = session.exec(
        select(SetMembership)
        .where(SetMembership.set_id == set_id)
        .order_by(col(SetMembership.position), col(SetMembership.id))
    ).all()
    for index, row in enumerate(rows):
        if row.position != index:
            row.position = index
            session.add(row)
