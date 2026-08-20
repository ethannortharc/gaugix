"""Planner: expansion counts, lane ordering, and snapshot immutability.

The snapshot tests are the ones that matter — they are what makes a run
reproducible and a comparison fair (ARCHITECTURE §3).
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, col, select

from gaugix.domain import ItemStatus, RunStatus
from gaugix.engine.planner import PlanRequest, plan_run, preview, resolve_scoring, suggest_name
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.cases import EvalCase, EvalSet
from gaugix.models.executors import HarnessProfile
from gaugix.models.runs import Attempt, RunItem
from tests.engine.conftest import make_case, make_fake_executor, make_set


def test_expansion_is_cases_times_executors(session: Session, demo):
    planned = plan_run(
        session,
        PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"], demo["scripted_id"]]),
    )
    assert planned.item_count == 6  # 3 cases × 2 executors

    items = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).all()
    assert len(items) == 6
    assert {i.executor_key for i in items} == {"echo @ fake", "scripted @ fake"}


def test_each_executor_gets_its_own_lane_positions(session: Session, demo):
    planned = plan_run(
        session,
        PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"], demo["scripted_id"]]),
    )
    items = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).all()
    for key in ("echo @ fake", "scripted @ fake"):
        lane = sorted((i for i in items if i.executor_key == key), key=lambda i: i.position)
        assert [i.position for i in lane] == [0, 1, 2]
        assert [i.title for i in lane] == ["Alpha", "Beta", "Gamma"]


def test_multiple_sets_are_concatenated_in_order(session: Session, demo):
    extra_case = make_case(session, "Delta", "delta input")
    second = make_set(session, "Second set", [extra_case])
    session.commit()

    planned = plan_run(
        session,
        PlanRequest(set_ids=[demo["set_id"], second.id or 0], executor_ids=[demo["echo_id"]]),
    )
    assert planned.item_count == 4

    items = session.exec(
        select(RunItem).where(RunItem.run_id == planned.run.id).order_by(col(RunItem.position))
    ).all()
    assert [i.title for i in items] == ["Alpha", "Beta", "Gamma", "Delta"]


def test_run_starts_pending_so_a_crash_before_launch_is_resumable(session: Session, demo):
    planned = plan_run(
        session, PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"]])
    )
    assert planned.run.status == str(RunStatus.pending)
    items = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).all()
    assert all(i.status == str(ItemStatus.pending) for i in items)


def test_trashed_cases_are_never_planned_into_a_run(session: Session, demo):
    from gaugix.models.base import utcnow

    case = session.get(EvalCase, demo["case_ids"][1])
    assert case is not None
    case.deleted_at = utcnow()
    session.add(case)
    session.commit()

    planned = plan_run(
        session, PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"]])
    )
    assert planned.item_count == 2
    items = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).all()
    assert "Beta" not in {i.title for i in items}


# -- snapshot rules ------------------------------------------------------------


def test_editing_a_case_after_planning_does_not_change_the_run(session: Session, demo):
    planned = plan_run(
        session, PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"]])
    )

    case = session.get(EvalCase, demo["case_ids"][0])
    assert case is not None
    case.title = "Alpha RENAMED"
    from gaugix.domain import Message, Role

    case.input = [Message(role=Role.user, content="completely different")]
    session.add(case)
    session.commit()

    item = session.exec(
        select(RunItem).where(RunItem.run_id == planned.run.id, RunItem.position == 0)
    ).one()
    snapshot = item.case_snapshot
    assert snapshot.title == "Alpha", "the run must remember what it actually ran"
    assert snapshot.input[0].content == "alpha input"


def test_editing_an_executor_after_planning_does_not_change_the_run(session: Session, demo):
    planned = plan_run(
        session, PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"]])
    )
    frozen = planned.run.executors[0]
    assert frozen.key == "echo @ fake"

    from gaugix.models.executors import ModelProfile

    model = session.get(ModelProfile, frozen.model.model_profile_id or 0)
    assert model is not None
    model.params = {"temperature": 1.9}
    session.add(model)
    session.commit()

    session.refresh(planned.run)
    assert planned.run.executors[0].model.params == {}


def test_resolved_scoring_is_frozen_into_the_item(session: Session):
    case_with = make_case(
        session, "Own scorers", "x", [{"type": "contains", "params": {"text": "own"}}]
    )
    case_without = make_case(session, "Inherits", "y")
    eval_set = make_set(
        session,
        "Scored set",
        [case_with, case_without],
        default_scoring=[{"type": "contains", "params": {"text": "default"}}],
    )
    executor = make_fake_executor(session, "e1 @ fake")
    session.commit()

    planned = plan_run(
        session, PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[executor.id or 0])
    )
    items = session.exec(
        select(RunItem).where(RunItem.run_id == planned.run.id).order_by(col(RunItem.position))
    ).all()

    assert items[0].case_snapshot.scoring[0].params["text"] == "own"
    assert items[1].case_snapshot.scoring[0].params["text"] == "default", "inherits set default"


def test_changing_the_set_default_after_planning_does_not_change_the_run(session: Session):
    case = make_case(session, "Inherits", "y")
    eval_set = make_set(
        session,
        "Scored set",
        [case],
        default_scoring=[{"type": "contains", "params": {"text": "original"}}],
    )
    executor = make_fake_executor(session, "e1 @ fake")
    session.commit()

    planned = plan_run(
        session, PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[executor.id or 0])
    )

    from gaugix.domain import ScorerSpec

    stored = session.get(EvalSet, eval_set.id or 0)
    assert stored is not None
    stored.default_scoring = [
        ScorerSpec.model_validate({"type": "contains", "params": {"text": "changed"}})
    ]
    session.add(stored)
    session.commit()

    item = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).one()
    assert item.case_snapshot.scoring[0].params["text"] == "original"


async def test_the_plan_time_judge_is_frozen_and_used_after_settings_change(session: Session):
    """Changing the measurement instrument mid-run must not split the cohort."""
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, write_setting
    from gaugix.scoring.service import score_item

    case = make_case(
        session,
        "Judged",
        "question",
        [
            {
                "type": "llm_judge",
                "params": {"rubric": "Is it correct?", "scale": "1-5"},
                "required": True,
            }
        ],
    )
    eval_set = make_set(session, "Judged set", [case])
    subject = make_fake_executor(session, "subject @ fake")
    judge = make_fake_executor(
        session,
        "judge @ fake",
        {"mode": "script", "default_response": '{"score":5,"pass":true,"rationale":"old"}'},
    )
    write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, judge.id)
    session.commit()

    planned = plan_run(
        session,
        PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[subject.id or 0]),
    )
    spec = case.scoring[0]
    frozen = planned.run.config["judge_executors"][spec.config_hash()]["executor"]
    assert frozen["key"] == "judge @ fake"
    assert frozen["harness"]["config"]["default_response"].endswith('"old"}')

    live_harness = session.get(HarnessProfile, judge.harness_profile_id)
    assert live_harness is not None
    live_harness.config = {
        "mode": "script",
        "default_response": '{"score":1,"pass":false,"rationale":"new"}',
    }
    write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None)
    session.add(live_harness)
    session.commit()

    item = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).one()
    attempt = Attempt(run_item_id=item.id or 0, output_text="subject answer")
    session.add(attempt)
    session.commit()
    outcome = await score_item(session, item, attempt, planned.run.executors[0])

    assert outcome.verdict is True, "the changed live judge would have failed this item"


async def test_scoring_leaves_the_live_terminal_transition_to_the_runner(session: Session):
    """Incremental run totals depend on the runner seeing scoring -> terminal."""
    from gaugix.domain import ItemStatus
    from gaugix.scoring.service import score_item

    case = make_case(
        session,
        "Scored",
        "question",
        [{"type": "contains", "params": {"text": "answer"}, "required": True}],
    )
    eval_set = make_set(session, "Scored set", [case])
    subject = make_fake_executor(session, "subject @ fake")
    session.commit()
    planned = plan_run(
        session,
        PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[subject.id or 0]),
    )
    item = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).one()
    item.status = str(ItemStatus.scoring)
    attempt = Attempt(run_item_id=item.id or 0, output_text="answer")
    session.add(item)
    session.add(attempt)
    session.commit()

    outcome = await score_item(session, item, attempt, planned.run.executors[0])
    session.refresh(item)

    assert outcome.verdict is True
    assert item.status == str(ItemStatus.scoring)


async def test_out_of_band_scoring_can_finalize_an_orphaned_scoring_item(session: Session):
    """Re-score/human paths have no live runner to perform the terminal transition."""
    from gaugix.domain import ItemStatus
    from gaugix.scoring.service import score_item

    case = make_case(
        session,
        "Scored out of band",
        "question",
        [{"type": "contains", "params": {"text": "answer"}, "required": True}],
    )
    eval_set = make_set(session, "Out-of-band set", [case])
    subject = make_fake_executor(session, "subject @ fake")
    session.commit()
    planned = plan_run(
        session,
        PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[subject.id or 0]),
    )
    item = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).one()
    item.status = str(ItemStatus.scoring)
    attempt = Attempt(run_item_id=item.id or 0, output_text="answer")
    session.add(item)
    session.add(attempt)
    session.commit()

    outcome = await score_item(
        session,
        item,
        attempt,
        planned.run.executors[0],
        finalize_status=True,
    )
    session.refresh(item)

    assert outcome.verdict is True
    assert item.status == str(ItemStatus.passed)


async def test_plan_time_self_judging_stays_self_judging_if_a_default_is_added(session: Session):
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, write_setting
    from gaugix.scoring.judge_config import default_judge_executor
    from gaugix.scoring.service import score_item

    case = make_case(
        session,
        "Self judged",
        "question",
        [{"type": "llm_judge", "params": {"rubric": "Good?"}, "required": True}],
    )
    eval_set = make_set(session, "Self judged set", [case])
    subject = make_fake_executor(
        session,
        "subject @ fake",
        {"mode": "script", "default_response": '{"score":5,"pass":true,"rationale":"self"}'},
    )
    session.commit()

    planned = plan_run(
        session,
        PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[subject.id or 0]),
    )
    assert planned.run.config["judge_executors"][case.scoring[0].config_hash()] == {"mode": "self"}

    later_default = make_fake_executor(
        session,
        "later default @ fake",
        {"mode": "script", "default_response": '{"score":1,"pass":false,"rationale":"new"}'},
    )
    write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, later_default.id)
    session.commit()

    item = session.exec(select(RunItem).where(RunItem.run_id == planned.run.id)).one()
    attempt = Attempt(run_item_id=item.id or 0, output_text="subject answer")
    session.add(attempt)
    session.commit()
    outcome = await score_item(
        session,
        item,
        attempt,
        planned.run.executors[0],
        judge_executor=default_judge_executor(session),
    )

    assert outcome.verdict is True, "the later default would have failed this item"


def test_an_explicit_missing_judge_never_falls_through_to_settings(session: Session):
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, write_setting
    from gaugix.scoring.judge_config import resolve_judge_executor

    fallback = make_fake_executor(session, "fallback @ fake")
    write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, fallback.id)
    session.commit()

    resolution = resolve_judge_executor(session, {"judge_executor": "missing @ fake"})

    assert resolution.executor is None
    assert resolution.explicit is True
    assert "does not exist" in (resolution.error or "")


def test_identical_judge_configs_are_resolved_only_once_at_plan_time(session: Session, monkeypatch):
    from gaugix.scoring.judge_config import resolve_judge_executor as original

    scoring = [{"type": "llm_judge", "params": {"rubric": "Good?"}, "required": True}]
    cases = [make_case(session, f"Case {index}", "q", scoring) for index in range(3)]
    eval_set = make_set(session, "Repeated judge", cases)
    subject = make_fake_executor(session, "subject @ fake")
    session.commit()

    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr("gaugix.engine.planner.resolve_judge_executor", counted)
    plan_run(
        session,
        PlanRequest(set_ids=[eval_set.id or 0], executor_ids=[subject.id or 0]),
    )

    assert calls == 1


def test_resolve_scoring_prefers_the_cases_own_config(session: Session):
    case = make_case(session, "c", "x", [{"type": "regex", "params": {"pattern": "^x"}}])
    eval_set = make_set(
        session, "s", [case], default_scoring=[{"type": "contains", "params": {"text": "d"}}]
    )
    session.commit()
    resolved = resolve_scoring(case, eval_set)
    assert len(resolved) == 1
    assert resolved[0].type == "regex"


# -- validation ----------------------------------------------------------------


def test_planning_with_no_sets_is_rejected(session: Session, demo):
    with pytest.raises(ValidationError, match="at least one eval set"):
        plan_run(session, PlanRequest(set_ids=[], executor_ids=[demo["echo_id"]]))


def test_planning_with_no_executors_is_rejected(session: Session, demo):
    with pytest.raises(ValidationError, match="at least one executor"):
        plan_run(session, PlanRequest(set_ids=[demo["set_id"]], executor_ids=[]))


def test_planning_an_empty_set_is_rejected(session: Session, demo):
    empty = make_set(session, "Empty", [])
    session.commit()
    with pytest.raises(ValidationError, match="no cases"):
        plan_run(session, PlanRequest(set_ids=[empty.id or 0], executor_ids=[demo["echo_id"]]))


def test_planning_with_an_unknown_set_is_a_404(session: Session, demo):
    with pytest.raises(NotFoundError):
        plan_run(session, PlanRequest(set_ids=[999], executor_ids=[demo["echo_id"]]))


def test_duplicate_executors_are_rejected(session: Session, demo):
    with pytest.raises(ValidationError, match="distinct"):
        plan_run(
            session,
            PlanRequest(set_ids=[demo["set_id"]], executor_ids=[demo["echo_id"], demo["echo_id"]]),
        )


# -- preview & naming ----------------------------------------------------------


def test_preview_counts_without_writing_anything(session: Session, demo):
    data = preview(session, [demo["set_id"]], [demo["echo_id"], demo["scripted_id"]])
    assert data["case_count"] == 3
    assert data["executor_count"] == 2
    assert data["item_count"] == 6
    assert session.exec(select(RunItem)).all() == []


def test_suggested_names_read_well():
    assert suggest_name(["Guardrails"], ["haiku @ direct"]) == "Guardrails × haiku @ direct"
    assert suggest_name(["A", "B"], ["x"]) == "2 sets × x"
    assert suggest_name(["A"], ["x", "y"]) == "A × 2 executors"


def test_run_config_freezes_concurrency_and_auto_score(session: Session, demo):
    planned = plan_run(
        session,
        PlanRequest(
            set_ids=[demo["set_id"]],
            executor_ids=[demo["echo_id"]],
            concurrency=7,
            auto_score=False,
        ),
    )
    assert planned.run.config["concurrency"] == 7
    assert planned.run.config["auto_score"] is False
