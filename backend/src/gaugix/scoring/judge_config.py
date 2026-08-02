"""Which executor grades, when a scorer does not name one.

Resolution order (PRD F4.1): the scorer's own `judge_executor`, else the Settings
default, else the executor being evaluated. That last fallback keeps a run working
on a fresh install — self-judging is a real bias (the learning center covers it),
but a broken run teaches nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from gaugix.domain import ExecutorSnapshot
from gaugix.models.executors import Executor, HarnessProfile, ModelProfile


@dataclass(frozen=True, slots=True)
class JudgeResolution:
    """The resolved judge and whether the scorer explicitly named a bad one."""

    executor: ExecutorSnapshot | None
    explicit: bool = False
    error: str | None = None


def executor_snapshot(session: Session, executor_id: int) -> ExecutorSnapshot | None:
    executor = session.get(Executor, executor_id)
    if executor is None:
        return None
    model = session.get(ModelProfile, executor.model_profile_id)
    harness = session.get(HarnessProfile, executor.harness_profile_id)
    if model is None or harness is None:
        return None
    return executor.to_snapshot(model, harness)


def default_judge_executor(session: Session) -> ExecutorSnapshot | None:
    """The Settings-configured judge, or None to fall back to the run's executor."""
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, read_setting

    executor_id = read_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None)
    if executor_id is None:
        return None
    try:
        return executor_snapshot(session, int(executor_id))
    except (TypeError, ValueError):
        return None


def resolve_judge_executor(session: Session, params: dict[str, object]) -> JudgeResolution:
    """Resolve a scorer judge without hiding a broken explicit reference.

    An omitted judge intentionally falls through to Settings (and eventually
    self-judging). An explicit id/name is a user choice: if it no longer exists,
    silently substituting Settings makes preflight and the actual grader lie
    about the experiment.
    """
    named = params.get("judge_executor")
    if named is None:
        return JudgeResolution(default_judge_executor(session))

    if isinstance(named, bool):
        return JudgeResolution(None, explicit=True, error="`judge_executor` must be an id or name")
    if isinstance(named, int):
        snapshot = executor_snapshot(session, named) if named > 0 else None
        if snapshot is not None:
            return JudgeResolution(snapshot, explicit=True)
        return JudgeResolution(
            None, explicit=True, error=f"`judge_executor` id {named} does not exist"
        )
    if isinstance(named, str):
        key = named.strip()
        if key:
            executor = session.exec(select(Executor).where(Executor.name == key)).first()
            if executor is not None and executor.id is not None:
                snapshot = executor_snapshot(session, executor.id)
                if snapshot is not None:
                    return JudgeResolution(snapshot, explicit=True)
            return JudgeResolution(
                None, explicit=True, error=f"`judge_executor` {key!r} does not exist"
            )
    return JudgeResolution(None, explicit=True, error="`judge_executor` must be an id or name")


def judge_executor_for(session: Session, params: dict[str, object]) -> ExecutorSnapshot | None:
    """Compatibility wrapper for callers that only need the resolved snapshot."""
    return resolve_judge_executor(session, params).executor
