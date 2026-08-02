"""The run engine (ARCHITECTURE §5).

A single in-process async orchestrator. Design constraints that shape everything
here:

* **Crash-safe.** Every item state transition is committed immediately, so killing
  the process loses at most the in-flight invocations — which recovery reclassifies
  as `error` and resume re-executes.
* **Two limits.** A per-run concurrency semaphore (from the run config) and a
  per-provider cap, so one slow provider cannot monopolise the pool.
* **Scorer bugs are not invocation failures.** A crashed scorer records a Score with
  `passed=None` and is fixed by re-scoring; it never triggers a re-invocation. Only
  provider failures produce `error`.
* **Cancel is graceful.** In-flight work gets a grace period, unstarted items become
  `skipped`, and the run ends `canceled`.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from gaugix.config import Settings, get_settings
from gaugix.domain import (
    AttemptStatus,
    CaseSnapshot,
    ExecutorSnapshot,
    HarnessError,
    InvocationResult,
    InvokeContext,
    ItemStatus,
    RunStatus,
    Usage,
)
from gaugix.engine.events import EventType, bus
from gaugix.engine.planner import empty_totals
from gaugix.harness import get as get_harness
from gaugix.logging_setup import get_logger
from gaugix.models.base import utcnow
from gaugix.models.runs import Attempt, Run, RunItem

log = get_logger("gaugix.runner")

MAX_RETRIES = 2
BASE_BACKOFF_S = 0.5
CANCEL_GRACE_S = 10.0

#: Statuses whose work is finished and must never be re-executed (PRD F3.5).
KEPT_STATUSES = frozenset({str(ItemStatus.passed), str(ItemStatus.failed)})


@dataclass(slots=True)
class RunnerHandle:
    """A live run: its task, its cancel signal, and how it was scheduled."""

    run_id: int
    task: asyncio.Task[None]
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class RunnerRegistry:
    """One active runner per run — the guard against double-start and double-resume."""

    def __init__(self) -> None:
        self._handles: dict[int, RunnerHandle] = {}

    def register(self, handle: RunnerHandle) -> None:
        self._handles[handle.run_id] = handle

    def get(self, run_id: int) -> RunnerHandle | None:
        handle = self._handles.get(run_id)
        if handle is not None and handle.task.done():
            self._handles.pop(run_id, None)
            return None
        return handle

    def is_active(self, run_id: int) -> bool:
        return self.get(run_id) is not None

    def discard(self, run_id: int) -> None:
        self._handles.pop(run_id, None)

    def active_ids(self) -> list[int]:
        return [rid for rid in list(self._handles) if self.is_active(rid)]

    async def cancel_all(self) -> None:
        for handle in list(self._handles.values()):
            handle.cancel_event.set()
        for handle in list(self._handles.values()):
            handle.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await handle.task
        self._handles.clear()


registry = RunnerRegistry()

#: Injected by the scoring layer; keeps the runner free of a scoring import at
#: module level (and lets tests run the engine with scoring switched off).
ScoreHook = Callable[[Session, RunItem, Attempt, ExecutorSnapshot], Awaitable[Any]]
_score_hook: ScoreHook | None = None


def set_score_hook(hook: ScoreHook | None) -> None:
    """Register the scoring pass the runner calls after a successful invocation."""
    global _score_hook
    _score_hook = hook


def get_score_hook() -> ScoreHook | None:
    return _score_hook


class Runner:
    """Executes one run's schedulable items."""

    def __init__(
        self,
        engine: Engine,
        run_id: int,
        cancel_event: asyncio.Event,
        settings: Settings | None = None,
    ) -> None:
        self.engine = engine
        self.run_id = run_id
        self.cancel = cancel_event
        self.settings = settings or get_settings()
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}

    # -- entry point -------------------------------------------------------

    async def execute(self, item_ids: list[int]) -> None:
        """Run the given items, then finalise the run's status and totals."""
        executors = self._load_executors()
        concurrency = max(1, int(self._run_config().get("concurrency", 4)))
        auto_score = bool(self._run_config().get("auto_score", True))
        gate = asyncio.Semaphore(concurrency)

        self._set_run_status(RunStatus.running, started=True)
        bus.emit(EventType.log, self.run_id, message=f"Running {len(item_ids)} items")

        aborted: BaseException | None = None
        try:
            async with asyncio.TaskGroup() as group:
                for item_id in item_ids:
                    group.create_task(self._run_item(item_id, executors, gate, auto_score))
        except* Exception as exc_group:
            # An item task should never escape; if one does, the run itself failed.
            # (`return` is not allowed inside except*, hence the flag.)
            aborted = exc_group.exceptions[0]
            log.exception("runner_aborted", run_id=self.run_id, errors=str(exc_group.exceptions))

        if aborted is not None:
            self._finalise(RunStatus.failed, error=str(aborted))
            return

        if self.cancel.is_set():
            self._skip_unstarted()
            self._finalise(RunStatus.canceled)
        else:
            self._finalise(RunStatus.completed)

    # -- per item ----------------------------------------------------------

    async def _run_item(
        self,
        item_id: int,
        executors: dict[str, ExecutorSnapshot],
        gate: asyncio.Semaphore,
        auto_score: bool,
    ) -> None:
        if self.cancel.is_set():
            self._mark_skipped(item_id)
            return

        async with gate:
            if self.cancel.is_set():
                self._mark_skipped(item_id)
                return

            with Session(self.engine) as session:
                item = session.get(RunItem, item_id)
                if item is None:
                    return
                executor = executors.get(item.executor_key)
                if executor is None:
                    self._fail_item(
                        session, item, f"executor {item.executor_key!r} is not in this run"
                    )
                    return
                case = item.case_snapshot
                attempt_n = self._next_attempt_n(session, item_id)
                self._transition(session, item, ItemStatus.invoking)

            provider = str(executor.model.provider)
            try:
                result, retries = await self._invoke_with_retry(case, executor, attempt_n, provider)
            except asyncio.CancelledError:
                with Session(self.engine) as session:
                    item = session.get(RunItem, item_id)
                    if item is not None:
                        self._write_error_attempt(
                            session, item, attempt_n, "canceled", "canceled", retries=0
                        )
                raise
            except HarnessError as exc:
                with Session(self.engine) as session:
                    item = session.get(RunItem, item_id)
                    if item is not None:
                        self._write_error_attempt(
                            session, item, attempt_n, exc.message, exc.kind, retries=exc.retries
                        )
                return

            with Session(self.engine) as session:
                item = session.get(RunItem, item_id)
                if item is None:
                    return
                attempt = self._write_ok_attempt(session, item, attempt_n, result, retries)
                self._transition(session, item, ItemStatus.scoring)
                await self._score(session, item, attempt, executor, auto_score)

    async def _invoke_with_retry(
        self, case: CaseSnapshot, executor: ExecutorSnapshot, attempt_n: int, provider: str
    ) -> tuple[InvocationResult, int]:
        """Invoke with ≤2 retries on transient errors, exponential backoff + jitter."""
        harness = get_harness(executor.harness.kind)
        ctx = InvokeContext(
            run_id=self.run_id,
            attempt_n=attempt_n,
            harness_config=executor.harness.config,
            params=executor.effective_params(),
        )

        last: HarnessError | None = None
        for retry in range(MAX_RETRIES + 1):
            if self.cancel.is_set():
                raise HarnessError("canceled before invocation", retryable=False, kind="canceled")
            try:
                async with self._provider_gate(provider):
                    ctx.try_index = retry
                    return await harness.invoke(case, executor.model, ctx), retry
            except HarnessError as exc:
                last = exc
                if not exc.retryable or retry == MAX_RETRIES:
                    exc.retries = retry
                    raise
                delay = BASE_BACKOFF_S * (2**retry) + random.uniform(0, 0.25)
                bus.emit(
                    EventType.log,
                    self.run_id,
                    level="warn",
                    message=f"retrying after {exc.message} (attempt {retry + 1}/{MAX_RETRIES})",
                )
                await asyncio.sleep(delay)

        raise last or HarnessError("invocation failed", retryable=False)

    def _provider_gate(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._provider_semaphores:
            self._provider_semaphores[provider] = asyncio.Semaphore(
                max(1, self.settings.provider_concurrency)
            )
        return self._provider_semaphores[provider]

    # -- persistence -------------------------------------------------------

    def _next_attempt_n(self, session: Session, item_id: int) -> int:
        existing = session.exec(
            select(Attempt).where(Attempt.run_item_id == item_id).order_by(col(Attempt.n).desc())
        ).first()
        return 1 if existing is None else existing.n + 1

    def _write_ok_attempt(
        self, session: Session, item: RunItem, n: int, result: InvocationResult, retries: int
    ) -> Attempt:
        attempt = Attempt(
            run_item_id=item.id or 0,
            n=n,
            status=str(AttemptStatus.ok),
            output_text=result.output_text,
            retries=retries,
        )
        attempt.messages = result.messages
        attempt.request = result.raw
        attempt.usage = result.usage
        session.add(attempt)
        session.flush()

        self._write_artifacts(session, item, attempt, result)

        item.current_attempt_id = attempt.id
        item.error = None
        item.touch()
        session.add(item)
        session.commit()

        self._add_usage(result.usage)
        bus.emit(
            EventType.usage_delta,
            self.run_id,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            cost_usd=result.usage.cost_usd,
        )
        session.refresh(attempt)
        return attempt

    def _write_artifacts(
        self, session: Session, item: RunItem, attempt: Attempt, result: InvocationResult
    ) -> None:
        """Store the raw output, its code blocks, and whatever the harness collected.

        Best-effort by design: a full disk must not turn a completed attempt into
        a failed one. The failure is logged and the run carries on with the
        output still safely in the database.
        """
        from gaugix.artifacts import capture

        try:
            capture.capture_attempt(
                session,
                run_id=self.run_id,
                item_id=item.id or 0,
                attempt_id=attempt.id or 0,
                attempt_n=attempt.n,
                output_text=result.output_text,
                harness_artifacts=result.artifacts,
            )
        except Exception as exc:  # pragma: no cover - disk failures are not simulated
            log.warning("artifact_capture_failed", item_id=item.id, error=str(exc))

    def _write_error_attempt(
        self, session: Session, item: RunItem, n: int, message: str, kind: str, retries: int
    ) -> None:
        attempt = Attempt(
            run_item_id=item.id or 0,
            n=n,
            status=str(AttemptStatus.error),
            error=message,
            error_kind=kind,
            retries=retries,
        )
        session.add(attempt)
        session.flush()
        item.current_attempt_id = attempt.id
        item.error = message
        session.add(item)
        self._transition(session, item, ItemStatus.error)

    async def _score(
        self,
        session: Session,
        item: RunItem,
        attempt: Attempt,
        executor: ExecutorSnapshot,
        auto_score: bool,
    ) -> None:
        """Run auto scorers, then set the terminal status from the verdict."""
        hook = get_score_hook()
        if auto_score and hook is not None:
            try:
                await hook(session, item, attempt, executor)
            except Exception as exc:
                # A scoring-layer crash must not lose the invocation we paid for.
                log.exception("scoring_failed", run_id=self.run_id, item_id=item.id)
                bus.emit(
                    EventType.log,
                    self.run_id,
                    level="error",
                    message=f"scoring failed for item {item.id}: {exc}",
                )
                item.error = f"scoring error: {exc}"

        session.refresh(item)
        # verdict None (no scorers, or only unresolved human scorers) still counts as
        # done — the UI shows it as "done (unscored)" per ARCHITECTURE §5.
        status = ItemStatus.failed if item.verdict is False else ItemStatus.passed
        self._transition(session, item, status)

    def _transition(self, session: Session, item: RunItem, status: ItemStatus) -> None:
        """Persist a state change immediately and tell the UI (crash-safe, NFR-D)."""
        previous = item.status
        item.status = str(status)
        item.touch()
        session.add(item)
        session.commit()

        self._bump_totals(previous, str(status), item)
        bus.emit(
            EventType.item_status,
            self.run_id,
            item_id=item.id,
            status=str(status),
            executor_key=item.executor_key,
            verdict=item.verdict,
            score_value=item.score_value,
            needs_human=item.needs_human,
            title=item.title,
        )

    def _mark_skipped(self, item_id: int) -> None:
        with Session(self.engine) as session:
            item = session.get(RunItem, item_id)
            if item is None or item.status in KEPT_STATUSES:
                return
            self._transition(session, item, ItemStatus.skipped)

    def _fail_item(self, session: Session, item: RunItem, message: str) -> None:
        item.error = message
        session.add(item)
        self._transition(session, item, ItemStatus.error)

    def _skip_unstarted(self) -> None:
        """Everything still pending when a cancel lands becomes `skipped` (PRD F3.4)."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(RunItem).where(
                    RunItem.run_id == self.run_id,
                    col(RunItem.status).in_(
                        [str(ItemStatus.pending), str(ItemStatus.invoking), str(ItemStatus.scoring)]
                    ),
                )
            ).all()
            for item in rows:
                self._transition(session, item, ItemStatus.skipped)

    # -- run-level bookkeeping --------------------------------------------

    def _run_config(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            return run.config if run else {}

    def _load_executors(self) -> dict[str, ExecutorSnapshot]:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            return {e.key: e for e in (run.executors if run else [])}

    def _set_run_status(self, status: RunStatus, started: bool = False) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            if run is None:
                return
            run.status = str(status)
            if started and run.started_at is None:
                run.started_at = utcnow()
            run.touch()
            session.add(run)
            session.commit()
        bus.emit(EventType.run_status, self.run_id, status=str(status))

    def _finalise(self, status: RunStatus, error: str | None = None) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            if run is None:
                return
            run.status = str(status)
            run.finished_at = utcnow()
            run.error = error
            run.totals = recompute_totals(session, self.run_id)
            run.touch()
            session.add(run)
            session.commit()
            totals = run.totals
        bus.emit(EventType.run_status, self.run_id, status=str(status), totals=totals, final=True)

    def _bump_totals(self, previous: str, current: str, item: RunItem) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            if run is None:
                return
            totals = {**empty_totals(), **run.totals}
            if previous in totals:
                totals[previous] = max(0, int(totals[previous]) - 1)
            if current in totals:
                totals[current] = int(totals[current]) + 1
            totals.update(_verdict_counts(session, self.run_id))
            run.totals = totals
            session.add(run)
            session.commit()

    def _add_usage(self, usage: Usage) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, self.run_id)
            if run is None:
                return
            totals = {**empty_totals(), **run.totals}
            totals["prompt_tokens"] = int(totals["prompt_tokens"]) + usage.prompt_tokens
            totals["completion_tokens"] = int(totals["completion_tokens"]) + usage.completion_tokens
            if usage.cost_usd is None:
                # Remember that at least one attempt had no computable cost, so the
                # UI can show "≥ $x" rather than implying the total is exact.
                totals["cost_unknown"] = True
            else:
                totals["cost_usd"] = float(totals["cost_usd"]) + usage.cost_usd
            run.totals = totals
            session.add(run)
            session.commit()


def _verdict_counts(session: Session, run_id: int) -> dict[str, int]:
    """Verdict tallies, counted directly rather than inferred from item status."""
    rows = session.exec(
        select(RunItem.verdict, RunItem.status, RunItem.needs_human).where(RunItem.run_id == run_id)
    ).all()
    scored = sum(1 for verdict, _, _ in rows if verdict is not None)
    return {
        "scored": scored,
        "verdict_passed": sum(1 for verdict, _, _ in rows if verdict is True),
        "unscored": sum(
            1 for verdict, status, _ in rows if verdict is None and status == str(ItemStatus.passed)
        ),
        "needs_human": sum(1 for _, _, needs_human in rows if needs_human),
    }


def recompute_totals(session: Session, run_id: int) -> dict[str, Any]:
    """Rebuild a run's counters from its items — the source of truth on finalise."""
    totals = empty_totals()
    items = session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
    totals["items"] = len(items)
    for item in items:
        if item.status in totals:
            totals[item.status] = int(totals[item.status]) + 1
    totals.update(_verdict_counts(session, run_id))

    item_ids = [i.id for i in items if i.id is not None]
    if item_ids:
        attempts = session.exec(
            select(Attempt).where(
                col(Attempt.run_item_id).in_(item_ids), col(Attempt.superseded).is_(False)
            )
        ).all()
        for attempt in attempts:
            totals["prompt_tokens"] = int(totals["prompt_tokens"]) + attempt.prompt_tokens
            totals["completion_tokens"] = (
                int(totals["completion_tokens"]) + attempt.completion_tokens
            )
            if attempt.status != str(AttemptStatus.error):
                if attempt.cost_usd is None:
                    totals["cost_unknown"] = True
                else:
                    totals["cost_usd"] = float(totals["cost_usd"]) + attempt.cost_usd

        # Judge calls produce no Attempt row — their usage lives in the Score's
        # judge_meta. Rebuilding from attempts alone would silently drop judge
        # spend from the run's cost, which is exactly what must stay visible.
        _add_judge_usage(session, item_ids, totals)
    return totals


def _add_judge_usage(session: Session, item_ids: list[int], totals: dict[str, Any]) -> None:
    """Fold judge token/cost usage (stored per Score) into a run's totals."""
    from gaugix.models.scores import Score

    rows = session.exec(
        select(Score).where(
            col(Score.run_item_id).in_(item_ids), col(Score.judge_meta_json).is_not(None)
        )
    ).all()

    # Only the latest version per (item, scorer) counts — earlier versions were
    # superseded by a re-score and their spend is already history.
    latest: dict[tuple[int, int], Score] = {}
    for row in rows:
        key = (row.run_item_id, row.scorer_index)
        current = latest.get(key)
        if current is None or row.version > current.version:
            latest[key] = row

    for row in latest.values():
        meta = row.judge_meta or {}
        usage = meta.get("usage")
        if not isinstance(usage, dict):
            continue
        totals["prompt_tokens"] = int(totals["prompt_tokens"]) + int(
            usage.get("prompt_tokens", 0) or 0
        )
        totals["completion_tokens"] = int(totals["completion_tokens"]) + int(
            usage.get("completion_tokens", 0) or 0
        )
        cost = usage.get("cost_usd")
        if cost is None:
            totals["cost_unknown"] = True
        else:
            totals["judge_cost_usd"] = float(totals.get("judge_cost_usd", 0.0)) + float(cost)
            totals["cost_usd"] = float(totals["cost_usd"]) + float(cost)


# -- scheduling ----------------------------------------------------------------


def schedulable_item_ids(session: Session, run_id: int, include_errors: bool = True) -> list[int]:
    """Items a start/resume should execute.

    Never `passed`/`failed` — those are finished work (PRD F3.5). `error` items are
    included by default so a resume retries what the provider dropped.
    """
    statuses = [str(ItemStatus.pending), str(ItemStatus.skipped)]
    if include_errors:
        statuses += [str(ItemStatus.error), str(ItemStatus.invoking), str(ItemStatus.scoring)]

    rows = session.exec(
        select(RunItem)
        .where(RunItem.run_id == run_id, col(RunItem.status).in_(statuses))
        .order_by(col(RunItem.executor_key), col(RunItem.position))
    ).all()
    return [r.id for r in rows if r.id is not None]


def retry_item(session: Session, run_id: int, item_id: int) -> int:
    """Reset exactly one item, leaving the rest of its lane alone.

    The narrow sibling of `rerun_from`: when one call hit a rate limit or a
    timeout, re-running the whole tail of the lane is both slower and more
    expensive than the problem warrants. Same supersede-don't-delete semantics,
    so the failed attempt stays in the ledger.
    """
    target = session.get(RunItem, item_id)
    if target is None or target.run_id != run_id:
        raise ValueError(f"item {item_id} is not part of run {run_id}")
    _reset_item(session, target)
    session.commit()
    return item_id


def _reset_item(session: Session, item: RunItem) -> None:
    """Send one item back to pending, keeping its history as superseded."""
    from gaugix.models.scores import Score

    attempts = session.exec(select(Attempt).where(Attempt.run_item_id == item.id)).all()
    for attempt in attempts:
        attempt.superseded = True
        session.add(attempt)

    # Scores stay as history too; the next scoring pass appends new versions.
    scores = session.exec(select(Score).where(Score.run_item_id == item.id)).all()
    for score in scores:
        session.add(score)

    item.status = str(ItemStatus.pending)
    item.verdict = None
    item.score_value = None
    item.needs_human = False
    item.error = None
    item.current_attempt_id = None
    item.touch()
    session.add(item)


def rerun_from(session: Session, run_id: int, item_id: int) -> list[int]:
    """Reset an item and everything after it *in the same executor lane*.

    Per ARCHITECTURE §5 and the draft requirement it answers ("don't rerun the
    whole set from the beginning after a bug"): current attempts are marked
    superseded rather than deleted, the items go back to `pending`, and the
    ordinary resume path re-executes them as new attempts. Other lanes are
    untouched, so a rerun in one executor cannot silently invalidate another's
    results.

    Returns the ids that were reset.
    """
    target = session.get(RunItem, item_id)
    if target is None or target.run_id != run_id:
        raise ValueError(f"item {item_id} is not part of run {run_id}")

    affected = session.exec(
        select(RunItem)
        .where(
            RunItem.run_id == run_id,
            RunItem.executor_key == target.executor_key,
            col(RunItem.position) >= target.position,
        )
        .order_by(col(RunItem.position))
    ).all()

    reset_ids: list[int] = []
    for item in affected:
        _reset_item(session, item)
        if item.id is not None:
            reset_ids.append(item.id)

    session.commit()
    return reset_ids


async def start_run(
    engine: Engine, run_id: int, include_errors: bool = True, settings: Settings | None = None
) -> RunnerHandle:
    """Schedule a run in the background. Raises if one is already active."""
    if registry.is_active(run_id):
        raise RuntimeError(f"run {run_id} is already running")

    with Session(engine) as session:
        item_ids = schedulable_item_ids(session, run_id, include_errors)

    cancel_event = asyncio.Event()
    runner = Runner(engine, run_id, cancel_event, settings)

    async def _drive() -> None:
        try:
            await runner.execute(item_ids)
        finally:
            registry.discard(run_id)

    task = asyncio.create_task(_drive(), name=f"gaugix-run-{run_id}")
    handle = RunnerHandle(run_id=run_id, task=task, cancel_event=cancel_event)
    registry.register(handle)
    return handle


async def cancel_run(engine: Engine, run_id: int) -> bool:
    """Graceful stop: signal, wait out the grace period, then cancel the task."""
    handle = registry.get(run_id)
    if handle is None:
        # Not running here — mark whatever is left as skipped so the run settles.
        with Session(engine) as session:
            run = session.get(Run, run_id)
            if run is None or run.is_terminal:
                return False
        runner = Runner(engine, run_id, asyncio.Event())
        runner._skip_unstarted()
        runner._finalise(RunStatus.canceled)
        return True

    handle.cancel_event.set()
    bus.emit(EventType.log, run_id, level="warn", message="cancel requested")
    try:
        await asyncio.wait_for(asyncio.shield(handle.task), timeout=CANCEL_GRACE_S)
    except TimeoutError:
        handle.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await handle.task
        Runner(engine, run_id, asyncio.Event())._finalise(RunStatus.canceled)
    return True
