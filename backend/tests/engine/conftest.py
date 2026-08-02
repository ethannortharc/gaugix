"""Fixtures for engine tests: a set of cases plus fake executors.

Everything runs on FakeHarness, so these tests need no network and are fully
deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import Session

from gaugix.domain import HarnessKind, Message, Provider, Role, ScorerSpec
from gaugix.models.cases import EvalCase, EvalSet, SetMembership
from gaugix.models.executors import Executor, HarnessProfile, ModelProfile


def make_case(session: Session, title: str, content: str, scoring: list[dict] | None = None):
    case = EvalCase(title=title)
    case.input = [Message(role=Role.user, content=content)]
    case.scoring = [ScorerSpec.model_validate(s) for s in (scoring or [])]
    session.add(case)
    session.flush()
    return case


def make_set(session: Session, name: str, cases: list[EvalCase], default_scoring=None):
    eval_set = EvalSet(name=name)
    if default_scoring:
        eval_set.default_scoring = [ScorerSpec.model_validate(s) for s in default_scoring]
    session.add(eval_set)
    session.flush()
    for position, case in enumerate(cases):
        session.add(SetMembership(set_id=eval_set.id or 0, case_id=case.id or 0, position=position))
    session.flush()
    return eval_set


def make_fake_executor(
    session: Session, name: str, harness_config: dict[str, Any] | None = None
) -> Executor:
    """A fake-provider executor with its own harness profile."""
    model = ModelProfile(name=f"{name}-model", provider=str(Provider.fake), model_id=name)
    session.add(model)
    harness = HarnessProfile(name=f"{name}-harness", kind=str(HarnessKind.fake))
    harness.config = harness_config or {}
    session.add(harness)
    session.flush()

    executor = Executor(
        name=name,
        model_profile_id=model.id or 0,
        harness_profile_id=harness.id or 0,
    )
    session.add(executor)
    session.flush()
    return executor


@pytest.fixture
def demo(session: Session):
    """Three cases in one set, plus two fake executors (echo and scripted)."""
    cases = [
        make_case(session, "Alpha", "alpha input"),
        make_case(session, "Beta", "beta input"),
        make_case(session, "Gamma", "gamma input"),
    ]
    eval_set = make_set(session, "Demo set", cases)
    echo = make_fake_executor(session, "echo @ fake")
    scripted = make_fake_executor(
        session,
        "scripted @ fake",
        {
            "mode": "script",
            "script": [{"match": "alpha", "response": "ALPHA-RESPONSE"}],
            "default_response": "DEFAULT-RESPONSE",
        },
    )
    session.commit()
    return {
        "set": eval_set,
        "set_id": eval_set.id,
        "cases": cases,
        "case_ids": [c.id for c in cases],
        "echo": echo,
        "echo_id": echo.id,
        "scripted": scripted,
        "scripted_id": scripted.id,
    }


@pytest.fixture(autouse=True)
def reset_engine_state():
    """Clear the runner registry and event bus between tests."""
    from gaugix.engine.events import bus
    from gaugix.engine.runner import registry, set_score_hook

    bus.reset()
    yield
    bus.reset()
    set_score_hook(None)
    for run_id in registry.active_ids():
        registry.discard(run_id)
