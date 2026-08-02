"""Running a program a model wrote (PRD F6.4).

This is the most dangerous thing Gaugix can do, so it is the most constrained:

* **Never automatic.** Execution requires a `confirm_token` that the caller can
  only obtain by first asking what would run — a two-step handshake, so a stray
  click, a replayed URL or a prompt-injected fetch cannot start a process.
* **The token names the exact command.** It is an HMAC over
  `(artifact id, argv, working directory)`, so a token obtained for
  `python solution.py` cannot be used to run anything else.
* **Bounded.** Runs in the artifact's own directory, with a hard timeout, a
  minimal environment, and captured output. Same no-shell rule as the CLI
  harness: the command is a token list, never a shell string.

What this is *not*: a sandbox. The program runs as the user, with the user's
filesystem. That is inherent to "run the thing the model wrote on my machine",
and the UI says so in the confirm dialog rather than implying protection that
does not exist (compare D-020, the same honesty applied to the python scorer).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from gaugix.artifacts import store
from gaugix.models.artifacts import Artifact

DEFAULT_TIMEOUT_S = 30.0
MAX_OUTPUT_CHARS = 100_000

#: Extension → how to run it. Anything absent is not executable by us, which is
#: a refusal rather than a guess at an interpreter.
RUNNERS: dict[str, list[str]] = {
    ".py": ["python3"],
    ".js": ["node"],
    ".mjs": ["node"],
    ".sh": ["bash"],
    ".rb": ["ruby"],
    ".go": ["go", "run"],
}


@dataclass(slots=True)
class ExecPlan:
    """Exactly what would run, shown to the user before anything happens."""

    argv: list[str]
    workdir: str
    timeout_s: float
    confirm_token: str

    @property
    def command(self) -> str:
        return " ".join(self.argv)


@dataclass(slots=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


class NotExecutable(ValueError):
    """This artifact has no runner we are willing to guess at."""


def _secret() -> bytes:
    """Per-process signing key.

    Deliberately not persisted: a restart invalidates every outstanding token,
    which is the right default for something this dangerous.
    """
    global _SECRET
    if _SECRET is None:
        _SECRET = os.urandom(32)
    return _SECRET


_SECRET: bytes | None = None


def _sign(argv: list[str], workdir: str, artifact_id: int) -> str:
    payload = json.dumps(
        {"argv": argv, "workdir": workdir, "artifact_id": artifact_id}, sort_keys=True
    ).encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def plan(artifact: Artifact, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> ExecPlan:
    """What running this artifact would mean, plus the token that authorises it."""
    path = store.resolve(artifact.rel_path)
    suffix = Path(artifact.filename).suffix.lower()
    runner = RUNNERS.get(suffix)
    if runner is None:
        raise NotExecutable(
            f"Gaugix will not guess how to run {artifact.filename!r}. "
            f"Runnable extensions: {', '.join(sorted(RUNNERS))}"
        )

    workdir = str(path.parent)
    argv = [*runner, str(path)]
    return ExecPlan(
        argv=argv,
        workdir=workdir,
        timeout_s=timeout_s,
        confirm_token=_sign(argv, workdir, artifact.id or 0),
    )


def verify(plan_: ExecPlan, token: str, artifact_id: int) -> bool:
    """Whether this token authorises exactly this command."""
    expected = _sign(plan_.argv, plan_.workdir, artifact_id)
    return hmac.compare_digest(expected, token)


async def execute(plan_: ExecPlan) -> ExecResult:
    """Run it. Assumes the caller has already verified the token."""
    started = time.perf_counter()
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR") if key in os.environ}

    try:
        process = await asyncio.create_subprocess_exec(
            *plan_.argv,
            cwd=plan_.workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        return ExecResult(exit_code=127, stdout="", stderr=str(exc), duration_ms=0)

    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout=plan_.timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        return ExecResult(
            exit_code=124,
            stdout="",
            stderr=f"killed after {plan_.timeout_s:g}s",
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=True,
        )

    return ExecResult(
        exit_code=process.returncode or 0,
        stdout=out.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS],
        stderr=err.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
