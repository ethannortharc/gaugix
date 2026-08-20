"""Build task-aware summaries from frozen runs and their current attempts."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from sqlmodel import Session, col, select

from gaugix.domain import EvaluationProfile, EvaluationValueSource
from gaugix.errors import NotFoundError
from gaugix.evaluation.metrics import Observation, summarize
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.schemas.evaluation import EvaluationSliceRead, RunEvaluationRead


def summarize_run(
    session: Session,
    run_id: int,
    *,
    set_id: int | None = None,
    executor_key: str | None = None,
    node_id: int | None = None,
) -> RunEvaluationRead:
    run = session.get(Run, run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} does not exist")

    statement = select(RunItem).where(RunItem.run_id == run_id)
    if set_id is not None:
        statement = statement.where(RunItem.set_id == set_id)
    if executor_key is not None:
        statement = statement.where(RunItem.executor_key == executor_key)
    items = list(
        session.exec(
            statement.order_by(
                col(RunItem.set_name),
                col(RunItem.executor_key),
                col(RunItem.position),
            )
        ).all()
    )
    if node_id is not None:
        # A branch summary includes all descendants. Ancestry is read from the
        # run snapshot rather than the live tree, so later moves cannot restate
        # a historical result.
        items = [item for item in items if node_id in item.node_path_ids]

    attempts = _current_attempts(session, run_id)
    grouped: dict[tuple[int | None, str, str], list[Observation]] = defaultdict(list)
    profiles = _frozen_profiles(run)
    paths: dict[tuple[int | None, str, str], list[str]] = {}

    for item in items:
        profile = profiles.get(item.set_id, EvaluationProfile.standard())
        attempt = attempts.get(item.id or 0)
        output = _output_object(attempt.output_text if attempt else "")
        key = (item.set_id, item.set_name, item.executor_key)
        if node_id is not None:
            path = _selected_node_path(item, node_id)
            if path:
                paths[key] = path
        grouped[key].append(
            Observation(
                item_id=item.id or 0,
                status=item.status,
                verdict=item.verdict,
                truth=_read(profile.truth, item, output),
                prediction=_read(profile.prediction, item, output),
                score=_read_score(profile, item, output),
                truth_category=_read(profile.category_truth, item, output),
                predicted_category=_read(profile.category_prediction, item, output),
                latency_ms=attempt.latency_ms if attempt else None,
            )
        )

    slices = []
    for (current_set_id, set_name, current_executor), observations in grouped.items():
        profile = profiles.get(current_set_id, EvaluationProfile.standard())
        result = summarize(profile, observations)
        slices.append(
            EvaluationSliceRead(
                set_id=current_set_id,
                set_name=set_name,
                executor_key=current_executor,
                node_id=node_id,
                node_path=paths.get((current_set_id, set_name, current_executor), []),
                profile=profile,
                coverage=result.coverage,
                metrics=result.metrics,
                confusion=result.confusion,
                categories=result.categories or [],
                threshold_curve=result.threshold_curve or [],
            )
        )
    return RunEvaluationRead(run_id=run_id, slices=slices)


def _current_attempts(session: Session, run_id: int) -> dict[int, Attempt]:
    rows = session.exec(
        select(Attempt)
        .join(RunItem, col(RunItem.id) == col(Attempt.run_item_id))
        .where(RunItem.run_id == run_id, col(Attempt.superseded).is_(False))
        .order_by(col(Attempt.run_item_id), col(Attempt.n))
    ).all()
    current: dict[int, Attempt] = {}
    for attempt in rows:
        current[attempt.run_item_id] = attempt
    return current


def _frozen_profiles(run: Run) -> dict[int | None, EvaluationProfile]:
    profiles: dict[int | None, EvaluationProfile] = {}
    raw_sets = run.config.get("sets", [])
    for raw in raw_sets if isinstance(raw_sets, list) else []:
        if not isinstance(raw, dict):
            continue
        raw_id = raw.get("id", raw.get("set_id"))
        current_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        profile = raw.get("evaluation_profile")
        if not isinstance(profile, dict):
            profiles[current_id] = EvaluationProfile.standard()
            continue
        try:
            profiles[current_id] = EvaluationProfile.model_validate(profile)
        except Exception:
            profiles[current_id] = EvaluationProfile.standard()
    return profiles


def _output_object(output: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read(
    source: EvaluationValueSource | None,
    item: RunItem,
    output: dict[str, Any],
) -> str | None:
    if source is None:
        return None
    if source.source == "reference":
        return item.case_snapshot.reference
    if source.source == "tag":
        if not source.key:
            return None
        prefix = f"{source.key}:"
        return next(
            (tag[len(prefix) :] for tag in item.case_snapshot.tags if tag.startswith(prefix)),
            None,
        )
    if source.source == "output_json":
        value = _json_path(output, source.key)
        if value is None or isinstance(value, dict | list):
            return None
        return str(value)
    return None


def _read_score(
    profile: EvaluationProfile,
    item: RunItem,
    output: dict[str, Any],
) -> float | None:
    raw = _read(profile.score, item, output)
    if raw is None:
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(score):
        return None
    if profile.score_scale == "0-100":
        score /= 100.0
    return min(1.0, max(0.0, score))


def _json_path(value: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _selected_node_path(item: RunItem, node_id: int) -> list[str]:
    try:
        index = item.node_path_ids.index(node_id)
    except ValueError:
        return []
    path = item.node_path
    if index < len(path):
        return path[: index + 1]
    return []
