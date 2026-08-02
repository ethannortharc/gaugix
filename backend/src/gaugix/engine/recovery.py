"""Boot-time recovery scan (ARCHITECTURE §5).

The engine lives in the API process, so killing the server leaves runs claiming to
be `running` and items frozen mid-flight. On boot we reclassify them honestly:
the run becomes `interrupted` (resumable), and any item caught in `invoking` or
`scoring` becomes `error` with `error="interrupted"` so resume re-executes it as a
**new attempt** rather than pretending the old one finished.

Items that had already reached `passed`/`failed` are never touched — that is work
the user paid for.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from gaugix.domain import AttemptStatus, ItemStatus, RunStatus
from gaugix.logging_setup import get_logger
from gaugix.models.base import utcnow
from gaugix.models.runs import Attempt, Run, RunItem

log = get_logger("gaugix.recovery")

INTERRUPTED = "interrupted"

#: Item statuses that mean "in flight when the process died".
IN_FLIGHT = (str(ItemStatus.invoking), str(ItemStatus.scoring))


@dataclass(slots=True)
class RecoveryReport:
    runs_interrupted: int = 0
    items_reclassified: int = 0
    run_ids: list[int] | None = None


def recover_interrupted_runs(engine: Engine) -> RecoveryReport:
    """Reclassify runs and items left behind by a crash. Idempotent."""
    report = RecoveryReport(run_ids=[])

    with Session(engine) as session:
        runs = session.exec(select(Run).where(Run.status == str(RunStatus.running))).all()
        for run in runs:
            run.status = str(RunStatus.interrupted)
            run.finished_at = run.finished_at or utcnow()
            run.touch()
            session.add(run)
            report.runs_interrupted += 1
            if report.run_ids is not None and run.id is not None:
                report.run_ids.append(run.id)

            items = session.exec(
                select(RunItem).where(RunItem.run_id == run.id, col(RunItem.status).in_(IN_FLIGHT))
            ).all()
            for item in items:
                item.status = str(ItemStatus.error)
                item.error = INTERRUPTED
                item.touch()
                session.add(item)
                report.items_reclassified += 1

                # The half-written attempt is history, not a result.
                attempt = session.exec(
                    select(Attempt)
                    .where(Attempt.run_item_id == item.id)
                    .order_by(col(Attempt.n).desc())
                ).first()
                if attempt is not None and attempt.status != str(AttemptStatus.error):
                    attempt.status = str(AttemptStatus.error)
                    attempt.error = attempt.error or INTERRUPTED
                    attempt.error_kind = attempt.error_kind or INTERRUPTED
                    session.add(attempt)

        session.commit()

    if report.runs_interrupted:
        log.warning(
            "recovered_interrupted_runs",
            runs=report.runs_interrupted,
            items=report.items_reclassified,
        )
    return report
