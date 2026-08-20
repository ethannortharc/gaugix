"""CliHarness against a local fake agent — no real agent, no network, no cost."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    InvokeContext,
    Message,
    ModelSnapshot,
    Provider,
    Role,
)
from gaugix.harness.cli import (
    CliHarness,
    build_env,
    extract_text,
    parse_usage,
    render_command,
    validate_config,
)

FAKE_AGENT = Path(__file__).parent.parent / "fixtures" / "fake_agent.py"

MODEL = ModelSnapshot(name="agent", provider=Provider.fake, model_id="agent")


def case(prompt: str) -> CaseSnapshot:
    return CaseSnapshot(title="cli case", input=[Message(role=Role.user, content=prompt)])


def context(tmp_path: Path, **config: object) -> InvokeContext:
    return InvokeContext(
        run_id=1,
        item_id=1,
        harness_config={
            "command_template": f"{sys.executable} {FAKE_AGENT} {{prompt_file}}",
            "timeout_s": 20,
            **config,
        },
        workdir_root=str(tmp_path / "work"),
    )


# -- config validation ---------------------------------------------------------


def test_a_template_without_the_prompt_file_is_refused():
    """Without {prompt_file} the agent never sees the case — silently scoring zero."""
    with pytest.raises(HarnessError) as excinfo:
        validate_config({"command_template": "model-cli --prompt"})
    assert "{prompt_file}" in str(excinfo.value)


def test_an_empty_template_is_refused():
    with pytest.raises(HarnessError):
        validate_config({})


# -- command construction ------------------------------------------------------


def test_the_prompt_path_is_an_argument_not_a_command(tmp_path: Path):
    """Tokenise-then-substitute: a hostile path cannot become a second command."""
    argv = render_command(
        "agent --file {prompt_file}",
        prompt_file=Path("/tmp/a b; rm -rf ~/prompt.md"),
        workdir=tmp_path,
    )
    assert argv == ["agent", "--file", "/tmp/a b; rm -rf ~/prompt.md"]


def test_workdir_is_substituted_when_the_template_asks_for_it(tmp_path: Path):
    argv = render_command(
        "agent {prompt_file} --cwd {workdir}", prompt_file=Path("p"), workdir=tmp_path
    )
    assert argv[-1] == str(tmp_path)


# -- environment isolation -----------------------------------------------------


def test_the_subprocess_environment_is_an_allowlist(monkeypatch: pytest.MonkeyPatch):
    """An agent under evaluation must not inherit every key on the machine."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-allowed")

    env = build_env({"env_allowlist": ["ANTHROPIC_API_KEY"]})

    assert env.get("ANTHROPIC_API_KEY") == "sk-allowed"
    assert "OPENAI_API_KEY" not in env
    assert "PATH" in env


def test_nothing_is_allowed_through_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    assert "ANTHROPIC_API_KEY" not in build_env({})


def test_subprocess_environment_uses_the_frozen_credential_view(
    monkeypatch: pytest.MonkeyPatch,
):
    from gaugix.config import credential_environment, reset_settings_cache

    monkeypatch.setenv("GAUGIX_FREEZE_CREDENTIALS", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "frozen-value")
    reset_settings_cache()
    try:
        credential_environment()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "rotated-value")

        env = build_env({"env_allowlist": ["ANTHROPIC_API_KEY"]})

        assert env["ANTHROPIC_API_KEY"] == "frozen-value"
    finally:
        reset_settings_cache()


# -- usage parsing -------------------------------------------------------------


def test_usage_is_read_from_a_tool_json_envelope():
    usage = parse_usage('{"usage": {"input_tokens": 10, "output_tokens": 20}}')
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 20


def test_usage_stays_zero_when_the_tool_reports_nothing():
    """An invented token count would flow straight into a cost comparison."""
    usage = parse_usage("just some prose")
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.cost_usd is None


def test_a_reported_cost_is_taken_at_face_value():
    assert parse_usage('{"total_cost_usd": 0.5}').cost_usd == 0.5


def test_plain_stdout_is_the_answer_when_there_is_no_envelope():
    assert extract_text("hello world") == "hello world"


def test_the_answer_is_unwrapped_from_a_json_envelope():
    assert extract_text('{"result": "the answer"}') == "the answer"


# -- the happy path ------------------------------------------------------------


async def test_a_successful_run_returns_output_and_collects_files(tmp_path: Path):
    result = await CliHarness().invoke(case("write a solver"), MODEL, context(tmp_path))

    assert "def solve" in result.output_text
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 34
    assert result.usage.cost_usd == 0.00042
    assert result.usage.latency_ms > 0

    names = {a.filename for a in result.artifacts}
    assert names == {"solution.py", "notes.md"}


async def test_the_prompt_file_is_not_collected_as_an_artifact(tmp_path: Path):
    """We wrote it; collecting it back would be noise in every single attempt."""
    result = await CliHarness().invoke(case("write a solver"), MODEL, context(tmp_path))
    assert all(a.filename != "prompt.md" for a in result.artifacts)


def leftover_scratch_dirs(root: Path) -> list[Path]:
    """Sync helper: the lint rule bans blocking pathlib calls inside async tests."""
    return list(root.iterdir()) if root.is_dir() else []


async def test_the_scratch_directory_is_removed_afterwards(tmp_path: Path):
    """The files are already copied into the store; the scratch dir is litter."""
    ctx = context(tmp_path)
    await CliHarness().invoke(case("write a solver"), MODEL, ctx)

    assert leftover_scratch_dirs(Path(ctx.workdir_root or "")) == []


async def test_artifact_collection_can_be_turned_off(tmp_path: Path):
    result = await CliHarness().invoke(
        case("write a solver"), MODEL, context(tmp_path, collect_artifacts=False)
    )
    assert result.artifacts == []


async def test_a_file_over_the_size_cap_is_skipped_not_truncated(tmp_path: Path):
    """Half a binary is worse than none — the cap protects the disk, not sampling."""
    result = await CliHarness().invoke(
        case("noisy output please"), MODEL, context(tmp_path, max_artifact_bytes=1024)
    )

    names = {a.filename for a in result.artifacts}
    assert "small.txt" in names
    assert "huge.bin" not in names


# -- failure paths -------------------------------------------------------------


async def test_a_non_zero_exit_is_reported_with_its_stderr(tmp_path: Path):
    with pytest.raises(HarnessError) as excinfo:
        await CliHarness().invoke(case("please fail"), MODEL, context(tmp_path))

    assert "could not complete" in str(excinfo.value)
    # The agent's own verdict, not a transport blip — retrying would repeat it.
    assert excinfo.value.retryable is False


async def test_a_timeout_kills_the_process_and_is_retryable(tmp_path: Path):
    with pytest.raises(HarnessError) as excinfo:
        await CliHarness().invoke(case("timeout please"), MODEL, context(tmp_path, timeout_s=0.5))

    assert excinfo.value.kind == "timeout"
    assert excinfo.value.retryable is True


async def test_a_missing_command_is_a_config_error_not_a_provider_error(tmp_path: Path):
    ctx = context(tmp_path)
    ctx.harness_config["command_template"] = "definitely-not-a-real-binary {prompt_file}"

    with pytest.raises(HarnessError) as excinfo:
        await CliHarness().invoke(case("hi"), MODEL, ctx)

    assert excinfo.value.kind == "config"
    assert excinfo.value.retryable is False


async def test_a_named_output_file_that_never_appears_is_a_config_error(tmp_path: Path):
    with pytest.raises(HarnessError) as excinfo:
        await CliHarness().invoke(
            case("write a solver"), MODEL, context(tmp_path, output_file="answer.txt")
        )

    assert "never written" in str(excinfo.value)


async def test_a_named_output_file_is_read_instead_of_stdout(tmp_path: Path):
    result = await CliHarness().invoke(
        case("write a solver"), MODEL, context(tmp_path, output_file="notes.md")
    )
    assert result.output_text.startswith("# Notes")


async def test_the_agent_runs_in_its_own_working_directory(tmp_path: Path):
    """Files land in the scratch dir, not wherever the server happens to be."""
    before = set(os.listdir("."))
    await CliHarness().invoke(case("write a solver"), MODEL, context(tmp_path))
    assert set(os.listdir(".")) == before
