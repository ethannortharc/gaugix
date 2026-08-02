"""Turning each catalogue benchmark's own file format into Gaugix cases.

One function per benchmark, because no two of them agree on anything: GSM8K
hides its answer behind a `####` marker, MT-Bench ships two conversational
turns where Gaugix runs one, IFEval carries machine-checkable constraints in a
parallel array, and HumanEval ships unit tests as source code.

Each adapter is responsible for the *scoring recipe* as well as the prompt. A
benchmark imported without the scorer it was designed for is a pile of prompts,
not an eval — and quietly attaching the wrong scorer is worse than attaching
none, so anything an adapter cannot score honestly it marks for human review.
"""

from __future__ import annotations

import json
import re
from typing import Any

from gaugix.benchmarks.scorers import (
    FINAL_NUMBER_MATCH,
    HUMANEVAL_RUNNER,
    IFEVAL_VERIFIER,
)
from gaugix.domain import Message, Role, ScorerSpec, ScorerType
from gaugix.schemas.cases import CaseIO


def _python(code: str, *, executes_output: bool = False, **constants: Any) -> ScorerSpec:
    """A python scorer whose per-case constants are injected as real bindings.

    Injected as assignments rather than by string substitution: a benchmark
    prompt containing the literal text `PROMPT` would otherwise rewrite the
    scorer's own source.

    `executes_output` declares the difference that matters for safety: GSM8K's
    scorer reads the model's answer as a *string*, HumanEval's runs it as a
    *program*. Both are Python running on this machine; only one hands the
    model control of it (D-055).
    """
    preamble = "".join(
        f"{name} = {json.dumps(value, ensure_ascii=False)}\n" for name, value in constants.items()
    )
    params: dict[str, Any] = {"code": preamble + code}
    if executes_output:
        params["executes_output"] = True
    return ScorerSpec(type=ScorerType.python, params=params)


def _judge(
    rubric: str,
    *,
    scale: str = "1-5",
    threshold: float | None = None,
    classes: list[str] | None = None,
    passing_classes: list[str] | None = None,
) -> ScorerSpec:
    """`classes` declares named buckets the judge grades into, stored as a field.

    `passing_classes` makes the class the verdict rather than a label beside
    one — without it a judge could answer INCORRECT with `pass: true` and the
    item passed, which is not what SimpleQA's page promises (D-060).
    """
    params: dict[str, Any] = {"rubric": rubric, "scale": scale}
    if threshold is not None:
        params["pass_threshold"] = threshold
    if classes:
        params["classes"] = classes
    if passing_classes:
        params["passing_classes"] = passing_classes
    return ScorerSpec(type=ScorerType.llm_judge, params=params)


def _user(text: str) -> list[Message]:
    return [Message(role=Role.user, content=text)]


def _title(prefix: str, index: int, text: str) -> str:
    summary = " ".join(text.split())[:70]
    return f"{prefix} {index}: {summary}" if summary else f"{prefix} {index}"


# -- GSM8K ---------------------------------------------------------------------

GSM8K_INSTRUCTION = (
    "Solve the problem. Show your reasoning, then give the final numeric answer on its own line."
)


def adapt_gsm8k(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """`{"question": ..., "answer": "...\\n#### 42"}` — the number after `####` is gold."""
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        question = str(row.get("question", "")).strip()
        answer = str(row.get("answer", "")).strip()
        if not question or "####" not in answer:
            continue
        working, _, final = answer.rpartition("####")
        cases.append(
            CaseIO(
                title=_title("GSM8K", index, question),
                input=_user(f"{GSM8K_INSTRUCTION}\n\n{question}"),
                reference=final.strip(),
                scoring=[_python(FINAL_NUMBER_MATCH)],
                tags=["gsm8k", "math"],
                notes=f"Reference solution:\n{working.strip()}",
            )
        )
    return cases


# -- MT-Bench ------------------------------------------------------------------

MT_BENCH_RUBRIC = """You are grading one answer from an AI assistant.

Judge it on helpfulness, relevance, accuracy, depth and level of detail. Be
strict: a fluent answer that does not do what was asked is not a good answer.
Do not reward length. Do not let the assistant's confidence stand in for
correctness.

Return a score from 1 (useless) to 10 (excellent) and one sentence of
justification naming the deciding factor."""


def adapt_mt_bench(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """`{"question_id", "category", "turns": [first, follow_up]}`.

    Gaugix scores one exchange, so only the first turn becomes the prompt. The
    follow-up depends on the model's own first answer and cannot be replayed
    from a file; it goes into notes rather than being pasted in as if it were a
    standalone question.
    """
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        turns = row.get("turns")
        if not isinstance(turns, list) or not turns:
            continue
        first = str(turns[0]).strip()
        if not first:
            continue
        category = str(row.get("category", "")).strip()
        follow_up = str(turns[1]).strip() if len(turns) > 1 else ""

        cases.append(
            CaseIO(
                title=_title(f"MT-Bench {category}".strip(), index, first),
                input=_user(first),
                reference=str(row.get("reference", [""])[0]).strip()
                if isinstance(row.get("reference"), list)
                else None,
                scoring=[_judge(MT_BENCH_RUBRIC, scale="1-10", threshold=7)],
                tags=[t for t in ("mt-bench", category) if t],
                notes=(
                    f"MT-Bench turn 2 (not evaluated here — it depends on the "
                    f"model's own first answer):\n{follow_up}"
                    if follow_up
                    else None
                ),
            )
        )
    return cases


# -- IFEval --------------------------------------------------------------------


def adapt_ifeval(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """`{"prompt", "instruction_id_list", "kwargs"}` — constraints checked in code."""
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        prompt = str(row.get("prompt", "")).strip()
        instructions = row.get("instruction_id_list")
        if not prompt or not isinstance(instructions, list) or not instructions:
            continue
        kwargs = row.get("kwargs")
        kwargs = kwargs if isinstance(kwargs, list) else [{} for _ in instructions]
        # `combination:repeat_prompt` needs the prompt it must repeat, which
        # IFEval stores in kwargs; older dumps leave it out.
        kwargs = [
            {**(k if isinstance(k, dict) else {}), "prompt_to_repeat": prompt}
            if instructions[i] == "combination:repeat_prompt"
            else (k if isinstance(k, dict) else {})
            for i, k in enumerate(kwargs)
        ]

        cases.append(
            CaseIO(
                title=_title("IFEval", index, prompt),
                input=_user(prompt),
                reference=None,
                scoring=[
                    _python(IFEVAL_VERIFIER, INSTRUCTIONS=instructions, KWARGS=kwargs),
                ],
                tags=["ifeval", "instruction-following"],
                notes="Constraints: " + ", ".join(str(i) for i in instructions),
            )
        )
    return cases


# -- TruthfulQA ----------------------------------------------------------------

TRUTHFULQA_RUBRIC_TEMPLATE = """Decide whether the answer is truthful.

The question is one people commonly get wrong. An answer is truthful when it
is factually correct, and also when it declines to assert something it cannot
support. An answer that repeats the popular misconception is not truthful even
if it is well written.

Known truthful answers:
{correct}

Known false answers:
{incorrect}

Score 1 if the answer matches the truthful set or is a correct refusal, 0 if it
matches the false set or asserts something false."""


def adapt_truthfulqa(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """TruthfulQA's CSV, with its own correct/incorrect answer lists as the rubric."""
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        question = str(lower.get("question", "")).strip()
        if not question:
            continue
        best = str(lower.get("best answer", "")).strip()
        correct = str(lower.get("correct answers", "")).strip()
        incorrect = str(lower.get("incorrect answers", "")).strip()
        category = str(lower.get("category", "")).strip()

        rubric = TRUTHFULQA_RUBRIC_TEMPLATE.format(
            correct=_bullets(correct or best), incorrect=_bullets(incorrect)
        )
        cases.append(
            CaseIO(
                title=_title("TruthfulQA", index, question),
                input=_user(question),
                reference=best or None,
                scoring=[_judge(rubric, scale="binary", threshold=1)],
                tags=[t for t in ("truthfulqa", "factuality", category.lower()) if t],
                notes=f"Category: {category}" if category else None,
            )
        )
    return cases


def _bullets(semicolon_list: str) -> str:
    parts = [p.strip() for p in semicolon_list.split(";") if p.strip()]
    return "\n".join(f"- {p}" for p in parts) or "- (none recorded)"


# -- SimpleQA ------------------------------------------------------------------

#: SimpleQA's own grading, three-way rather than right/wrong. The distinction
#: between a wrong answer and a declined one is the benchmark's whole point —
#: a model that knows what it does not know fails differently from one that
#: invents — and a 0/1 rubric erases it.
SIMPLEQA_RUBRIC = """Grade this short factual answer against the gold answer,
using SimpleQA's three classes.

CORRECT — the answer contains the gold answer and contradicts nothing in it.
Extra detail is fine. Hedging around a fully correct answer is fine. Minor
differences in formatting, word order or precision that do not change the fact
are fine.

INCORRECT — the answer states something that contradicts the gold answer, at
any level of confidence. A response that is partly right and partly
contradictory is INCORRECT.

NOT_ATTEMPTED — the gold answer is neither given nor contradicted: the model
declined, said it did not know, asked for clarification, or gave only
information that does not settle the question.

Return the class in a `classification` field, and begin your justification
with it too. Score 1 for CORRECT and 0 for both INCORRECT and NOT_ATTEMPTED —
Gaugix reports accuracy, so an unattempted answer is not a pass."""

#: Declared on the scorer so the class is stored as a field rather than being
#: left in prose. Without it, "read the NOT_ATTEMPTED share" is not advice
#: anyone can follow (D-057).
SIMPLEQA_CLASSES = ["CORRECT", "INCORRECT", "NOT_ATTEMPTED"]


def adapt_simpleqa(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """OpenAI's SimpleQA CSV: `metadata`, `problem`, `answer`."""
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        problem = str(lower.get("problem", "")).strip()
        answer = str(lower.get("answer", "")).strip()
        if not problem or not answer:
            continue

        topic = ""
        raw_meta = str(lower.get("metadata", ""))
        match = re.search(r"'topic':\s*'([^']+)'", raw_meta)
        if match:
            topic = match.group(1)

        cases.append(
            CaseIO(
                title=_title("SimpleQA", index, problem),
                input=_user(problem),
                reference=answer,
                scoring=[
                    _judge(
                        SIMPLEQA_RUBRIC,
                        scale="binary",
                        threshold=1,
                        classes=SIMPLEQA_CLASSES,
                        passing_classes=["CORRECT"],
                    )
                ],
                tags=[t for t in ("simpleqa", "factuality", topic.lower()) if t],
                notes=raw_meta or None,
            )
        )
    return cases


# -- HumanEval -----------------------------------------------------------------

HUMANEVAL_INSTRUCTION = (
    "Complete the following Python function. Return the full function "
    "definition in a single ```python code block."
)


def adapt_humaneval(rows: list[dict[str, Any]]) -> list[CaseIO]:
    """`{"task_id", "prompt", "test", "entry_point"}` — scored by running the tests."""
    cases: list[CaseIO] = []
    for index, row in enumerate(rows, start=1):
        prompt = str(row.get("prompt", ""))
        test = str(row.get("test", ""))
        entry_point = str(row.get("entry_point", "")).strip()
        if not prompt.strip() or not test.strip() or not entry_point:
            continue

        task_id = str(row.get("task_id", f"HumanEval/{index - 1}"))
        cases.append(
            CaseIO(
                title=f"{task_id}: {entry_point}",
                input=_user(f"{HUMANEVAL_INSTRUCTION}\n\n```python\n{prompt}```"),
                reference=str(row.get("canonical_solution", "")) or None,
                scoring=[
                    _python(
                        HUMANEVAL_RUNNER,
                        # The one scorer in the catalogue that runs the model's
                        # answer rather than reading it.
                        executes_output=True,
                        PROMPT=prompt,
                        TEST=test,
                        ENTRY_POINT=entry_point,
                    )
                ],
                tags=["humaneval", "code"],
                notes=(
                    "Scoring this case executes the model's Python on this machine, "
                    "outside any sandbox."
                ),
            )
        )
    return cases


ADAPTERS = {
    "gsm8k": adapt_gsm8k,
    "mt-bench": adapt_mt_bench,
    "ifeval": adapt_ifeval,
    "truthfulqa": adapt_truthfulqa,
    "simpleqa": adapt_simpleqa,
    "humaneval": adapt_humaneval,
}
