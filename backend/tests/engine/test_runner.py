"""Runner: happy path, retry, cancel, interrupt/recovery, and totals.

All of it on FakeHarness failure injection — no network, fully deterministic.
"""

from __future__ import annotations

import asyncio

from sqlmodel import Session, col, select

from gaugix.domain import AttemptStatus, InvocationResult, ItemStatus, RunStatus, Usage
from gaugix.engine.events import Event, EventType, bus
from gaugix.engine.planner import PlanRequest, plan_run
from gaugix.engine.recovery import recover_interrupted_runs
from gaugix.engine.runner import (
    Runner,
    cancel_run,
    recompute_totals,
    registry,
    schedulable_item_ids,
    set_score_hook,
    start_run,
)
from gaugix.models.executors import HarnessProfile
from gaugix.models.runs import Attempt, Run, RunItem
from tests.engine.conftest import make_case, make_fake_executor, make_set


async def run_to_completion(engine, run_id: int, deadline_s: float = 10.0) -> Run:
    handle = await start_run(engine, run_id)
    await asyncio.wait_for(handle.task, timeout=deadline_s)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        session.refresh(run)
        return run


def items_of(engine, run_id: int) -> list[RunItem]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(RunItem).where(RunItem.run_id == run_id).order_by(col(RunItem.position))
            ).all()
        )


def plan(session: Session, set_id: int, executor_ids: list[int], **kwargs) -> int:
    planned = plan_run(session, PlanRequest(set_ids=[set_id], executor_ids=executor_ids, **kwargs))
    return planned.run.id or 0


# -- happy path ----------------------------------------------------------------


async def test_run_completes_and_every_item_reaches_a_terminal_state(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    run = await run_to_completion(engine, run_id)

    assert run.status == str(RunStatus.completed)
    items = items_of(engine, run_id)
    assert len(items) == 3
    assert all(i.status == str(ItemStatus.passed) for i in items)
    assert run.started_at is not None and run.finished_at is not None


async def test_each_item_gets_an_attempt_with_the_harness_output(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["scripted_id"]])
    await run_to_completion(engine, run_id)

    with Session(engine) as s:
        items = s.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
        outputs = {}
        for item in items:
            attempt = s.exec(select(Attempt).where(Attempt.run_item_id == item.id)).one()
            outputs[item.title] = attempt.output_text

    assert outputs["Alpha"] == "ALPHA-RESPONSE"
    assert outputs["Beta"] == "DEFAULT-RESPONSE"


async def test_unexpected_harness_exception_marks_one_item_without_aborting_siblings(
    engine, session, demo, monkeypatch
):
    import gaugix.engine.runner as runner_module

    class OneBrokenAdapter:
        async def invoke(self, case, _model, _ctx):
            if case.title == "Alpha":
                raise RuntimeError("sensitive provider internals")
            return InvocationResult(
                output_text="ok",
                messages=[{"role": "assistant", "content": "ok"}],
                usage=Usage(),
            )

    monkeypatch.setattr(runner_module, "get_harness", lambda _kind: OneBrokenAdapter())
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])

    run = await run_to_completion(engine, run_id)
    items = items_of(engine, run_id)

    assert run.status == str(RunStatus.completed)
    assert [item.status for item in items].count(str(ItemStatus.error)) == 1
    assert [item.status for item in items].count(str(ItemStatus.passed)) == 2
    failed = next(item for item in items if item.status == str(ItemStatus.error))
    assert failed.error == "unexpected harness error: RuntimeError"
    assert "sensitive provider internals" not in failed.error


async def test_two_executors_produce_independent_lanes(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"], demo["scripted_id"]])
    run = await run_to_completion(engine, run_id)

    assert run.status == str(RunStatus.completed)
    items = items_of(engine, run_id)
    assert len(items) == 6
    by_lane: dict[str, list[RunItem]] = {}
    for item in items:
        by_lane.setdefault(item.executor_key, []).append(item)
    assert set(by_lane) == {"echo @ fake", "scripted @ fake"}
    assert all(len(lane) == 3 for lane in by_lane.values())


async def test_totals_are_accurate_after_a_run(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    run = await run_to_completion(engine, run_id)

    totals = run.totals
    assert totals["items"] == 3
    assert totals["passed"] == 3
    assert totals["pending"] == 0
    assert totals["prompt_tokens"] > 0
    assert totals["completion_tokens"] > 0
    assert totals["cost_usd"] == 0.0, "the fake provider is free, and says so explicitly"
    assert totals["cost_unknown"] is False


async def test_serial_concurrency_still_completes(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]], concurrency=1)
    run = await run_to_completion(engine, run_id)
    assert run.status == str(RunStatus.completed)
    assert run.totals["passed"] == 3


async def test_live_totals_move_finished_items_out_of_scoring(engine, session):
    """The running UI must not wait for finalisation to show terminal counts."""
    from gaugix.scoring.service import score_item

    cases = [make_case(session, "First", "one"), make_case(session, "Second", "two")]
    eval_set = make_set(session, "Live totals", cases)
    executor = make_fake_executor(session, "live totals @ fake")
    session.commit()
    second_scored = asyncio.Event()
    release_second = asyncio.Event()
    calls = 0

    async def pausing_score_hook(session, item, attempt, executor_snapshot):
        nonlocal calls
        outcome = await score_item(session, item, attempt, executor_snapshot)
        calls += 1
        if calls == 2:
            second_scored.set()
            await release_second.wait()
        return outcome

    set_score_hook(pausing_score_hook)
    run_id = plan(session, eval_set.id or 0, [executor.id or 0], concurrency=1)
    handle = await start_run(engine, run_id)
    await asyncio.wait_for(second_scored.wait(), timeout=2)
    try:
        with Session(engine) as live:
            run = live.get(Run, run_id)
            assert run is not None
            assert run.totals["passed"] == 1
            assert run.totals["scoring"] == 1
            assert run.totals["pending"] == 0
    finally:
        release_second.set()
    await asyncio.wait_for(handle.task, timeout=2)


# -- retries -------------------------------------------------------------------


async def test_transient_failure_is_retried_and_then_succeeds(engine, session, demo):
    """`fail_first_n_invocations` makes the retry path deterministic."""
    flaky = make_fake_executor(session, "flaky @ fake", {"fail_first_n_invocations": 1})
    session.commit()

    run_id = plan(session, demo["set_id"], [flaky.id or 0])
    run = await run_to_completion(engine, run_id)

    assert run.status == str(RunStatus.completed)
    items = items_of(engine, run_id)
    assert all(i.status == str(ItemStatus.passed) for i in items)

    with Session(engine) as s:
        attempt = s.exec(select(Attempt).where(Attempt.run_item_id == items[0].id)).one()
    assert attempt.status == str(AttemptStatus.ok)
    assert attempt.retries == 1, "one retry was needed, and it is recorded"


async def test_persistent_failure_ends_as_error_after_the_retry_budget(engine, session, demo):
    broken = make_fake_executor(
        session, "broken @ fake", {"error_rate": 1.0, "error_message": "provider exploded"}
    )
    session.commit()

    run_id = plan(session, demo["set_id"], [broken.id or 0])
    run = await run_to_completion(engine, run_id)

    # Item-level errors are expected; the run itself still completed its work.
    assert run.status == str(RunStatus.completed)
    items = items_of(engine, run_id)
    assert all(i.status == str(ItemStatus.error) for i in items)
    assert all("provider exploded" in (i.error or "") for i in items)
    assert run.totals["error"] == 3


async def test_a_non_retryable_error_is_not_retried(engine, session, demo):
    hard = make_fake_executor(session, "hard @ fake", {"error_rate": 1.0, "error_retryable": False})
    session.commit()

    run_id = plan(session, demo["set_id"], [hard.id or 0])
    await run_to_completion(engine, run_id)

    with Session(engine) as s:
        attempts = s.exec(select(Attempt)).all()
    assert all(a.retries == 0 for a in attempts), "a permanent error must fail immediately"


async def test_one_failing_case_does_not_stop_the_others(engine, session, demo):
    targeted = make_fake_executor(session, "targeted @ fake", {"fail_if_contains": "beta"})
    session.commit()

    run_id = plan(session, demo["set_id"], [targeted.id or 0])
    run = await run_to_completion(engine, run_id)

    statuses = {i.title: i.status for i in items_of(engine, run_id)}
    assert statuses["Alpha"] == str(ItemStatus.passed)
    assert statuses["Beta"] == str(ItemStatus.error)
    assert statuses["Gamma"] == str(ItemStatus.passed)
    assert run.status == str(RunStatus.completed)


# -- cancel --------------------------------------------------------------------


async def test_cancel_marks_unstarted_items_skipped_and_the_run_canceled(engine, session):
    cases = [make_case(session, f"C{i}", f"input {i}") for i in range(8)]
    eval_set = make_set(session, "Slow set", cases)
    slow = make_fake_executor(session, "slow @ fake", {"latency_ms": 120})
    session.commit()

    run_id = plan(session, eval_set.id or 0, [slow.id or 0], concurrency=1)
    handle = await start_run(engine, run_id)
    await asyncio.sleep(0.15)
    await cancel_run(engine, run_id)
    await asyncio.wait_for(handle.task, timeout=10)

    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None
        assert run.status == str(RunStatus.canceled)

    statuses = [i.status for i in items_of(engine, run_id)]
    assert str(ItemStatus.skipped) in statuses, "unstarted work is skipped, not left pending"
    assert str(ItemStatus.pending) not in statuses, "a canceled run leaves nothing pending"


async def test_cancelling_a_finished_run_is_a_no_op(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    await run_to_completion(engine, run_id)

    changed = await cancel_run(engine, run_id)
    assert changed is False

    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None and run.status == str(RunStatus.completed)


# -- interruption & recovery ---------------------------------------------------


async def test_recovery_reclassifies_a_crashed_run(engine, session, demo):
    """Simulate a kill: a `running` run with items stuck mid-flight."""
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])

    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None
        run.status = str(RunStatus.running)
        s.add(run)
        items = s.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
        items[0].status = str(ItemStatus.passed)  # finished before the crash
        items[1].status = str(ItemStatus.invoking)  # in flight
        items[2].status = str(ItemStatus.scoring)  # in flight
        for item in items:
            s.add(item)
        s.commit()

    report = recover_interrupted_runs(engine)
    assert report.runs_interrupted == 1
    assert report.items_reclassified == 2

    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None and run.status == str(RunStatus.interrupted)
        items = s.exec(
            select(RunItem).where(RunItem.run_id == run_id).order_by(col(RunItem.position))
        ).all()
    assert items[0].status == str(ItemStatus.passed), "finished work is never touched"
    assert items[1].status == str(ItemStatus.error)
    assert items[1].error == "interrupted"
    assert items[2].status == str(ItemStatus.error)


async def test_recovery_is_idempotent(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None
        run.status = str(RunStatus.running)
        s.add(run)
        s.commit()

    first = recover_interrupted_runs(engine)
    second = recover_interrupted_runs(engine)
    assert first.runs_interrupted == 1
    assert second.runs_interrupted == 0


async def test_recovery_leaves_completed_runs_alone(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    await run_to_completion(engine, run_id)

    report = recover_interrupted_runs(engine)
    assert report.runs_interrupted == 0

    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None and run.status == str(RunStatus.completed)


# -- scheduling rules ----------------------------------------------------------


async def test_schedulable_never_includes_finished_work(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    with Session(engine) as s:
        items = s.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
        items[0].status = str(ItemStatus.passed)
        items[1].status = str(ItemStatus.failed)
        items[2].status = str(ItemStatus.error)
        for item in items:
            s.add(item)
        s.commit()

        with_errors = schedulable_item_ids(s, run_id, include_errors=True)
        without_errors = schedulable_item_ids(s, run_id, include_errors=False)

    assert with_errors == [items[2].id]
    assert without_errors == []


async def test_a_second_start_is_refused_while_a_run_is_active(engine, session):
    cases = [make_case(session, f"C{i}", f"input {i}") for i in range(6)]
    eval_set = make_set(session, "Slow", cases)
    slow = make_fake_executor(session, "slow2 @ fake", {"latency_ms": 80})
    session.commit()

    run_id = plan(session, eval_set.id or 0, [slow.id or 0], concurrency=1)
    handle = await start_run(engine, run_id)
    try:
        assert registry.is_active(run_id)
        try:
            await start_run(engine, run_id)
            raise AssertionError("a double start must be refused")
        except RuntimeError as exc:
            assert "already running" in str(exc)
    finally:
        await cancel_run(engine, run_id)
        await asyncio.wait_for(handle.task, timeout=10)


# -- events --------------------------------------------------------------------


async def test_the_ui_receives_item_and_run_events(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    queue = bus.subscribe(run_id)

    await run_to_completion(engine, run_id)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    bus.unsubscribe(run_id, queue)

    kinds = {e.type for e in events}
    assert EventType.item_status in kinds
    assert EventType.run_status in kinds
    assert EventType.usage_delta in kinds


async def test_event_sequence_numbers_are_monotonic(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    queue = bus.subscribe(run_id)
    await run_to_completion(engine, run_id)

    seqs = []
    while not queue.empty():
        seqs.append(queue.get_nowait().seq)
    bus.unsubscribe(run_id, queue)

    assert seqs == sorted(seqs), "the UI relies on seq to drop stale deltas"
    assert len(set(seqs)) == len(seqs)


async def test_a_full_subscriber_queue_never_blocks_the_run(engine, session, demo):
    """A browser tab that stops reading must not stall the engine."""
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    queue = bus.subscribe(run_id)
    for _ in range(queue.maxsize):
        queue.put_nowait(_make_filler(run_id))

    run = await run_to_completion(engine, run_id)
    bus.unsubscribe(run_id, queue)
    assert run.status == str(RunStatus.completed)


def _make_filler(run_id: int) -> Event:
    return Event(type=EventType.log, run_id=run_id, data={"message": "filler"})


# -- totals recomputation ------------------------------------------------------


async def test_recompute_totals_matches_the_live_counters(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"], demo["scripted_id"]])
    run = await run_to_completion(engine, run_id)

    with Session(engine) as s:
        recomputed = recompute_totals(s, run_id)

    for key in ("items", "passed", "failed", "error", "skipped", "prompt_tokens"):
        assert recomputed[key] == run.totals[key], f"{key} drifted"


async def test_unknown_cost_is_flagged_rather_than_counted_as_zero(engine, session, demo):
    """A None cost must set `cost_unknown`, not quietly add 0."""
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    await run_to_completion(engine, run_id)

    with Session(engine) as s:
        attempt = s.exec(select(Attempt)).first()
        assert attempt is not None
        attempt.cost_usd = None
        s.add(attempt)
        s.commit()
        totals = recompute_totals(s, run_id)

    assert totals["cost_unknown"] is True


# -- misconfiguration ----------------------------------------------------------


async def test_an_item_whose_executor_vanished_errors_cleanly(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    with Session(engine) as s:
        items = s.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
        items[0].executor_key = "ghost @ fake"
        s.add(items[0])
        s.commit()

    run = await run_to_completion(engine, run_id)
    statuses = {i.executor_key: i.status for i in items_of(engine, run_id)}
    assert statuses["ghost @ fake"] == str(ItemStatus.error)
    assert run.status == str(RunStatus.completed)


async def test_an_unknown_fake_mode_fails_the_item_not_the_run(engine, session, demo):
    with Session(engine) as s:
        harness = s.exec(
            select(HarnessProfile).where(HarnessProfile.name == "echo @ fake-harness")
        ).first()
        assert harness is not None
        harness.config = {"mode": "nonsense"}
        s.add(harness)
        s.commit()

    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    run = await run_to_completion(engine, run_id)

    assert run.status == str(RunStatus.completed)
    assert all(i.status == str(ItemStatus.error) for i in items_of(engine, run_id))


def test_runner_registry_forgets_finished_runs():
    assert registry.get(999) is None
    assert registry.is_active(999) is False


async def test_runner_uses_the_frozen_config_not_the_live_one(engine, session, demo):
    """Concurrency comes from the run's snapshot, so editing settings mid-run is safe."""
    run_id = plan(session, demo["set_id"], [demo["echo_id"]], concurrency=2)
    runner = Runner(engine, run_id, asyncio.Event())
    assert runner._run_config()["concurrency"] == 2


async def test_pass_rate_counters_do_not_treat_unscored_items_as_passes(engine, session, demo):
    """An item that ran fine with no scorers has no verdict — it must not inflate
    the pass rate (the totals track verdicts separately from statuses)."""
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    run = await run_to_completion(engine, run_id)

    assert run.totals["passed"] == 3, "all three finished"
    assert run.totals["scored"] == 0, "but none of them was judged"
    assert run.totals["verdict_passed"] == 0
    assert run.totals["unscored"] == 3


async def test_verdict_counters_follow_actual_verdicts(engine, session, demo):
    run_id = plan(session, demo["set_id"], [demo["echo_id"]])
    await run_to_completion(engine, run_id)

    with Session(engine) as s:
        items = s.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
        items[0].verdict = True
        items[1].verdict = False
        for item in items[:2]:
            s.add(item)
        s.commit()
        totals = recompute_totals(s, run_id)

    assert totals["scored"] == 2
    assert totals["verdict_passed"] == 1
    assert totals["unscored"] == 1


async def test_crash_then_resume_reexecutes_only_unfinished_work(engine, session, demo):
    """The M4 gate: simulate a kill mid-run, recover, resume, verify the ledger.

    Finished items keep their single attempt; the interrupted one and everything
    still pending get executed exactly once more; totals add up.
    """
    extra = [make_case(session, f"X{i}", f"extra {i}") for i in range(3)]
    eval_set = make_set(session, "Crash set", [*demo["cases"], *extra])
    executor = make_fake_executor(session, "crash @ fake")
    session.commit()

    run_id = plan(session, eval_set.id or 0, [executor.id or 0])

    # Freeze a plausible mid-flight state: two done, one in flight, three pending.
    with Session(engine) as s:
        run = s.get(Run, run_id)
        assert run is not None
        run.status = str(RunStatus.running)
        s.add(run)
        items = s.exec(
            select(RunItem).where(RunItem.run_id == run_id).order_by(col(RunItem.position))
        ).all()
        for done in items[:2]:
            done.status = str(ItemStatus.passed)
            done.verdict = True
            s.add(done)
            s.add(Attempt(run_item_id=done.id or 0, n=1, output_text="done before the crash"))
        # Crashed *during scoring*: the attempt row exists but never completed,
        # which is the case where recovery must mark it errored so resume appends
        # a new one rather than trusting a half-written result.
        items[2].status = str(ItemStatus.scoring)
        s.add(items[2])
        s.add(Attempt(run_item_id=items[2].id or 0, n=1, output_text="half-written"))
        s.commit()
        finished_ids = [i.id for i in items[:2]]
        interrupted_id = items[2].id

    report = recover_interrupted_runs(engine)
    assert report.runs_interrupted == 1

    with Session(engine) as s:
        stale = s.exec(select(Attempt).where(Attempt.run_item_id == interrupted_id)).one()
        assert stale.status == str(AttemptStatus.error)
        assert stale.error == "interrupted", "the half-written attempt is not a result"
        schedulable = schedulable_item_ids(s, run_id, include_errors=True)
    assert len(schedulable) == 4, "the interrupted item plus the three pending ones"
    assert all(i not in schedulable for i in finished_ids), "finished work is never redone"
    assert interrupted_id in schedulable

    run = await run_to_completion(engine, run_id)
    assert run.status == str(RunStatus.completed)

    with Session(engine) as s:
        items = s.exec(
            select(RunItem).where(RunItem.run_id == run_id).order_by(col(RunItem.position))
        ).all()
        assert all(i.status == str(ItemStatus.passed) for i in items)

        for item in items:
            attempts = s.exec(select(Attempt).where(Attempt.run_item_id == item.id)).all()
            expected = 1 if item.id in finished_ids else (2 if item.id == interrupted_id else 1)
            assert len(attempts) == expected, f"item {item.id} ran the wrong number of times"

    assert run.totals["items"] == 6
    assert run.totals["passed"] == 6
    assert run.totals["pending"] == 0
    assert run.totals["error"] == 0
