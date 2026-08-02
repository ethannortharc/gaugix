"""User-supplied Python scorers, run in an isolated subprocess (PRD F4.1).

**This is not a sandbox, and nothing here should be described as one.** It runs
code the user wrote, on their own machine, by their own request — the PRD's
trust model (NFR-S) allows that explicitly — and the guards contain *accidents*,
not a hostile author.

What the child process cannot do:

* corrupt the server: it is a separate `python -I` process (isolated mode — no
  user site-packages, no PYTHONPATH, no cwd on `sys.path`);
* wedge a run: a hard wall-clock timeout kills it;
* read provider credentials: `_safe_env` passes a minimal environment;
* crash anything: every failure becomes a scorer-error result.

What it *can* still do, because none of these are contained: read and write any
file the user can (including `$HOME`), open network connections, and spawn
further processes. Running a scorer you did not write is running a program you
did not read. Real isolation would need a container or a VM with filesystem,
network and resource limits — Gaugix does not provide one (D-033).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

from gaugix.config import get_settings
from gaugix.domain import CaseSnapshot
from gaugix.scoring.aggregate import finite_float
from gaugix.scoring.assertions import ScoreResult

#: Wrapper executed in the child process. Reads {case, output} on stdin, writes
#: the scorer's dict on stdout. Anything on stderr is treated as diagnostics.
RUNNER_SOURCE = """
import json, sys

payload = json.load(sys.stdin)
namespace = {}
exec(compile(payload["code"], "<gaugix-scorer>", "exec"), namespace)

score = namespace.get("score")
if not callable(score):
    print(json.dumps({"__gaugix_error__": "no callable `score(case, output)` was defined"}))
    sys.exit(0)

result = score(payload["case"], payload["output"])
if not isinstance(result, dict):
    kind = type(result).__name__
    print(json.dumps({"__gaugix_error__": f"score() returned {kind}, expected a dict"}))
    sys.exit(0)

print(json.dumps(result, default=str))
"""


def _safe_env() -> dict[str, str]:
    """Minimal environment — the snippet must not see provider credentials."""
    import os

    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }


def score_python(
    params: dict[str, Any], case: CaseSnapshot, output: str, timeout_s: float | None = None
) -> ScoreResult:
    """Run a user scorer and normalise whatever it returns."""
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        return ScoreResult.scorer_error("python: `code` param is required")

    timeout = timeout_s if timeout_s is not None else get_settings().python_scorer_timeout_s
    payload = json.dumps(
        {
            "code": textwrap.dedent(code),
            "output": output,
            "case": {
                "title": case.title,
                "input": case.messages_for_api(),
                "reference": case.reference,
                "tags": case.tags,
                "notes": case.notes,
            },
        }
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", RUNNER_SOURCE],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_safe_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ScoreResult.scorer_error(f"python: timed out after {timeout:g}s")
    except OSError as exc:
        return ScoreResult.scorer_error(f"python: could not start the scorer process ({exc})")

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        return ScoreResult.scorer_error(f"python: {message}")

    raw = (completed.stdout or "").strip()
    if not raw:
        return ScoreResult.scorer_error("python: the scorer produced no output")

    try:
        result = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError:
        return ScoreResult.scorer_error(f"python: unparseable result {raw[:120]!r}")

    if not isinstance(result, dict):
        return ScoreResult.scorer_error("python: the scorer must return a dict")
    if "__gaugix_error__" in result:
        return ScoreResult.scorer_error(f"python: {result['__gaugix_error__']}")

    return _normalise(result)


def _normalise(result: dict[str, Any]) -> ScoreResult:
    """Accept what a reasonable person would write, reject what is ambiguous."""
    # A scorer that cannot judge this output must be able to say so. Without
    # this, the only ways out are a wrong verdict or a crash — and "I don't
    # know" is a real answer that has to survive to the item as *unscored*
    # rather than as a fail (D-035).
    declined = result.get("error")
    if isinstance(declined, str) and declined.strip():
        return ScoreResult.scorer_error(f"python: {declined.strip()}")

    passed = result.get("passed")
    if passed is not None and not isinstance(passed, bool):
        passed = bool(passed)

    value = result.get("value")
    if value is not None:
        raw_value = value
        value = finite_float(value)
        if value is None:
            return ScoreResult.scorer_error(
                f"python: `value` must be a finite number, got {raw_value!r}"
            )

    rationale = result.get("rationale")
    rationale = str(rationale) if rationale is not None else ""

    if passed is None and value is None:
        return ScoreResult.scorer_error("python: the result needs `passed` and/or `value`")

    # A value with no explicit verdict: treat the midpoint as the boundary, which
    # is what "score out of 100" conventionally means.
    if passed is None and value is not None:
        passed = value >= 50

    return ScoreResult(passed=passed, value=value, rationale=rationale)
