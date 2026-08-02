"""Re-score stored outputs after a config change (PRD F4.3).

The whole point: fixing a regex or rewriting a rubric must not cost another round
of model calls. This reads `attempt.output_text` and appends new Score versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from gaugix.domain import ExecutorSnapshot, ScorerType
from gaugix.errors import ValidationError
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.scoring.service import score_item


@dataclass(slots=True)
class RescoreReport:
    items_rescored: int = 0
    items_skipped: int = 0
    verdict_changes: int = 0
    configs_refreshed: int = 0
    details: list[dict[str, object]] = field(default_factory=list)


def refresh_scoring_config(session: Session, item: RunItem) -> bool:
    """Pull the case's *current* scoring config into the item snapshot.

    This is the one deliberate exception to the snapshot rule, and PRD F4.3 is
    why: "fixed regex, new rubric → re-score" is pointless if re-scoring keeps
    applying the broken config. What stays frozen is everything that determines
    *what the model produced* — the input, the params, the recorded output. Only
    the ruler is allowed to change, and the new Score rows carry the new config
    hash so the change is visible in the history.
    """
    from gaugix.models.cases import EvalCase

    if item.case_id is None:
        return False
    case = session.get(EvalCase, item.case_id)
    if case is None:
        return False

    snapshot = item.case_snapshot
    live_scoring = case.scoring
    if not live_scoring:
        # The case now inherits its set default; leave the frozen config alone
        # rather than silently scoring against nothing.
        return False
    if [s.model_dump() for s in live_scoring] == [s.model_dump() for s in snapshot.scoring]:
        return False

    snapshot.scoring = live_scoring
    item.case_snapshot = snapshot
    session.add(item)
    session.flush()
    return True


async def rescore_items(
    session: Session,
    item_ids: list[int],
    judge_executor: ExecutorSnapshot | None = None,
    scorer_indices: list[int] | None = None,
    refresh_config: bool = True,
) -> RescoreReport:
    """Re-run auto/judge scorers against stored outputs.

    With `refresh_config` (the default), each item first picks up its case's
    current scoring config — that is what makes "I fixed the regex" work.
    """
    report = RescoreReport()

    for item_id in item_ids:
        item = session.get(RunItem, item_id)
        if item is None:
            report.items_skipped += 1
            continue

        attempt = session.exec(
            select(Attempt)
            .where(Attempt.run_item_id == item_id, col(Attempt.superseded).is_(False))
            .order_by(col(Attempt.n).desc())
        ).first()
        if attempt is None or not attempt.output_text:
            # Nothing was produced, so there is nothing to score. Re-invoking is
            # what `resume` is for; re-scoring never calls a model.
            report.items_skipped += 1
            continue

        executor = _executor_for(session, item)
        if executor is None:
            report.items_skipped += 1
            continue

        if refresh_config and refresh_scoring_config(session, item):
            report.configs_refreshed += 1
            session.refresh(item)

        before = item.verdict
        outcome = await score_item(
            session,
            item,
            attempt,
            executor,
            judge_executor=judge_executor,
            only_indices=scorer_indices,
            use_frozen_judges=False,
        )
        report.items_rescored += 1
        if before != outcome.verdict:
            report.verdict_changes += 1
            report.details.append(
                {
                    "item_id": item_id,
                    "title": item.title,
                    "before": before,
                    "after": outcome.verdict,
                }
            )

    return report


def _executor_for(session: Session, item: RunItem) -> ExecutorSnapshot | None:
    """The frozen executor snapshot this item ran under."""
    run = session.get(Run, item.run_id)
    if run is None:
        return None
    for executor in run.executors:
        if executor.key == item.executor_key:
            return executor
    return run.executors[0] if run.executors else None


def items_for_run(session: Session, run_id: int, only_failing: bool = False) -> list[int]:
    """Item ids in a run that have something worth re-scoring."""
    statement = select(RunItem).where(RunItem.run_id == run_id)
    rows = session.exec(statement.order_by(col(RunItem.position))).all()
    if only_failing:
        rows = [r for r in rows if r.verdict is False]
    return [r.id for r in rows if r.id is not None]


def needs_judge(session: Session, item_ids: list[int]) -> bool:
    """Whether any selected item has an llm_judge scorer — i.e. would spend money."""
    for item_id in item_ids:
        item = session.get(RunItem, item_id)
        if item is None:
            continue
        if any(s.type == ScorerType.llm_judge for s in item.case_snapshot.scoring):
            return True
    return False


def validate_selection(run_id: int | None, item_ids: list[int] | None) -> None:
    if run_id is None and not item_ids:
        raise ValidationError("provide either run_id or item_ids")
