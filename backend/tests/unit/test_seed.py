"""Demo seed data: valid, idempotent, and guarded against accidental wipes."""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from gaugix import seed
from gaugix.caseio import parse_cases
from gaugix.models.cases import EvalCase, EvalSet, SetMembership
from gaugix.schemas.cases import CaseIO


@pytest.mark.parametrize(
    "payload", [*seed.GUARDRAIL_CASES, *seed.CODING_CASES], ids=lambda p: p["title"]
)
def test_every_seed_case_matches_the_canonical_schema(payload):
    """Seed content must survive the same validation as a user import."""
    case = CaseIO.model_validate(payload)
    assert case.title
    assert case.input


def test_seed_cases_survive_a_jsonl_round_trip():
    import json

    payloads = [*seed.GUARDRAIL_CASES, *seed.CODING_CASES]
    content = "".join(json.dumps(p) + "\n" for p in payloads)
    cases, errors = parse_cases(content)
    assert errors == []
    assert len(cases) == len(payloads)


def test_seed_creates_both_sets_with_ordered_cases(engine):
    with Session(engine) as session:
        result = seed.seed_database(session)

    assert result["cases"] == len(seed.GUARDRAIL_CASES) + len(seed.CODING_CASES)

    with Session(engine) as session:
        sets = session.exec(select(EvalSet)).all()
        assert {s.name for s in sets} == {"Guardrail regression", "Go & concurrency benchmark"}

        guardrails = next(s for s in sets if s.name == "Guardrail regression")
        rows = session.exec(
            select(SetMembership).where(SetMembership.set_id == guardrails.id)
        ).all()
        assert sorted(r.position for r in rows) == list(range(len(seed.GUARDRAIL_CASES)))


def test_seeding_twice_does_not_duplicate(engine):
    with Session(engine) as session:
        seed.seed_database(session)
        seed.seed_database(session)

    with Session(engine) as session:
        assert len(session.exec(select(EvalSet)).all()) == 2
        assert len(session.exec(select(EvalCase)).all()) == len(seed.GUARDRAIL_CASES) + len(
            seed.CODING_CASES
        )


def test_the_guardrail_set_carries_a_default_scoring_config(engine):
    with Session(engine) as session:
        seed.seed_database(session)
        guardrails = session.exec(
            select(EvalSet).where(EvalSet.name == "Guardrail regression")
        ).one()
        assert guardrails.default_scoring
        assert guardrails.default_scoring[0].type == "json_schema"


def test_the_seed_includes_a_human_scored_case(engine):
    """PRD F4.4's review queue needs something in it on a fresh install."""
    with Session(engine) as session:
        seed.seed_database(session)
        cases = session.exec(select(EvalCase)).all()
        human_scored = [c for c in cases if any(s.type == "human" for s in c.scoring)]
        assert len(human_scored) == 1


def test_the_seed_includes_benign_lookalikes(engine):
    """A guardrail set without false-positive cases measures only half the story."""
    titles = [c["title"] for c in seed.GUARDRAIL_CASES]
    assert sum("Benign lookalike" in t for t in titles) >= 2


def test_seed_command_refuses_without_the_force_flag(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("GAUGIX_FORCE", raising=False)
    marker = tmp_path / "data" / "precious.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("do not delete me")
    monkeypatch.setenv("GAUGIX_DATA_DIR", str(tmp_path / "data"))

    from gaugix.config import reset_settings_cache

    reset_settings_cache()

    assert seed.seed_command() == 2
    assert "GAUGIX_FORCE=1" in capsys.readouterr().err
    assert marker.exists(), "a refused seed must not touch the data directory"


def test_seed_ships_runnable_executors(engine):
    """A fresh install should be able to run something without any setup."""
    from gaugix.models.executors import Executor

    with Session(engine) as session:
        result = seed.seed_database(session)
        executors = session.exec(select(Executor)).all()

    names = {e.name for e in executors}
    assert names == {"guardrail-sim @ fake", "code-sim @ fake", "judge @ fake"}
    assert result["judge_executor_id"] > 0


def test_seeding_executors_twice_does_not_duplicate(engine):
    from gaugix.models.executors import Executor

    with Session(engine) as session:
        seed.seed_database(session)
        seed.seed_database(session)
        assert len(session.exec(select(Executor)).all()) == 3


def test_the_guardrail_simulator_answers_every_seeded_case(engine):
    """The demo run must produce real verdicts, not a wall of failures."""
    import asyncio

    from gaugix.domain import CaseSnapshot, InvokeContext, Message, ModelSnapshot, Provider, Role
    from gaugix.harness.fake import FakeHarness

    model = ModelSnapshot(name="sim", provider=Provider.fake, model_id="sim")
    for payload in seed.GUARDRAIL_CASES:
        case = CaseSnapshot(
            title=payload["title"],
            input=[Message(role=Role(m["role"]), content=m["content"]) for m in payload["input"]],
        )
        result = asyncio.run(
            FakeHarness().invoke(
                case, model, InvokeContext(harness_config=seed.GUARDRAIL_SIM_CONFIG)
            )
        )
        assert '"action"' in result.output_text, payload["title"]


def test_the_seeded_judge_always_returns_parseable_json():
    """A judge that cannot be parsed would make the demo look broken."""
    import json

    from gaugix.scoring.judge import parse_verdict

    for rule in seed.JUDGE_CONFIG["script"]:
        assert parse_verdict(rule["response"], "1-5") is not None
    assert parse_verdict(seed.JUDGE_CONFIG["default_response"], "1-5") is not None
    assert json.loads(seed.JUDGE_CONFIG["default_response"])


def test_the_seeded_judge_is_actually_named_as_the_default(session):
    """Seeding a judge and not wiring it left the demo grading its own homework."""
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, read_setting
    from gaugix.seed import seed_database

    ids = seed_database(session)

    assert read_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None) == ids["judge_executor_id"]


def test_reseeding_does_not_steal_back_a_judge_the_user_chose(session):
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, read_setting, write_setting
    from gaugix.seed import seed_database

    write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, 999)
    session.commit()

    seed_database(session)

    assert read_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None) == 999
