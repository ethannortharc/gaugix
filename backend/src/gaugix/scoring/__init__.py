"""Scoring: deterministic assertions, local python, LLM judge, human review."""

from gaugix.scoring.aggregate import Aggregate, ScoredScorer, aggregate, normalize_value
from gaugix.scoring.assertions import ScoreResult, extract_json, run_assertion
from gaugix.scoring.rescore import RescoreReport, rescore_items
from gaugix.scoring.service import (
    BUILTIN_RUBRICS,
    recompute_item,
    resolve_rubric,
    score_item,
    submit_human_score,
)

__all__ = [
    "BUILTIN_RUBRICS",
    "Aggregate",
    "RescoreReport",
    "ScoreResult",
    "ScoredScorer",
    "aggregate",
    "extract_json",
    "normalize_value",
    "recompute_item",
    "rescore_items",
    "resolve_rubric",
    "run_assertion",
    "score_item",
    "submit_human_score",
]


def install_runner_hook() -> None:
    """Wire the scoring pass into the engine.

    The runner deliberately knows nothing about scoring at import time; this is
    the single call that connects the two, made once by the app factory.
    """
    from gaugix.engine.runner import set_score_hook
    from gaugix.scoring.judge_config import default_judge_executor

    async def hook(session, item, attempt, executor):  # type: ignore[no-untyped-def]
        return await score_item(
            session, item, attempt, executor, judge_executor=default_judge_executor(session)
        )

    set_score_hook(hook)
