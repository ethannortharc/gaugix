#!/usr/bin/env python
"""Real-API smoke test — this script spends money (ARCHITECTURE §12).

Runs two tiny cases against the cheapest available model for each configured
provider key, asserting that usage and cost actually come back. Excluded from
`make check`; run it deliberately.

Guards, in order:

1. a hard cap on cumulative calls (`GAUGIX_SMOKE_MAX_CALLS`, default 50), counted
   across runs in `.gaugix-smoke-calls` at the repo root — deliberately outside
   `data/`, which `make seed` wipes;
2. cheapest model tier only — the table below is the only place model ids appear;
3. `--dry-run` prints the plan and calls nothing.

Usage:
    make smoke                  # run it
    make smoke ARGS=--dry-run   # show the plan only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from gaugix.config import (  # noqa: E402
    get_settings,
    load_dotenv_into_environ,
    read_api_key,
)
from gaugix.domain import (  # noqa: E402
    CaseSnapshot,
    HarnessError,
    InvokeContext,
    Message,
    ModelSnapshot,
    Provider,
    Role,
)
from gaugix.harness.direct import DirectHarness  # noqa: E402


@dataclass(frozen=True)
class SmokeTarget:
    """The cheapest model Gaugix will ever call on its own initiative."""

    label: str
    provider: Provider
    model_id: str
    env_var: str
    base_url: str | None = None


#: Cheapest tier per provider. Nothing else belongs here.
TARGETS: list[SmokeTarget] = [
    SmokeTarget("anthropic", Provider.anthropic, "claude-3-5-haiku-20241022", "ANTHROPIC_API_KEY"),
    SmokeTarget("openai", Provider.openai, "gpt-4o-mini", "OPENAI_API_KEY"),
    SmokeTarget("gemini", Provider.gemini, "gemini-2.0-flash-lite", "GEMINI_API_KEY"),
    SmokeTarget(
        "openrouter",
        Provider.openai_compatible,
        "openai/gpt-4o-mini",
        "OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
    ),
]

CASES = [
    CaseSnapshot(
        title="smoke: arithmetic",
        input=[Message(role=Role.user, content="What is 2+2? Reply with just the number.")],
    ),
    CaseSnapshot(
        title="smoke: single word",
        input=[Message(role=Role.user, content="Reply with exactly one word: ok")],
    ),
]


def counter_path() -> Path:
    """Outside `data/` on purpose: a budget that `make seed` resets is not a budget."""
    return Path(__file__).resolve().parent.parent / ".gaugix-smoke-calls"


def legacy_counter_path() -> Path:
    """Where the counter used to live, before a reseed could wipe it."""
    return get_settings().resolved_data_dir / ".smoke_calls"


def _read_counter(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text()).get("calls", 0))
    except (ValueError, OSError):
        return 0


def calls_so_far() -> int:
    # Take the larger of the two: a spend already made cannot be un-made by a
    # reseed, and on the first run after this change the old file is the truth.
    return max(_read_counter(counter_path()), _read_counter(legacy_counter_path()))


def record_calls(n: int) -> None:
    path = counter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calls": calls_so_far() + n}))


def available_targets() -> list[SmokeTarget]:
    return [t for t in TARGETS if read_api_key(t.env_var)]


async def probe(target: SmokeTarget, case: CaseSnapshot) -> dict[str, object]:
    model = ModelSnapshot(
        name=target.label,
        provider=target.provider,
        model_id=target.model_id,
        base_url=target.base_url,
        api_key_env=target.env_var,
        params={"max_tokens": 16, "temperature": 0},
    )
    ctx = InvokeContext(harness_config={}, params=model.params, timeout_s=60, purpose="smoke")
    try:
        result = await DirectHarness().invoke(case, model, ctx)
    except HarnessError as exc:
        return {"ok": False, "error": exc.message, "kind": exc.kind}

    usage = result.usage
    return {
        "ok": True,
        "output": result.output_text.strip()[:60],
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost_usd": usage.cost_usd,
        "latency_ms": usage.latency_ms,
    }


async def main_async(dry_run: bool) -> int:
    load_dotenv_into_environ()
    settings = get_settings()
    settings.ensure_dirs()

    targets = available_targets()
    if not targets:
        print("No provider keys are set — skipping the smoke test entirely.")
        print("Set one of: " + ", ".join(t.env_var for t in TARGETS) + " in .env")
        return 0

    planned = len(targets) * len(CASES)
    spent = calls_so_far()
    cap = settings.smoke_max_calls

    print(f"Providers with keys : {', '.join(t.label for t in targets)}")
    print(f"Planned calls       : {planned}")
    print(f"Cumulative so far   : {spent} / {cap}")

    if spent + planned > cap:
        print(
            f"\nRefusing to run: this would exceed GAUGIX_SMOKE_MAX_CALLS ({cap}).\n"
            f"Raise the cap in .env, or delete {counter_path()} to reset the counter.",
            file=sys.stderr,
        )
        return 2

    if dry_run:
        for target in targets:
            print(f"  would call {target.label}: {target.model_id} × {len(CASES)} cases")
        print("\n--dry-run: no API calls made.")
        return 0

    print()
    total_cost = 0.0
    unknown_cost = False
    failures = 0
    made = 0

    for target in targets:
        print(f"── {target.label} ({target.model_id})")
        for case in CASES:
            result = await probe(target, case)
            made += 1
            if not result["ok"]:
                failures += 1
                print(f"   ✗ {case.title}: {result['error']}")
                continue

            cost = result["cost_usd"]
            if cost is None:
                unknown_cost = True
                cost_text = "n/a"
            else:
                total_cost += float(cost)
                cost_text = f"${float(cost):.6f}"
            print(
                f"   ✓ {case.title}: {result['prompt_tokens']}+"
                f"{result['completion_tokens']} tok, {cost_text}, "
                f"{result['latency_ms']}ms → {result['output']!r}"
            )

            if int(result["prompt_tokens"] or 0) <= 0:
                failures += 1
                print("     ! usage came back empty — cost accounting would be wrong")

    record_calls(made)
    print(
        f"\nCalls made: {made} (cumulative {calls_so_far()}/{cap})\n"
        f"Estimated cost: ${total_cost:.6f}" + (" (+ unpriced calls)" if unknown_cost else "")
    )
    if failures:
        print(f"{failures} check(s) failed.", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    args = parser.parse_args()
    return asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    raise SystemExit(main())
