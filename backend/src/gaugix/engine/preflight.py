"""What is wrong with this run, before it costs anything (PRD F3.1).

Everything checked here is knowable without calling a model: a regex that will
not compile, a judge scorer with no rubric, a missing API key, a case that will
come back unscored, a model whose price nobody knows. Each of those turns into a
failed or meaningless item *after* the tokens are spent, which is the worst
moment to find out.

Findings have three severities and the distinction is the point:

* **blocker** — the run cannot produce a usable result. The builder refuses.
* **warning** — the run will work and the result will be less than it looks.
  Unscored cases and self-judging live here.
* **note** — worth knowing, not worth stopping for.

Nothing here writes, and nothing here calls out. `POST /runs/preflight` is safe
to run on every keystroke of the builder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import jsonschema
from sqlmodel import Session, col, select

from gaugix.config import credential_environment
from gaugix.domain import HarnessKind, Pricing, Provider, ScorerSpec, ScorerType
from gaugix.engine.planner import resolve_scoring
from gaugix.models.cases import EvalCase, EvalSet, SetMembership
from gaugix.models.executors import Executor, HarnessProfile, ModelProfile
from gaugix.scoring.aggregate import NAMED_SCALES, scale_bounds
from gaugix.scoring.judge import class_config, threshold_value
from gaugix.scoring.judge_config import resolve_judge_executor

BLOCKER = "blocker"
WARNING = "warning"
NOTE = "note"

#: Coarse per-item guess used for the cost estimate. Stated in the response so
#: nobody mistakes it for a quote.
ASSUMED_PROMPT_TOKENS = 400
ASSUMED_COMPLETION_TOKENS = 400
#: A judge call re-sends the case, the answer and the rubric, and writes a short
#: verdict. Bigger in, much smaller out — a judged run is not "twice the cost".
ASSUMED_JUDGE_PROMPT_TOKENS = 900
ASSUMED_JUDGE_COMPLETION_TOKENS = 150


@dataclass(slots=True)
class Finding:
    severity: str
    code: str
    message: str
    detail: str | None = None
    #: How many cases/executors this affects, when that is meaningful.
    count: int = 0


@dataclass(slots=True)
class Preflight:
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)
    case_count: int = 0
    executor_count: int = 0
    item_count: int = 0
    estimated_cost_usd: float | None = None
    cost_assumptions: str = ""
    #: Model calls spent on judging, included in `estimated_cost_usd`. Reported
    #: separately because it is the half people forget: a 4,326-case set judged
    #: 0/1 costs two calls per item, not one.
    judge_call_count: int = 0
    estimated_judge_cost_usd: float | None = None
    #: True when a scorer in this run executes model-written code on this host.
    #: The API refuses to create the run until the caller acknowledges it.
    requires_code_execution: bool = False
    #: Sets whose cases carry a code-executing scorer, for the confirmation text.
    code_execution_sets: list[str] = field(default_factory=list)


def preflight(
    session: Session,
    set_ids: list[int],
    executor_ids: list[int],
    case_ids: list[int] | None = None,
    *,
    auto_score: bool = True,
) -> Preflight:
    """Everything checkable about a planned run, without planning it."""
    result = Preflight()
    if not set_ids or not executor_ids:
        result.ok = False
        result.findings.append(
            Finding(BLOCKER, "empty_selection", "Pick at least one set and one executor.")
        )
        return result

    sets = _live_sets(session, set_ids)
    cases_by_set = {s.id: _cases_in_set(session, s.id or 0, case_ids) for s in sets}
    executors = _executors(session, executor_ids)

    result.case_count = sum(len(v) for v in cases_by_set.values())
    result.executor_count = len(executors)
    result.item_count = result.case_count * result.executor_count

    if result.case_count == 0:
        result.findings.append(
            Finding(
                BLOCKER,
                "no_cases",
                "None of the chosen cases are in the chosen sets."
                if case_ids is not None
                else "The chosen sets contain no cases to run.",
            )
        )

    _check_subset(session, result, sets, cases_by_set, case_ids)
    _check_credentials(result, executors)
    _check_executor_compatibility(result, sets, cases_by_set, executors)
    judge_specs = _check_scorers(session, result, sets, cases_by_set, executors, auto_score)
    _check_duplicates(result, sets, cases_by_set)
    _check_pricing(result, executors)
    _estimate(session, result, executors, judge_specs if auto_score else [])

    result.ok = not any(f.severity == BLOCKER for f in result.findings)
    return result


# -- loading -------------------------------------------------------------------


def _live_sets(session: Session, set_ids: list[int]) -> list[EvalSet]:
    rows = session.exec(
        select(EvalSet).where(col(EvalSet.id).in_(set_ids), col(EvalSet.deleted_at).is_(None))
    ).all()
    return sorted(rows, key=lambda s: set_ids.index(s.id) if s.id in set_ids else 0)


def _cases_in_set(
    session: Session, set_id: int, case_ids: list[int] | None = None
) -> list[EvalCase]:
    statement = (
        select(EvalCase)
        .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
        .where(SetMembership.set_id == set_id, col(EvalCase.deleted_at).is_(None))
    )
    if case_ids is not None:
        if not case_ids:
            return []
        statement = statement.where(col(EvalCase.id).in_(case_ids))
    return list(session.exec(statement.order_by(col(SetMembership.position))).all())


@dataclass(slots=True)
class _ExecutorInfo:
    name: str
    model: ModelProfile
    harness: HarnessProfile


def _executors(session: Session, executor_ids: list[int]) -> list[_ExecutorInfo]:
    """Each chosen executor with its model. Missing rows are skipped, not fatal:
    the run builder rejects them, and preflight's job is to describe.
    """
    out: list[_ExecutorInfo] = []
    for executor_id in executor_ids:
        executor = session.get(Executor, executor_id)
        if executor is None:
            continue
        model = session.get(ModelProfile, executor.model_profile_id)
        harness = session.get(HarnessProfile, executor.harness_profile_id)
        if model is not None and harness is not None:
            out.append(_ExecutorInfo(name=executor.name, model=model, harness=harness))
    return out


# -- checks --------------------------------------------------------------------


def _check_subset(
    session: Session,
    result: Preflight,
    sets: list[EvalSet],
    cases_by_set: dict[int | None, list[EvalCase]],
    case_ids: list[int] | None,
) -> None:
    """Say plainly that this is part of a set, and what was left out.

    A partial run's numbers are not the set's numbers, and the place to say so
    is before it starts — a pass rate over nine of four hundred cases will
    otherwise be filed next to one over all four hundred.
    """
    if case_ids is None:
        return

    available = sum(len(_cases_in_set(session, s.id or 0)) for s in sets)
    selected = result.case_count
    if selected < available:
        result.findings.append(
            Finding(
                NOTE,
                "partial_set",
                f"Running {selected} of {available} cases in the selection.",
                detail=(
                    "The result describes these cases, not the whole set. Comparisons against "
                    "a full-set run are not like-for-like."
                ),
                count=selected,
            )
        )

    # A case can sit in two chosen sets, so count distinct ids rather than rows.
    found = {c.id for cases in cases_by_set.values() for c in cases}
    missing = len(set(case_ids) - found)
    if missing > 0:
        result.findings.append(
            Finding(
                NOTE,
                "cases_outside_selection",
                f"{missing} chosen case(s) are not in the chosen sets and will be skipped.",
                detail="Add their set to the selection, or drop them from the choice.",
                count=missing,
            )
        )


def _check_credentials(result: Preflight, executors: list[_ExecutorInfo]) -> None:
    """A missing key fails every item in the lane, one call at a time."""
    environment = credential_environment()
    missing = [
        e
        for e in executors
        if e.model.api_key_env and not environment.get(e.model.api_key_env, "").strip()
    ]
    for info in missing:
        result.findings.append(
            Finding(
                BLOCKER,
                "missing_api_key",
                f"{info.name} needs ${info.model.api_key_env}, which is not set.",
                detail=(
                    "Add it to .env and restart the API. Without it every call in this lane "
                    "fails on authentication."
                ),
            )
        )


def _check_executor_compatibility(
    result: Preflight,
    sets: list[EvalSet],
    cases_by_set: dict[int | None, list[EvalCase]],
    executors: list[_ExecutorInfo],
) -> None:
    """Refuse pairings whose output or environment contract cannot satisfy the set.

    These are configuration failures, not model-quality failures.  Letting them
    run produces a very convincing 0% report even though every HTTP call may have
    succeeded.  Tags express environment requirements; scorer schemas express
    the output contract actually consumed by Gaugix.
    """
    cases = [case for eval_set in sets for case in cases_by_set.get(eval_set.id, [])]
    verdict_cases = [
        case
        for eval_set in sets
        for case in cases_by_set.get(eval_set.id, [])
        if _requires_guardrail_verdict(case, eval_set)
    ]
    blocked_verdict_cases = [
        case
        for eval_set in sets
        for case in cases_by_set.get(eval_set.id, [])
        if _expects_blocked_guardrail_verdict(case, eval_set)
    ]
    stub_cases = [case for case in cases if "needs:stub" in case.tags]
    real_cases = [case for case in cases if "no-stub" in case.tags]

    for executor in executors:
        if (
            verdict_cases
            and executor.harness.kind == str(HarnessKind.direct)
            and executor.harness.config.get("output_adapter") != "guardrail_verdict_v1"
        ):
            result.findings.append(
                Finding(
                    BLOCKER,
                    "output_contract_mismatch",
                    f"{executor.name} returns raw model/API text, but the selected cases "
                    "require the Guardrail verdict contract.",
                    detail=(
                        "Use a CLI probe executor or configure the Direct harness with "
                        "output_adapter=guardrail_verdict_v1. Otherwise fields such as "
                        "verdict, rule_id and method cannot be scored."
                    ),
                    count=len(verdict_cases),
                )
            )

        capture = executor.harness.config.get("capture_http_errors")
        captures_guardrail_block = (
            isinstance(capture, dict)
            and 403 in (capture.get("status_codes") or [])
            and "guardrails_blocked" in (capture.get("error_codes") or [])
        )
        if (
            blocked_verdict_cases
            and executor.harness.kind == str(HarnessKind.direct)
            and executor.harness.config.get("output_adapter") == "guardrail_verdict_v1"
            and not captures_guardrail_block
        ):
            result.findings.append(
                Finding(
                    BLOCKER,
                    "guardrail_capture_mismatch",
                    f"{executor.name} adapts successful output, but cannot capture the "
                    "structured policy refusals expected by the selected cases.",
                    detail=(
                        "Configure capture_http_errors with status_codes=[403] and "
                        "error_codes=['guardrails_blocked']. Otherwise expected blocks "
                        "become execution errors instead of guardrail-verdict/v1 output."
                    ),
                    count=len(blocked_verdict_cases),
                )
            )

        if stub_cases and executor.model.provider != str(Provider.fake):
            result.findings.append(
                Finding(
                    BLOCKER,
                    "stub_requirement_mismatch",
                    f"{executor.name} uses a real model, but {len(stub_cases)} selected "
                    "case(s) require the deterministic stub stack.",
                    detail=(
                        "Choose the mt0 Guardrail probe executor and materialize the matching "
                        "policy first, or choose a no-stub real-API set. A real upstream changes "
                        "output-side assertions and makes this comparison invalid."
                    ),
                    count=len(stub_cases),
                )
            )

        if real_cases and executor.model.provider == str(Provider.fake):
            result.findings.append(
                Finding(
                    BLOCKER,
                    "real_api_requirement_mismatch",
                    f"{executor.name} is a fake/stub model profile, but {len(real_cases)} "
                    "selected case(s) require real API calls.",
                    detail="Choose a real-API executor for sets tagged no-stub.",
                    count=len(real_cases),
                )
            )


def _requires_guardrail_verdict(case: EvalCase, eval_set: EvalSet) -> bool:
    """Whether resolved JSON-schema scoring consumes the canonical verdict object."""
    if "contract:guardrail-verdict-v1" in case.tags:
        return True
    specs = resolve_scoring(case, eval_set)
    for spec in specs:
        if spec.type != ScorerType.json_schema:
            continue
        schema = spec.params.get("schema")
        if not isinstance(schema, dict):
            continue
        required = schema.get("required")
        if isinstance(required, list) and "verdict" in required:
            return True
    return False


def _expects_blocked_guardrail_verdict(case: EvalCase, eval_set: EvalSet) -> bool:
    """Whether a case requires a captured structured policy refusal."""
    if "expect:block" in case.tags:
        return _requires_guardrail_verdict(case, eval_set)
    for spec in resolve_scoring(case, eval_set):
        if spec.type != ScorerType.json_schema:
            continue
        schema = spec.params.get("schema")
        if not isinstance(schema, dict):
            continue
        required = schema.get("required")
        properties = schema.get("properties")
        verdict = properties.get("verdict") if isinstance(properties, dict) else None
        if (
            isinstance(required, list)
            and "verdict" in required
            and isinstance(verdict, dict)
            and verdict.get("const") == "blocked"
        ):
            return True
    return False


def _check_scorers(
    session: Session,
    result: Preflight,
    sets: list[EvalSet],
    cases_by_set: dict[int | None, list[EvalCase]],
    executors: list[_ExecutorInfo],
    auto_score: bool,
) -> list[ScorerSpec]:
    """Validate the *resolved* config — the set default counts as the case's.

    Returns every judge scorer in the run — the cost estimate prices each at
    its own judge's rate. With `auto_score` off nothing here scores during the
    run, so a broken scorer stops being a blocker: refusing to launch over a
    scorer that will not run is a dead end (D-046).
    """
    unscored = 0
    seen_problems: set[tuple[str, str]] = set()
    judge_specs: list[ScorerSpec] = []
    code_sets: list[str] = []
    local_sets: list[str] = []

    for eval_set in sets:
        set_executes_code = False
        set_runs_python = False
        for case in cases_by_set.get(eval_set.id, []):
            scoring = resolve_scoring(case, eval_set)
            if not scoring:
                unscored += 1
                continue
            for spec in scoring:
                if spec.type == ScorerType.llm_judge:
                    judge_specs.append(spec)
                if spec.type == ScorerType.python:
                    set_runs_python = True
                    if executes_model_output(spec):
                        set_executes_code = True
                problem = _scorer_problem(spec)
                if problem is None:
                    continue
                key = (str(spec.type), problem)
                if key in seen_problems:
                    continue
                seen_problems.add(key)
                result.findings.append(
                    Finding(
                        BLOCKER if auto_score else NOTE,
                        "invalid_scorer",
                        f"A {spec.type} scorer is misconfigured: {problem}",
                        detail=(
                            f"First seen on “{case.title}”. "
                            + (
                                "Fix it before spending tokens on it."
                                if auto_score
                                else "Automatic scoring is off, so it will not run — but a "
                                "later re-score will hit it."
                            )
                        ),
                    )
                )
        if set_executes_code:
            code_sets.append(eval_set.name)
        elif set_runs_python:
            local_sets.append(eval_set.name)

    if code_sets and auto_score:
        result.requires_code_execution = True
        result.code_execution_sets = code_sets
        result.findings.append(
            Finding(
                WARNING,
                "executes_model_output",
                "Scoring this run runs model-written code on this machine.",
                detail=(
                    f"A Python scorer in {', '.join(code_sets)} executes whatever the model "
                    "returns, with your user's permissions and no sandbox. Read the scorer "
                    "before launching."
                ),
                count=len(code_sets),
            )
        )
    # Worth saying, not worth stopping for. A GSM8K or IFEval scorer is Python
    # running on this machine — *your* Python, reading the model's answer as a
    # string. Demanding a code-execution acknowledgement for that taught people
    # to click through the one that matters (D-055).
    if local_sets and auto_score:
        result.findings.append(
            Finding(
                NOTE,
                "local_python_scorer",
                f"A Python scorer runs on this machine for {', '.join(local_sets)}.",
                detail=(
                    "It reads the model's answer as text rather than running it. The code is "
                    "yours to read in the case editor — Gaugix does not sandbox scorers."
                ),
                count=len(local_sets),
            )
        )

    if unscored:
        result.findings.append(
            Finding(
                WARNING,
                "unscored_cases",
                f"{unscored} case(s) have no scorers and will come back unscored.",
                detail=(
                    "They still cost a model call. Give them scorers, or set a default "
                    "scoring config on their set."
                ),
                count=unscored,
            )
        )

    if not auto_score:
        result.findings.append(
            Finding(
                NOTE,
                "scoring_disabled",
                "Automatic scoring is off — every item will finish unscored.",
                detail="Score them later from the run page; the outputs are kept either way.",
            )
        )
    elif judge_specs:
        _check_judges(session, result, judge_specs, executors)

    return judge_specs


#: Ways a scorer can hand the model's answer to the interpreter. These are
#: *needles searched for in scorer source*, never called — this module only
#: reads scorer text, it does not run it. Deliberately broad: a false positive
#: costs one extra tick, a false negative runs model-written code unannounced.
_EXECUTION_MARKERS = ("exec(", "eval(", "compile(", "subprocess", "os.system", "__import__")


def executes_model_output(spec: ScorerSpec) -> bool:
    """Whether this Python scorer runs the model's answer rather than reading it.

    Two sources, in order. Catalogue scorers *declare* it — HumanEval sets
    `executes_output`, GSM8K and IFEval do not — which is exact. A hand-written
    scorer declares nothing, so its source is scanned for the constructs that
    could hand the output to the interpreter. That scan cannot be sound (the
    question is undecidable), so it errs towards warning.
    """
    declared = spec.params.get("executes_output")
    if isinstance(declared, bool):
        return declared
    code = spec.params.get("code")
    if not isinstance(code, str):
        return False
    return any(marker in code for marker in _EXECUTION_MARKERS)


def _scorer_problem(spec: ScorerSpec) -> str | None:
    """Why this scorer would fail at scoring time, or None when it is fine."""
    params = spec.params

    if spec.type in (ScorerType.contains, ScorerType.not_contains):
        text = params.get("text")
        if not isinstance(text, str) or not text:
            return "`text` is empty, so it matches everything"

    elif spec.type == ScorerType.regex:
        pattern = params.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return "`pattern` is empty"
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"the pattern does not compile ({exc})"

    elif spec.type == ScorerType.json_schema:
        schema = params.get("schema")
        if not isinstance(schema, dict):
            return "`schema` is not an object"
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            return f"the schema is invalid ({exc.message})"

    elif spec.type == ScorerType.python:
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            return "`code` is empty"
        if "def score" not in code:
            return "the code defines no `score(case, output)` function"
        try:
            compile(code, "<preflight>", "exec")
        except SyntaxError as exc:
            return f"the code does not parse (line {exc.lineno}: {exc.msg})"

    elif spec.type == ScorerType.llm_judge:
        if not params.get("rubric") and not params.get("rubric_ref"):
            return "no rubric — set `rubric` inline or point `rubric_ref` at one"
        scale = str(params.get("scale") or "1-5")
        if scale_bounds(scale) is None:
            # An unmappable scale used to reach scoring and be clamped as a
            # percentage, so `1-7` turned a top mark into 7 out of 100 — the
            # same shape as the `0-1` bug, and just as invisible (D-066).
            return (
                f"`scale` is {scale!r}, which has no numeric range — "
                f"use one of {', '.join(sorted(NAMED_SCALES))}, or write it as "
                f"a range like `1-7`"
            )
        _, threshold_error = threshold_value(params.get("pass_threshold"), scale)
        if threshold_error is not None:
            return threshold_error
        _, _, classes_error = class_config(params)
        if classes_error is not None:
            return classes_error

    return None


def _check_judges(
    session: Session,
    result: Preflight,
    judge_specs: list[ScorerSpec],
    executors: list[_ExecutorInfo],
) -> None:
    """Self-judging is the bias this catches: a model grading its own answer."""
    under_test = {e.name for e in executors}
    unresolved = 0
    self_judged: set[str] = set()
    invalid: set[str] = set()

    for spec in judge_specs:
        resolution = resolve_judge_executor(session, dict(spec.params))
        if resolution.error is not None:
            invalid.add(resolution.error)
            continue
        judge = resolution.executor
        if judge is None:
            unresolved += 1
        elif judge.key in under_test:
            self_judged.add(judge.key)

    for problem in sorted(invalid):
        result.findings.append(
            Finding(
                BLOCKER,
                "invalid_judge_executor",
                f"A judge scorer is misconfigured: {problem}.",
                detail=(
                    "Choose an existing executor or remove the explicit judge to use the "
                    "Settings default. Gaugix will not silently substitute another grader."
                ),
            )
        )

    if unresolved:
        result.findings.append(
            Finding(
                WARNING,
                "self_judging",
                "Some judge scorers resolve to no judge, so each model grades its own answer.",
                detail=(
                    "Pick a default judge on Settings, or name one per scorer. A model "
                    "marking its own homework flatters itself measurably."
                ),
                count=unresolved,
            )
        )
    for key in sorted(self_judged):
        result.findings.append(
            Finding(
                WARNING,
                "judge_under_test",
                f"The judge ({key}) is also one of the executors being evaluated.",
                detail="Its own answers will be graded by itself. Use a judge outside the run.",
            )
        )


def _check_duplicates(
    result: Preflight, sets: list[EvalSet], cases_by_set: dict[int | None, list[EvalCase]]
) -> None:
    """A case in two selected sets runs twice — legitimate, but say so."""
    seen: dict[int, list[str]] = {}
    for eval_set in sets:
        for case in cases_by_set.get(eval_set.id, []):
            if case.id is not None:
                seen.setdefault(case.id, []).append(eval_set.name)

    repeated = {case_id: names for case_id, names in seen.items() if len(names) > 1}
    if repeated:
        example = next(iter(repeated.values()))
        result.findings.append(
            Finding(
                NOTE,
                "duplicate_cases",
                f"{len(repeated)} case(s) belong to more than one selected set.",
                detail=(
                    f"They will be invoked once per set (e.g. {' + '.join(example)}), and "
                    "counted separately everywhere."
                ),
                count=len(repeated),
            )
        )


def _check_pricing(result: Preflight, executors: list[_ExecutorInfo]) -> None:
    unpriced = [e for e in executors if str(e.model.provider) != "fake" and e.model.pricing is None]
    for info in unpriced:
        result.findings.append(
            Finding(
                WARNING,
                "unknown_pricing",
                f"No price is known for {info.model.model_id}, so the cost will be a floor.",
                detail="Add rates on the Settings pricing table, or pull them from litellm.",
            )
        )


def _estimate(
    session: Session,
    result: Preflight,
    executors: list[_ExecutorInfo],
    judge_specs: list[ScorerSpec],
) -> None:
    """A cost range, or None when any model in the run cannot be priced.

    A partial estimate is worse than none: it reads as "this run is cheap" when
    the model we could not price is the expensive one (D-017 applied forward).
    The judge is part of "the run" for this purpose — a judged 4,326-case set
    costs two calls per item, and an estimate that counted one understated it by
    more than half (D-047).
    """
    total = 0.0
    for info in executors:
        if str(info.model.provider) == "fake":
            continue
        pricing = info.model.pricing
        if pricing is None:
            result.estimated_cost_usd = None
            result.cost_assumptions = (
                "No estimate: at least one model has no known price, and a partial total "
                "would read as a complete one."
            )
            return
        total += (
            result.case_count
            * (
                ASSUMED_PROMPT_TOKENS * pricing.input_per_1m
                + ASSUMED_COMPLETION_TOKENS * pricing.output_per_1m
            )
            / 1_000_000
        )

    judge_note = ""
    if judge_specs:
        # Every executor's answer is judged separately, so judge calls scale with
        # the matrix, not with the case count.
        # Per scorer, not per case: a case with two judge scorers makes two
        # judge calls, and counting the case once halved it.
        result.judge_call_count = len(judge_specs) * max(1, len(executors))
        judge_cost = _judge_cost(session, judge_specs, executors)
        if judge_cost is None:
            result.estimated_cost_usd = None
            result.estimated_judge_cost_usd = None
            result.cost_assumptions = (
                f"No estimate: this run makes about {result.judge_call_count} judge calls and "
                "the judge model has no known price. Add rates on Settings, or the total would "
                "hide its largest half."
            )
            return
        result.estimated_judge_cost_usd = round(judge_cost, 6)
        total += judge_cost
        judge_note = (
            f" Includes ~{result.judge_call_count} judge calls "
            f"(≈{formatted(judge_cost)}) at {ASSUMED_JUDGE_PROMPT_TOKENS} prompt and "
            f"{ASSUMED_JUDGE_COMPLETION_TOKENS} completion tokens each."
        )

    result.estimated_cost_usd = round(total, 6)
    result.cost_assumptions = (
        f"Assumes {ASSUMED_PROMPT_TOKENS} prompt and {ASSUMED_COMPLETION_TOKENS} completion "
        f"tokens per item — a guess, not a quote.{judge_note} Retries and long answers are not "
        "included, so treat it as a lower bound."
    )


def formatted(usd: float) -> str:
    """Money for prose. Never rounds a real cost down to `$0.00`."""
    if usd == 0:
        return "$0.00"
    return f"${usd:.2f}" if usd >= 0.01 else f"${usd:.4f}"


def _judge_cost(
    session: Session, judge_specs: list[ScorerSpec], executors: list[_ExecutorInfo]
) -> float | None:
    """Cost of running every judge scorer once per executor, or None if unpriceable.

    Priced per scorer at *its own* judge's rate. A run can mix judges — one
    scorer naming a cheap model, another falling back to the expensive default
    — and pricing them all at one rate was wrong in whichever direction the
    default happened to sit (D-058).

    A scorer that resolves to no judge is graded by the executor under test
    (the self-judging fallback preflight already warns about), so it is priced
    at each executor's own rate.
    """
    from gaugix.scoring.judge_config import judge_executor_for

    total = 0.0
    for spec in judge_specs:
        judge = judge_executor_for(session, dict(spec.params))
        if judge is not None:
            if str(judge.model.provider) == "fake":
                continue
            pricing = judge.model.pricing
            if pricing is None:
                return None
            total += len(executors) * _per_judge_call(pricing)
            continue

        for info in executors:
            if str(info.model.provider) == "fake":
                continue
            if info.model.pricing is None:  # pragma: no cover — _estimate returns first
                return None
            total += _per_judge_call(info.model.pricing)
    return total


def _per_judge_call(pricing: Pricing) -> float:
    return (
        ASSUMED_JUDGE_PROMPT_TOKENS * pricing.input_per_1m
        + ASSUMED_JUDGE_COMPLETION_TOKENS * pricing.output_per_1m
    ) / 1_000_000
