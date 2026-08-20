"""CliHarness — evaluating an agent you invoke as a command (ARCHITECTURE §4).

The reason this exists: a coding agent is not a chat completion. It reads files,
writes files, runs tools, and the *files it leaves behind* are the answer. So an
attempt here is a subprocess in a scratch directory, and everything it created
becomes an artifact you can open.

Configuration (`harness_profile.config_json`):

```jsonc
{
  "command_template": "model-cli --prompt-file {prompt_file} --output-format json",
  "timeout_s": 300,
  "collect_artifacts": true,
  "max_artifact_bytes": 20971520,
  "env_allowlist": ["ANTHROPIC_API_KEY"],   // names only; values come from the environment
  "output_file": null                         // read stdout unless a file is named
}
```

Three deliberate constraints:

* **The command is a template, not a shell string.** It is tokenised with
  `shlex.split` and run via `create_subprocess_exec` — no shell, so a prompt
  containing `; rm -rf ~` is an argument, not a command.
* **The environment is an allowlist.** A subprocess inherits nothing except
  PATH, HOME and the variables the profile names, so an agent under evaluation
  cannot read every key on the machine because it happened to be launched here.
* **Usage is parsed, never invented.** If the tool reports tokens in its JSON
  envelope, we use them; otherwise usage stays zero and cost stays unknown,
  which the UI shows as "n/a" rather than a flattering $0.00.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from gaugix.artifacts import store
from gaugix.config import credential_environment
from gaugix.domain import (
    ArtifactIn,
    CaseSnapshot,
    HarnessError,
    HarnessKind,
    InvocationResult,
    InvokeContext,
    ModelSnapshot,
    Usage,
)

PROMPT_FILENAME = "prompt.md"
DEFAULT_TIMEOUT_S = 300.0

#: Always passed through — without these most tools cannot even start.
BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SHELL", "USER")


def validate_config(config: dict[str, Any]) -> str:
    """Check a cli harness config, returning the command template."""
    template = str(config.get("command_template") or "").strip()
    if not template:
        raise HarnessError("cli harness needs a command_template", retryable=False, kind="config")
    if "{prompt_file}" not in template:
        raise HarnessError(
            "command_template must contain {prompt_file} — otherwise the agent "
            "never receives the case",
            retryable=False,
            kind="config",
        )
    return template


def build_env(config: dict[str, Any]) -> dict[str, str]:
    """A minimal environment plus the names this profile allows through."""
    environment = credential_environment()
    env = {key: environment[key] for key in BASE_ENV_KEYS if key in environment}
    allowlist = config.get("env_allowlist") or []
    for name in allowlist if isinstance(allowlist, list) else []:
        value = environment.get(str(name))
        if value is not None:
            env[str(name)] = value
    return env


def render_command(template: str, *, prompt_file: Path, workdir: Path) -> list[str]:
    """Tokenise first, substitute second — so a path can never inject an argument."""
    argv = shlex.split(template)
    return [
        token.replace("{prompt_file}", str(prompt_file)).replace("{workdir}", str(workdir))
        for token in argv
    ]


def parse_usage(text: str) -> Usage:
    """Token counts if the tool reported them; zeros if it did not.

    Common JSON command envelopes put them under `usage`. Anything we cannot
    read stays zero rather than being estimated — an invented token count would
    flow straight into a cost comparison.
    """
    usage = Usage()
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return usage
    if not isinstance(payload, dict):
        return usage

    raw = payload.get("usage")
    if isinstance(raw, dict):
        for key, target in (
            ("input_tokens", "prompt_tokens"),
            ("prompt_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("completion_tokens", "completion_tokens"),
        ):
            value = raw.get(key)
            if isinstance(value, int | float):
                setattr(usage, target, int(value))

    # Cost is reported at the top level, independently of whether the tool also
    # broke out token counts — reading it only inside the `usage` branch lost it.
    cost = payload.get("total_cost_usd", payload.get("cost_usd"))
    if isinstance(cost, int | float) and not isinstance(cost, bool):
        usage.cost_usd = float(cost)
    return usage


def extract_text(stdout: str) -> str:
    """The answer itself, unwrapped from a JSON envelope when there is one."""
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout
    if isinstance(payload, dict):
        for key in ("result", "text", "output", "content", "response"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return stdout


class CliHarness:
    """Runs a local command per attempt and collects what it leaves behind."""

    kind = str(HarnessKind.cli)

    async def invoke(
        self, case: CaseSnapshot, model: ModelSnapshot, ctx: InvokeContext
    ) -> InvocationResult:
        config = ctx.harness_config or {}
        template = validate_config(config)
        timeout_s = float(ctx.timeout_s or config.get("timeout_s") or DEFAULT_TIMEOUT_S)

        root = Path(ctx.workdir_root) if ctx.workdir_root else store.artifacts_root() / "tmp"
        workdir = root / uuid.uuid4().hex
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            prompt_file = workdir / PROMPT_FILENAME
            prompt_file.write_text(case.prompt_text(), encoding="utf-8")

            argv = render_command(template, prompt_file=prompt_file, workdir=workdir)
            if not argv:
                raise HarnessError(
                    "command_template is empty after parsing", retryable=False, kind="config"
                )

            stdout, stderr, code, latency_ms = await self._run(argv, workdir, config, timeout_s)

            if code != 0:
                raise HarnessError(
                    f"command exited {code}: {(stderr or stdout)[:400]}",
                    # A non-zero exit is the agent's verdict on itself, not a
                    # transport blip — retrying would usually just repeat it.
                    retryable=False,
                    kind="provider_error",
                )

            output_text = self._read_output(config, workdir, stdout)
            usage = parse_usage(stdout)
            usage.latency_ms = latency_ms

            artifacts = self._collect(config, workdir, stdout)
            return InvocationResult(
                output_text=output_text,
                messages=[
                    {"role": "user", "content": case.prompt_text()},
                    {"role": "assistant", "content": output_text},
                ],
                usage=usage,
                artifacts=artifacts,
                raw={"command": " ".join(argv), "exit_code": code, "workdir": str(workdir)},
            )
        finally:
            # The files are already copied into the artifact store; the scratch
            # directory itself is not worth keeping.
            shutil.rmtree(workdir, ignore_errors=True)

    async def _run(
        self, argv: list[str], workdir: Path, config: dict[str, Any], timeout_s: float
    ) -> tuple[str, str, int, int]:
        started = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(workdir),
                env=build_env(config),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise HarnessError(
                f"command not found: {argv[0]!r}", retryable=False, kind="config"
            ) from exc
        except OSError as exc:
            raise HarnessError(str(exc), retryable=False, kind="config") from exc

        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise HarnessError(
                f"command timed out after {timeout_s:g}s", retryable=True, kind="timeout"
            ) from None

        latency_ms = int((time.perf_counter() - started) * 1000)
        return (
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
            process.returncode or 0,
            latency_ms,
        )

    def _read_output(self, config: dict[str, Any], workdir: Path, stdout: str) -> str:
        """stdout, unless the profile designates a file the agent writes instead."""
        named = config.get("output_file")
        if named:
            path = workdir / store.safe_filename(str(named))
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
            raise HarnessError(
                f"output_file {named!r} was never written by the command",
                retryable=False,
                kind="config",
            )
        return extract_text(stdout)

    def _collect(self, config: dict[str, Any], workdir: Path, stdout: str) -> list[ArtifactIn]:
        if not config.get("collect_artifacts", True):
            return []
        max_bytes = int(config.get("max_artifact_bytes") or store.DEFAULT_MAX_BYTES)
        collected = store.collect_workdir(workdir, skip={PROMPT_FILENAME}, max_bytes=max_bytes)
        return [
            ArtifactIn(
                kind="workdir_file",
                filename=name,
                mime="application/octet-stream",
                data=data,
            )
            for name, data in collected
        ]
