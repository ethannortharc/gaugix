"""Entity-centred run history projections for set and case detail pages.

Runs are stored run-first, but debugging starts from the thing being evaluated:
"how has this set changed?" and "what did each executor do on this case?". These
queries project immutable RunItems back onto those entities without duplicating
run ids on mutable Set/Case rows.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlmodel import Session, col, func, select

from gaugix.coverage import SetCoverage, of_run
from gaugix.models.runs import Attempt, Run, RunItem


def set_run_history(
    session: Session, set_id: int, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """Latest runs containing `set_id`, with verdicts scoped to that set."""
    run_ids_stmt = (
        select(RunItem.run_id)
        .where(RunItem.set_id == set_id)
        .distinct()
        .order_by(col(RunItem.run_id).desc())
    )
    all_run_ids = list(session.exec(run_ids_stmt).all())
    total = len(all_run_ids)
    page_ids = all_run_ids[offset : offset + limit]
    if not page_ids:
        return [], total

    runs = session.exec(select(Run).where(col(Run.id).in_(page_ids))).all()
    runs_by_id = {run.id: run for run in runs if run.id is not None}
    items = session.exec(
        select(RunItem).where(
            RunItem.set_id == set_id,
            col(RunItem.run_id).in_(page_ids),
        )
    ).all()
    items_by_run: dict[int, list[RunItem]] = defaultdict(list)
    for item in items:
        items_by_run[item.run_id].append(item)

    rows: list[dict[str, Any]] = []
    for run_id in page_ids:
        run = runs_by_id.get(run_id)
        scoped = items_by_run.get(run_id, [])
        if run is None or not scoped:
            continue
        scored = [item for item in scoped if item.verdict is not None]
        passed = sum(1 for item in scored if item.verdict is True)
        set_coverage = _coverage_for(run, set_id, scoped[0].set_name)
        rows.append(
            {
                "run_id": run_id,
                "run_name": run.name,
                "status": run.status,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
                "executor_keys": sorted({item.executor_key for item in scoped}),
                "item_count": len(scoped),
                "case_count": len({item.case_id for item in scoped if item.case_id is not None}),
                "coverage": set_coverage.describe(),
                "is_partial": set_coverage.is_partial,
                "is_baseline": set_id in run.is_baseline_for,
                "scored": len(scored),
                "passed": passed,
                "failed": len(scored) - passed,
                "unscored": len(scoped) - len(scored),
                "pass_rate": round(100 * passed / len(scored), 1) if scored else None,
            }
        )
    return rows, total


def _coverage_for(run: Run, set_id: int, set_name: str) -> SetCoverage:
    known = of_run(run.config).get(set_id)
    if known is not None:
        return known
    # A malformed/very old config must not make history disappear. `case_ids`
    # still proves restriction even when the exact denominator was not frozen.
    return SetCoverage(
        set_id=set_id,
        set_name=set_name,
        selected=0,
        available=0,
        universe="",
        sizes_known=False,
        restricted=bool(run.config.get("case_ids")),
    )


def case_run_history(
    session: Session, case_id: int, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """Latest RunItems for one case; one row per set × executor execution."""
    statement = (
        select(RunItem, Run)
        .join(Run, col(Run.id) == RunItem.run_id)
        .where(RunItem.case_id == case_id)
        .order_by(col(RunItem.id).desc())
    )
    total = session.exec(
        select(func.count()).select_from(RunItem).where(RunItem.case_id == case_id)
    ).one()
    pairs = session.exec(statement.limit(limit).offset(offset)).all()

    attempt_ids = [item.current_attempt_id for item, _ in pairs if item.current_attempt_id]
    attempts = (
        session.exec(select(Attempt).where(col(Attempt.id).in_(attempt_ids))).all()
        if attempt_ids
        else []
    )
    attempts_by_id = {attempt.id: attempt for attempt in attempts if attempt.id is not None}

    rows: list[dict[str, Any]] = []
    for item, run in pairs:
        attempt = attempts_by_id.get(item.current_attempt_id) if item.current_attempt_id else None
        output = attempt.output_text.strip() if attempt and attempt.output_text else ""
        rows.append(
            {
                "item_id": item.id or 0,
                "run_id": run.id or 0,
                "run_name": run.name,
                "run_status": run.status,
                "run_created_at": run.created_at,
                "set_id": item.set_id,
                "set_name": item.set_name,
                "executor_key": item.executor_key,
                "item_status": item.status,
                "verdict": item.verdict,
                "score_value": item.score_value,
                "needs_human": item.needs_human,
                "error": item.error,
                "output_preview": output[:240] if output else None,
                "latency_ms": attempt.latency_ms if attempt else None,
                "cost_usd": attempt.cost_usd if attempt else None,
                "attempt_n": attempt.n if attempt else None,
            }
        )
    return rows, total
