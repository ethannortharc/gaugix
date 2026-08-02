"""Settings: provider key status, pricing table, defaults (PRD F8.1).

Keys are reported as present/absent plus a masked suffix and nothing else. There is
no endpoint that returns key material, by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session, select

from gaugix import __version__
from gaugix.config import get_settings, provider_key_status
from gaugix.db import get_session
from gaugix.domain import Pricing, Provider
from gaugix.models.base import dump_json, load_json
from gaugix.models.cases import AppSetting
from gaugix.models.executors import ModelProfile
from gaugix.pricing import lookup_pricing
from gaugix.schemas.executors import (
    PricingEntry,
    PricingPullRequest,
    PricingPullResult,
    ProviderKeyStatus,
    SettingsRead,
    SettingsUpdate,
)

router = APIRouter(prefix="/settings", tags=["settings"])

SessionDep = Annotated[Session, Depends(get_session)]

KEY_PRICING = "pricing"
KEY_DEFAULT_CONCURRENCY = "default_concurrency"
KEY_DEFAULT_JUDGE_EXECUTOR = "default_judge_executor_id"


def read_setting(session: Session, key: str, fallback: Any = None) -> Any:
    row = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
    if row is None:
        return fallback
    value = load_json(row.value_json, fallback)
    return value


def write_setting(session: Session, key: str, value: Any) -> None:
    row = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
    if row is None:
        row = AppSetting(key=key)
    row.value_json = dump_json(value)
    row.touch()
    session.add(row)


def pricing_table(session: Session) -> dict[str, Pricing]:
    """The user's per-model rates, used when litellm cannot price a model."""
    raw = read_setting(session, KEY_PRICING, []) or []
    table: dict[str, Pricing] = {}
    for entry in raw if isinstance(raw, list) else []:
        try:
            table[str(entry["model_id"])] = Pricing(
                input_per_1m=float(entry["input_per_1m"]),
                output_per_1m=float(entry["output_per_1m"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return table


def read_pricing_entries(session: Session) -> list[PricingEntry]:
    """The stored table, skipping any row that no longer parses."""
    raw = read_setting(session, KEY_PRICING, []) or []
    entries: list[PricingEntry] = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            entries.append(PricingEntry.model_validate(entry))
        except Exception:
            continue
    return entries


@dataclass(slots=True)
class PullTally:
    """What one seeding pass changed, by model id."""

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


def seed_pricing_from_litellm(
    session: Session, model_ids: Sequence[tuple[str, str | None]], *, refresh: bool = False
) -> PullTally:
    """Fill in rates litellm knows about, without ever clobbering the user's own.

    Takes `(model_id, provider)` pairs because the same model id can be filed
    under different names per provider. Does not commit — the caller decides.
    """
    entries = read_pricing_entries(session)
    by_id = {entry.model_id: entry for entry in entries}
    tally = PullTally()

    for model_id, provider in model_ids:
        if not model_id:
            continue
        existing = by_id.get(model_id)
        # A row the user typed is theirs. Only litellm-sourced rows are refreshed,
        # and only when asked — otherwise a pull would silently revert an edit.
        if existing is not None and (existing.source == "manual" or not refresh):
            tally.unchanged.append(model_id)
            continue

        found = lookup_pricing(model_id, provider)
        if found is None:
            tally.not_found.append(model_id)
            continue

        entry = PricingEntry(
            model_id=model_id,
            input_per_1m=found.input_per_1m,
            output_per_1m=found.output_per_1m,
            source="litellm",
        )
        if existing is None:
            entries.append(entry)
            by_id[model_id] = entry
            tally.added.append(model_id)
        elif (existing.input_per_1m, existing.output_per_1m) == (
            entry.input_per_1m,
            entry.output_per_1m,
        ):
            tally.unchanged.append(model_id)
        else:
            entries[entries.index(existing)] = entry
            by_id[model_id] = entry
            tally.updated.append(model_id)

    if tally.added or tally.updated:
        write_setting(session, KEY_PRICING, [e.model_dump() for e in entries])

    return tally


def known_models(session: Session) -> list[tuple[str, str | None]]:
    """Every distinct `(model_id, provider)` a non-archived profile can be billed for.

    Fake models are skipped: they cost nothing by construction, so reporting them
    as "no rates found" would be noise dressed up as a problem.
    """
    profiles = session.exec(select(ModelProfile).where(ModelProfile.archived == False)).all()  # noqa: E712
    seen: set[str] = set()
    pairs: list[tuple[str, str | None]] = []
    for profile in profiles:
        if profile.provider == Provider.fake:
            continue
        if profile.model_id and profile.model_id not in seen:
            seen.add(profile.model_id)
            pairs.append((profile.model_id, profile.provider))
    return pairs


@router.get("", response_model=SettingsRead)
def get_app_settings(session: SessionDep) -> SettingsRead:
    cfg = get_settings()
    entries = read_pricing_entries(session)

    return SettingsRead(
        providers=[
            ProviderKeyStatus(
                provider=provider,
                env_var=str(status["env_var"]),
                present=bool(status["present"]),
                masked=status["masked"],  # type: ignore[arg-type]
            )
            for provider, status in provider_key_status().items()
        ],
        pricing=entries,
        default_concurrency=int(
            read_setting(session, KEY_DEFAULT_CONCURRENCY, cfg.default_concurrency)
        ),
        provider_concurrency=cfg.provider_concurrency,
        default_judge_executor_id=read_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None),
        data_dir=str(cfg.resolved_data_dir),
        db_path=str(cfg.resolved_db_path),
        version=__version__,
    )


@router.patch("", response_model=SettingsRead)
def update_app_settings(payload: SettingsUpdate, session: SessionDep) -> SettingsRead:
    if payload.pricing is not None:
        write_setting(session, KEY_PRICING, [p.model_dump() for p in payload.pricing])
    if payload.default_concurrency is not None:
        write_setting(session, KEY_DEFAULT_CONCURRENCY, payload.default_concurrency)
    if "default_judge_executor_id" in payload.model_dump(exclude_unset=True):
        write_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, payload.default_judge_executor_id)
    session.commit()
    return get_app_settings(session)


@router.post("/pricing/pull", response_model=PricingPullResult)
def pull_pricing(payload: PricingPullRequest, session: SessionDep) -> PricingPullResult:
    """Seed the pricing table from litellm's bundled cost map (no network).

    With no `model_ids`, covers every model a non-archived profile can call —
    which is the case that matters: "price everything I actually use".
    """
    if payload.model_ids is None:
        targets = known_models(session)
    else:
        by_model = dict(known_models(session))
        targets = [(model_id, by_model.get(model_id)) for model_id in payload.model_ids]

    tally = seed_pricing_from_litellm(session, targets, refresh=payload.refresh)
    session.commit()
    return PricingPullResult(
        added=tally.added,
        updated=tally.updated,
        unchanged=tally.unchanged,
        not_found=tally.not_found,
        settings=get_app_settings(session),
    )


@router.get("/providers", response_model=list[ProviderKeyStatus])
def get_provider_status() -> list[ProviderKeyStatus]:
    """Present/absent per provider. Never returns key material."""
    return [
        ProviderKeyStatus(
            provider=provider,
            env_var=str(status["env_var"]),
            present=bool(status["present"]),
            masked=status["masked"],  # type: ignore[arg-type]
        )
        for provider, status in provider_key_status().items()
    ]


@router.post("/backup")
def create_backup_zip() -> Response:
    """Everything that cannot be regenerated, in one zip (PRD F8.2)."""
    from gaugix.backup import create_backup

    path = create_backup()
    return Response(
        content=path.read_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
