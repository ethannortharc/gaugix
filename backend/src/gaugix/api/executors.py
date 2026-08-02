"""Model profiles, harness profiles, executors, and the connection probe (PRD F2)."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, col, func, select

from gaugix.capabilities import capabilities_for
from gaugix.config import PROVIDER_KEY_ENV, read_api_key
from gaugix.db import get_session
from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    HarnessKind,
    InvokeContext,
    Message,
    Provider,
    Role,
)
from gaugix.errors import ConflictError, ValidationError
from gaugix.harness import get as get_harness
from gaugix.models.executors import Executor, HarnessProfile, ModelProfile, default_executor_name
from gaugix.models.runs import RunItem
from gaugix.repo import get_or_404
from gaugix.schemas.common import CountResponse
from gaugix.schemas.executors import (
    ExecutorCreate,
    ExecutorRead,
    ExecutorUpdate,
    HarnessProfileCreate,
    HarnessProfileRead,
    HarnessProfileUpdate,
    ModelCapabilitiesRead,
    ModelProfileCreate,
    ModelProfileRead,
    ModelProfileUpdate,
    TestConnectionResult,
)

router = APIRouter(tags=["executors"])

SessionDep = Annotated[Session, Depends(get_session)]

#: The tiniest possible real request — this probe costs money (PRD F2.2).
PROBE_CASE = CaseSnapshot(
    title="Gaugix connection test",
    input=[Message(role=Role.user, content="Reply with the single word: ok")],
)


def _key_present(profile: ModelProfile) -> bool:
    """Whether the credential this profile needs is actually in the environment."""
    provider = Provider(profile.provider)
    if provider is Provider.fake:
        return True
    env_var = profile.api_key_env or PROVIDER_KEY_ENV.get(str(provider))
    return bool(read_api_key(env_var))


def to_model_read(profile: ModelProfile) -> ModelProfileRead:
    return ModelProfileRead(
        id=profile.id or 0,
        name=profile.name,
        provider=profile.provider,
        model_id=profile.model_id,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        params=profile.params,
        pricing=profile.pricing,
        archived=profile.archived,
        key_present=_key_present(profile),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def to_harness_read(profile: HarnessProfile) -> HarnessProfileRead:
    return HarnessProfileRead(
        id=profile.id or 0,
        name=profile.name,
        kind=profile.kind,
        config=profile.config,
        archived=profile.archived,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def to_executor_read(session: Session, executor: Executor) -> ExecutorRead:
    model = session.get(ModelProfile, executor.model_profile_id)
    harness = session.get(HarnessProfile, executor.harness_profile_id)
    run_count = session.exec(
        select(func.count()).select_from(RunItem).where(RunItem.executor_key == executor.name)
    ).one()
    return ExecutorRead(
        id=executor.id or 0,
        name=executor.name,
        model_profile_id=executor.model_profile_id,
        harness_profile_id=executor.harness_profile_id,
        model_name=model.name if model else "(missing)",
        model_id=model.model_id if model else "",
        provider=model.provider if model else "",
        harness_name=harness.name if harness else "(missing)",
        harness_kind=harness.kind if harness else "",
        overrides=executor.overrides,
        archived=executor.archived,
        run_count=int(run_count),
        created_at=executor.created_at,
        updated_at=executor.updated_at,
    )


# -- model profiles ------------------------------------------------------------


@router.get("/model-profiles", response_model=list[ModelProfileRead])
def list_model_profiles(
    session: SessionDep, response: Response, include_archived: bool = Query(default=False)
) -> list[ModelProfileRead]:
    statement = select(ModelProfile)
    if not include_archived:
        statement = statement.where(col(ModelProfile.archived).is_(False))
    rows = session.exec(statement.order_by(col(ModelProfile.name))).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return [to_model_read(p) for p in rows]


@router.post("/model-profiles", response_model=ModelProfileRead, status_code=201)
def create_model_profile(payload: ModelProfileCreate, session: SessionDep) -> ModelProfileRead:
    if session.exec(select(ModelProfile).where(ModelProfile.name == payload.name)).first():
        raise ConflictError(f"a model profile named {payload.name!r} already exists")
    _validate_model(payload.provider, payload.model_id, payload.base_url)

    profile = ModelProfile(
        name=payload.name,
        provider=str(payload.provider),
        model_id=payload.model_id,
        base_url=payload.base_url,
        api_key_env=payload.api_key_env,
    )
    profile.params = payload.params
    profile.pricing = payload.pricing
    session.add(profile)
    _seed_pricing(session, profile)
    session.commit()
    session.refresh(profile)
    return to_model_read(profile)


@router.get("/model-capabilities", response_model=ModelCapabilitiesRead)
def get_model_capabilities(
    provider: Annotated[Provider, Query()],
    model_id: Annotated[str, Query()] = "",
) -> ModelCapabilitiesRead:
    """Which generation params this model accepts, so the form can offer them.

    Declared above `/model-profiles/{profile_id}` for the usual reason (D-010):
    FastAPI matches in declaration order.
    """
    caps = capabilities_for(model_id, str(provider))
    return ModelCapabilitiesRead(
        model_id=model_id,
        known=caps.known,
        supported=caps.supported or [],
        reasoning_effort=caps.allows("reasoning_effort"),
        temperature=caps.allows("temperature"),
        max_tokens=caps.allows("max_tokens"),
        thinking=caps.allows("thinking"),
        effort_levels=caps.effort_levels,
    )


@router.get("/model-profiles/{profile_id}", response_model=ModelProfileRead)
def get_model_profile(profile_id: int, session: SessionDep) -> ModelProfileRead:
    return to_model_read(get_or_404(session, ModelProfile, profile_id, "Model profile"))


@router.patch("/model-profiles/{profile_id}", response_model=ModelProfileRead)
def update_model_profile(
    profile_id: int, payload: ModelProfileUpdate, session: SessionDep
) -> ModelProfileRead:
    profile = get_or_404(session, ModelProfile, profile_id, "Model profile")
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] != profile.name:
        if session.exec(select(ModelProfile).where(ModelProfile.name == data["name"])).first():
            raise ConflictError(f"a model profile named {data['name']!r} already exists")
        profile.name = data["name"]
    if payload.provider is not None:
        profile.provider = str(payload.provider)
    if "model_id" in data:
        profile.model_id = data["model_id"] or ""
    if "base_url" in data:
        profile.base_url = data["base_url"]
    if "api_key_env" in data:
        profile.api_key_env = data["api_key_env"]
    if payload.params is not None:
        profile.params = payload.params
    if "pricing" in data:
        profile.pricing = payload.pricing
    if payload.archived is not None:
        profile.archived = payload.archived

    _validate_model(Provider(profile.provider), profile.model_id, profile.base_url)
    profile.touch()
    session.add(profile)
    _seed_pricing(session, profile)
    session.commit()
    session.refresh(profile)
    return to_model_read(profile)


@router.delete("/model-profiles/{profile_id}", response_model=CountResponse)
def delete_model_profile(profile_id: int, session: SessionDep) -> CountResponse:
    """Delete when unused; archive when an executor still points at it."""
    profile = get_or_404(session, ModelProfile, profile_id, "Model profile")
    in_use = session.exec(select(Executor).where(Executor.model_profile_id == profile_id)).first()
    if in_use is not None:
        profile.archived = True
        profile.touch()
        session.add(profile)
        session.commit()
        return CountResponse(count=1, message="archived (in use by an executor)")
    session.delete(profile)
    session.commit()
    return CountResponse(count=1, message="deleted")


@router.post("/model-profiles/{profile_id}/test", response_model=TestConnectionResult)
async def test_model_profile(profile_id: int, session: SessionDep) -> TestConnectionResult:
    """Send one tiny request and report latency/usage/cost, or a readable error.

    For `fake` profiles this is simulated and free; for real providers it is a
    genuine (very small) API call.
    """
    profile = get_or_404(session, ModelProfile, profile_id, "Model profile")
    provider = Provider(profile.provider)

    if provider is not Provider.fake and not _key_present(profile):
        env_var = profile.api_key_env or PROVIDER_KEY_ENV.get(str(provider), "?")
        return TestConnectionResult(
            ok=False,
            message=f"No API key found. Set {env_var} in .env and restart the server.",
            error_kind="missing_key",
        )

    kind = HarnessKind.fake if provider is Provider.fake else HarnessKind.direct
    harness = get_harness(kind)
    ctx = InvokeContext(harness_config={}, params=profile.params, timeout_s=30, purpose="probe")

    try:
        result = await harness.invoke(PROBE_CASE, profile.to_snapshot(), ctx)
    except HarnessError as exc:
        return TestConnectionResult(ok=False, message=exc.message, error_kind=exc.kind)
    except Exception as exc:
        return TestConnectionResult(
            ok=False, message=f"{type(exc).__name__}: {exc}", error_kind="unexpected"
        )

    return TestConnectionResult(
        ok=True,
        message="Connection OK",
        latency_ms=result.usage.latency_ms,
        prompt_tokens=result.usage.prompt_tokens,
        completion_tokens=result.usage.completion_tokens,
        cost_usd=result.usage.cost_usd,
        output_preview=result.output_text[:200],
    )


def _seed_pricing(session: Session, profile: ModelProfile) -> None:
    """Fill this model's rates from litellm the first time we see it.

    Best-effort by design: a profile must still save if the cost map has never
    heard of the model. The user then types the rates in Settings, and that row
    is theirs from then on.
    """
    from gaugix.api.settings import seed_pricing_from_litellm

    if not profile.model_id:
        return
    seed_pricing_from_litellm(session, [(profile.model_id, profile.provider)])


def _validate_model(provider: Provider, model_id: str, base_url: str | None) -> None:
    if provider is Provider.fake:
        return
    if not model_id:
        raise ValidationError("model_id is required for non-fake providers")
    if provider is Provider.openai_compatible and not base_url:
        raise ValidationError("base_url is required for openai_compatible providers")


# -- harness profiles ----------------------------------------------------------


@router.get("/harness-profiles", response_model=list[HarnessProfileRead])
def list_harness_profiles(
    session: SessionDep, response: Response, include_archived: bool = Query(default=False)
) -> list[HarnessProfileRead]:
    statement = select(HarnessProfile)
    if not include_archived:
        statement = statement.where(col(HarnessProfile.archived).is_(False))
    rows = session.exec(statement.order_by(col(HarnessProfile.name))).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return [to_harness_read(p) for p in rows]


@router.post("/harness-profiles", response_model=HarnessProfileRead, status_code=201)
def create_harness_profile(
    payload: HarnessProfileCreate, session: SessionDep
) -> HarnessProfileRead:
    if session.exec(select(HarnessProfile).where(HarnessProfile.name == payload.name)).first():
        raise ConflictError(f"a harness named {payload.name!r} already exists")
    _validate_harness(payload.kind, payload.config)

    profile = HarnessProfile(name=payload.name, kind=str(payload.kind))
    profile.config = payload.config
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return to_harness_read(profile)


@router.get("/harness-profiles/{profile_id}", response_model=HarnessProfileRead)
def get_harness_profile(profile_id: int, session: SessionDep) -> HarnessProfileRead:
    return to_harness_read(get_or_404(session, HarnessProfile, profile_id, "Harness profile"))


@router.patch("/harness-profiles/{profile_id}", response_model=HarnessProfileRead)
def update_harness_profile(
    profile_id: int, payload: HarnessProfileUpdate, session: SessionDep
) -> HarnessProfileRead:
    profile = get_or_404(session, HarnessProfile, profile_id, "Harness profile")
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] != profile.name:
        if session.exec(select(HarnessProfile).where(HarnessProfile.name == data["name"])).first():
            raise ConflictError(f"a harness named {data['name']!r} already exists")
        profile.name = data["name"]
    if payload.kind is not None:
        profile.kind = str(payload.kind)
    if payload.config is not None:
        profile.config = payload.config
    if payload.archived is not None:
        profile.archived = payload.archived

    _validate_harness(HarnessKind(profile.kind), profile.config)
    profile.touch()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return to_harness_read(profile)


@router.delete("/harness-profiles/{profile_id}", response_model=CountResponse)
def delete_harness_profile(profile_id: int, session: SessionDep) -> CountResponse:
    profile = get_or_404(session, HarnessProfile, profile_id, "Harness profile")
    in_use = session.exec(select(Executor).where(Executor.harness_profile_id == profile_id)).first()
    if in_use is not None:
        profile.archived = True
        profile.touch()
        session.add(profile)
        session.commit()
        return CountResponse(count=1, message="archived (in use by an executor)")
    session.delete(profile)
    session.commit()
    return CountResponse(count=1, message="deleted")


def _validate_harness(kind: HarnessKind, config: dict[str, object]) -> None:
    if kind is HarnessKind.fake:
        mode = str(config.get("mode", "echo"))
        if mode not in {"echo", "script"}:
            raise ValidationError(f"fake harness mode must be 'echo' or 'script', got {mode!r}")
    if kind is HarnessKind.cli:
        template = str(config.get("command_template", ""))
        if not template:
            raise ValidationError("cli harness requires a command_template")
        if "{prompt_file}" not in template:
            raise ValidationError("command_template must contain {prompt_file}")


# -- executors -----------------------------------------------------------------


@router.get("/executors", response_model=list[ExecutorRead])
def list_executors(
    session: SessionDep, response: Response, include_archived: bool = Query(default=False)
) -> list[ExecutorRead]:
    statement = select(Executor)
    if not include_archived:
        statement = statement.where(col(Executor.archived).is_(False))
    rows = session.exec(statement.order_by(col(Executor.name))).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return [to_executor_read(session, e) for e in rows]


@router.post("/executors", response_model=ExecutorRead, status_code=201)
def create_executor(payload: ExecutorCreate, session: SessionDep) -> ExecutorRead:
    model = get_or_404(session, ModelProfile, payload.model_profile_id, "Model profile")
    harness = get_or_404(session, HarnessProfile, payload.harness_profile_id, "Harness profile")
    name = payload.name or default_executor_name(model.name, harness.name)

    if session.exec(select(Executor).where(Executor.name == name)).first():
        raise ConflictError(f"an executor named {name!r} already exists")

    executor = Executor(
        name=name,
        model_profile_id=payload.model_profile_id,
        harness_profile_id=payload.harness_profile_id,
    )
    executor.overrides = payload.overrides
    session.add(executor)
    session.commit()
    session.refresh(executor)
    return to_executor_read(session, executor)


@router.get("/executors/{executor_id}", response_model=ExecutorRead)
def get_executor(executor_id: int, session: SessionDep) -> ExecutorRead:
    return to_executor_read(session, get_or_404(session, Executor, executor_id, "Executor"))


@router.patch("/executors/{executor_id}", response_model=ExecutorRead)
def update_executor(executor_id: int, payload: ExecutorUpdate, session: SessionDep) -> ExecutorRead:
    executor = get_or_404(session, Executor, executor_id, "Executor")
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] != executor.name:
        if session.exec(select(Executor).where(Executor.name == data["name"])).first():
            raise ConflictError(f"an executor named {data['name']!r} already exists")
        executor.name = data["name"]
    if payload.model_profile_id is not None:
        get_or_404(session, ModelProfile, payload.model_profile_id, "Model profile")
        executor.model_profile_id = payload.model_profile_id
    if payload.harness_profile_id is not None:
        get_or_404(session, HarnessProfile, payload.harness_profile_id, "Harness profile")
        executor.harness_profile_id = payload.harness_profile_id
    if payload.overrides is not None:
        executor.overrides = payload.overrides
    if payload.archived is not None:
        executor.archived = payload.archived

    executor.touch()
    session.add(executor)
    session.commit()
    session.refresh(executor)
    return to_executor_read(session, executor)


@router.delete("/executors/{executor_id}", response_model=CountResponse)
def delete_executor(executor_id: int, session: SessionDep) -> CountResponse:
    """Executors with runs are archived, never deleted — past runs must stay readable."""
    executor = get_or_404(session, Executor, executor_id, "Executor")
    has_runs = session.exec(select(RunItem).where(RunItem.executor_key == executor.name)).first()
    if has_runs is not None:
        executor.archived = True
        executor.touch()
        session.add(executor)
        session.commit()
        return CountResponse(count=1, message="archived (has runs)")
    session.delete(executor)
    session.commit()
    return CountResponse(count=1, message="deleted")


__all__ = ["os", "router"]
