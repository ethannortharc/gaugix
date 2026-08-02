"""AI-assisted case generation (PRD F1.4 path A, F1.5 path B).

Path A is the one that always works: Gaugix builds a prompt containing the
canonical schema, the user's topic, and K real examples from their set; the user
pastes it into whatever assistant they like and pastes the JSONL back. The
paste-back flow reuses the ordinary import validator, so generated cases go
through exactly the same gate as hand-written ones.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, select

from gaugix import caseio
from gaugix.api.cases import to_read
from gaugix.db import get_session
from gaugix.errors import NotFoundError
from gaugix.models.cases import EvalCase, SetMembership
from gaugix.repo import get_live_set
from gaugix.schemas.cases import (
    GenDirectRequest,
    GenDirectResponse,
    GenPromptRequest,
    GenPromptResponse,
)

router = APIRouter(prefix="/gen", tags=["generation"])

SessionDep = Annotated[Session, Depends(get_session)]

SCHEMA_BLOCK = """{
  "title": "string (required, one specific behaviour)",
  "input": [{"role": "system|user|assistant", "content": "string"}],
  "reference": "string | null — the expected answer or notes for scorers/humans",
  "scoring": [ /* scorer specs, see below; may be [] to inherit the set default */ ],
  "tags": ["string"],
  "notes": "string | null"
}"""

SCORER_BLOCK = """{"type": "contains", "params": {"text": "...", "case_sensitive": false}, "required": true, "weight": 1}
{"type": "not_contains", "params": {"text": "...", "case_sensitive": false}, "required": false, "weight": 1}
{"type": "regex", "params": {"pattern": "^```go\\\\n", "should_match": true}, "required": true, "weight": 1}
{"type": "json_schema", "params": {"schema": {"type": "object", "required": ["action"]}, "extract_json": true}, "required": true, "weight": 1}
{"type": "llm_judge", "params": {"rubric": "...", "scale": "1-5", "pass_threshold": 4}, "required": true, "weight": 2}
{"type": "human", "params": {"instructions": "..."}, "required": false, "weight": 1}"""


def build_generation_prompt(
    topic: str,
    count: int,
    examples: list[dict[str, object]],
    instructions: str | None = None,
    set_name: str | None = None,
) -> str:
    """Assemble the copy-able generation prompt (PRD F1.4a)."""
    lines: list[str] = [
        "You are helping build an LLM evaluation set for Gaugix.",
        "",
        f"# Task\nWrite {count} new eval cases about: {topic}",
    ]
    if set_name:
        lines.append(f"They will be added to the existing set “{set_name}”.")
    if instructions:
        lines.append(f"\nAdditional instructions from the author:\n{instructions}")

    lines += [
        "",
        "# Output format",
        "Reply with **JSONL only** — one JSON object per line, no prose, no markdown fence.",
        "Each line must match this schema exactly:",
        "",
        "```",
        SCHEMA_BLOCK,
        "```",
        "",
        "Valid scorer specs (choose what actually tests the behaviour; prefer",
        "deterministic assertions over a judge when a substring or schema will do):",
        "",
        "```",
        SCORER_BLOCK,
        "```",
    ]

    if examples:
        lines += [
            "",
            f"# Examples from the author's existing set ({len(examples)})",
            "Match this style, specificity and tagging discipline:",
            "",
            "```",
            *[json.dumps(e, ensure_ascii=False) for e in examples],
            "```",
        ]

    lines += [
        "",
        "# Rules",
        "- One behaviour per case; a case must be able to fail for exactly one reason.",
        "- Inputs must be realistic, not toy phrasings.",
        "- Include negative / benign-lookalike cases where the topic warrants them.",
        "- `reference` should say what a correct answer must contain, not restate the prompt.",
        "- Tag consistently with the examples.",
        f"- Output exactly {count} lines. Nothing else.",
    ]
    return "\n".join(lines)


@router.post("/prompt", response_model=GenPromptResponse)
def generation_prompt(payload: GenPromptRequest, session: SessionDep) -> GenPromptResponse:
    """Build a generation prompt seeded with real examples from the user's set."""
    set_name: str | None = None
    examples: list[dict[str, object]] = []
    example_ids: list[int] = []

    if payload.set_id is not None:
        eval_set = get_live_set(session, payload.set_id)
        set_name = eval_set.name
        if payload.example_count:
            rows = session.exec(
                select(EvalCase)
                .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
                .where(
                    SetMembership.set_id == payload.set_id,
                    col(EvalCase.deleted_at).is_(None),
                )
                .order_by(col(SetMembership.position))
                .limit(payload.example_count)
            ).all()
            for case in rows:
                examples.append(to_read(case).to_io().model_dump(mode="json"))
                if case.id is not None:
                    example_ids.append(case.id)

    prompt = build_generation_prompt(
        topic=payload.topic,
        count=payload.count,
        examples=examples,
        instructions=payload.instructions,
        set_name=set_name,
    )
    return GenPromptResponse(prompt=prompt, example_case_ids=example_ids)


__all__ = ["build_generation_prompt", "caseio", "router"]


@router.post("/direct", response_model=GenDirectResponse)
async def generate_direct(payload: GenDirectRequest, session: SessionDep) -> GenDirectResponse:
    """Path B (PRD F1.5): ask a configured executor for the cases directly.

    Same prompt as path A and the same import validator on the way back, so the
    only difference is who does the pasting. Nothing is written: candidates come
    back for review, and committing them goes through `/cases/import` like any
    other batch — a model's draft gets no more trust than a stranger's file.

    This spends money on the chosen executor. The UI says which one and warns.
    """
    from gaugix.domain import CaseSnapshot, Message, Role
    from gaugix.errors import ValidationError
    from gaugix.harness import get as get_harness
    from gaugix.harness.base import HarnessError, InvokeContext
    from gaugix.scoring.judge_config import executor_snapshot

    executor = executor_snapshot(session, payload.executor_id)
    if executor is None:
        raise NotFoundError(f"Executor {payload.executor_id} does not exist")

    prompt = generation_prompt(
        GenPromptRequest(
            topic=payload.topic,
            count=payload.count,
            set_id=payload.set_id,
            example_count=payload.example_count,
            instructions=payload.instructions,
        ),
        session,
    ).prompt

    harness = get_harness(executor.harness.kind)
    case = CaseSnapshot(title="generate cases", input=[Message(role=Role.user, content=prompt)])
    ctx = InvokeContext(
        run_id=None,
        attempt_n=1,
        try_index=0,
        harness_config=executor.harness.config,
        params=executor.effective_params(),
        purpose="generate",
    )
    try:
        invocation = await harness.invoke(case, executor.model, ctx)
    except HarnessError as exc:
        raise ValidationError(f"{executor.key} could not generate cases: {exc.message}") from exc

    # The model's output goes through the ordinary JSONL validator, so a
    # malformed line is a row error the user can read rather than a silent drop.
    cases, errors = caseio.parse_cases(_strip_fences(invocation.output_text), caseio.JSONL)
    return GenDirectResponse(
        cases=cases,
        errors=errors,
        raw_output=invocation.output_text,
        usage={
            "prompt_tokens": invocation.usage.prompt_tokens,
            "completion_tokens": invocation.usage.completion_tokens,
            "cost_usd": invocation.usage.cost_usd,
            "latency_ms": invocation.usage.latency_ms,
            "executor": executor.key,
        },
    )


def _strip_fences(text: str) -> str:
    """Models wrap JSONL in ```json fences however often you ask them not to."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
    return "\n".join(body)
