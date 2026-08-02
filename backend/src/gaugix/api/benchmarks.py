"""Benchmark catalogue endpoints: browse, preview, install.

`GET` is always free and offline. The only call that can reach the network is
`POST /benchmarks/{slug}/install` with `scope="full"`, and `/preview` exists so
the UI can show the exact URL, size and caveats *before* anyone commits to it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, func, select

from gaugix import benchmarks
from gaugix.api.cases import create_cases
from gaugix.benchmarks.catalog import Benchmark
from gaugix.db import get_session
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.cases import EvalSet, SetMembership
from gaugix.schemas.benchmarks import (
    BenchmarkDetail,
    BenchmarkMethod,
    BenchmarkSource,
    BenchmarkSummary,
    InstalledSetRef,
    InstallPreview,
    InstallRequest,
    InstallResult,
)

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

SessionDep = Annotated[Session, Depends(get_session)]


def _require(slug: str) -> Benchmark:
    entry = benchmarks.get(slug)
    if entry is None:
        raise NotFoundError(f"no benchmark with slug {slug!r}")
    return entry


def _source(entry: Benchmark) -> BenchmarkSource | None:
    if entry.source is None:
        return None
    return BenchmarkSource(
        url=entry.source.url,
        host=entry.source.host,
        encoding=entry.source.encoding,
        approx_bytes=entry.source.approx_bytes,
        revision=entry.source.revision,
        sha256=entry.source.sha256,
        expected_rows=entry.source.expected_rows,
    )


def _method(entry: Benchmark) -> BenchmarkMethod:
    return BenchmarkMethod(
        fidelity=entry.method.fidelity,
        comparable=entry.method.comparable,
        deviations=list(entry.method.deviations),
        version=entry.method.version,
    )


def _installed(session: Session, slug: str) -> list[InstalledSetRef]:
    """Sets already installed from this benchmark, with their live case counts."""
    sets = benchmarks.installed_sets(session, slug)
    if not sets:
        return []
    ids = [s.id for s in sets if s.id is not None]
    counts = dict(
        session.exec(
            select(SetMembership.set_id, func.count())
            .where(col(SetMembership.set_id).in_(ids))
            .group_by(col(SetMembership.set_id))
        ).all()
    )
    return [
        InstalledSetRef(id=s.id or 0, name=s.name, case_count=int(counts.get(s.id, 0)))
        for s in sets
        if s.id is not None
    ]


def _summary(session: Session, entry: Benchmark) -> BenchmarkSummary:
    return BenchmarkSummary(
        slug=entry.slug,
        name=entry.name,
        publisher=entry.publisher,
        year=entry.year,
        licence=entry.licence,
        task=entry.task,
        summary=entry.summary,
        full_size=entry.full_size,
        sample_size=len(entry.sample_rows()),
        tags=list(entry.tags),
        requires_judge=entry.requires_judge,
        requires_code_execution=entry.requires_code_execution,
        method=_method(entry),
        installed=_installed(session, entry.slug),
    )


@router.get("", response_model=list[BenchmarkSummary])
def list_benchmarks(session: SessionDep) -> list[BenchmarkSummary]:
    """The catalogue. Reads bundled files only — never the network."""
    return [_summary(session, entry) for entry in benchmarks.CATALOG]


@router.get("/{slug}", response_model=BenchmarkDetail)
def get_benchmark(slug: str, session: SessionDep) -> BenchmarkDetail:
    """Everything about one benchmark, including real sample cases to read.

    The samples are built through the same adapter an install uses, so what you
    read here — prompt wording, scorer, tags — is exactly what you would get.
    """
    entry = _require(slug)
    return BenchmarkDetail(
        **_summary(session, entry).model_dump(),
        description=entry.description,
        what_it_measures=entry.what_it_measures,
        caveats=list(entry.caveats),
        scoring_note=entry.scoring_note,
        languages=list(entry.languages),
        homepage=entry.homepage,
        licence_url=entry.licence_url,
        licence_note=entry.licence_note,
        paper=entry.paper,
        source=_source(entry),
        sample_cases=entry.sample_cases(),
    )


@router.post("/{slug}/preview", response_model=InstallPreview)
def preview_install(slug: str, payload: InstallRequest, session: SessionDep) -> InstallPreview:
    """What installing would do — name clashes, caveats, and the URL involved."""
    entry = _require(slug)
    plan = benchmarks.plan_install(
        session,
        entry,
        scope=payload.scope,
        set_name=payload.set_name,
        # Preview must describe the code-execution benchmark rather than refuse
        # it: the acknowledgement belongs on the install, after reading this.
        accept_code_execution=True,
    )
    count = plan.case_count if payload.limit is None else min(plan.case_count, payload.limit)
    warnings = list(plan.warnings)
    if payload.limit is not None and payload.limit < plan.case_count:
        warnings.insert(
            0,
            f"Installing {count} of {plan.case_count} cases"
            + (
                f", sampled at random with seed {payload.sample_seed}."
                if payload.sample_seed is not None
                else " — the first ones in file order, which is not a random sample. "
                "Set a seed to draw one."
            ),
        )
    return InstallPreview(
        slug=entry.slug,
        scope=plan.scope,
        set_name=plan.set_name,
        case_count=count,
        warnings=warnings,
        source=_source(entry) if plan.scope == benchmarks.FULL else None,
        requires_judge=entry.requires_judge,
        requires_code_execution=entry.requires_code_execution,
        method=_method(entry),
    )


@router.post("/{slug}/install", response_model=InstallResult, status_code=201)
def install_benchmark(slug: str, payload: InstallRequest, session: SessionDep) -> InstallResult:
    """Install a benchmark as a new eval set.

    `scope="sample"` is offline. `scope="full"` makes one HTTPS GET to the URL
    this benchmark's detail page shows — the only outbound request Gaugix makes.
    """
    entry = _require(slug)
    plan = benchmarks.plan_install(
        session,
        entry,
        scope=payload.scope,
        set_name=payload.set_name,
        accept_code_execution=payload.accept_code_execution,
    )
    cases, fetched = benchmarks.load_cases(
        entry, plan.scope, limit=payload.limit, seed=payload.sample_seed
    )

    # A dataset that no longer matches its checksum is not the one this page
    # describes: its caveats, its size and its comparability claim are all
    # about a different version. Importing it under that description with only
    # a warning was the quiet failure D-050 set out to prevent (D-059).
    if fetched is not None and fetched.drift and not payload.accept_drift:
        raise ValidationError(
            "This download does not match the dataset the catalogue describes. "
            + " ".join(fetched.drift)
            + " Resend with accept_drift=true to install it anyway.",
            details={"drift": fetched.drift},
        )

    eval_set = EvalSet(
        name=plan.set_name,
        description=(
            f"{entry.name} — {entry.summary} Installed from the Gaugix catalogue "
            f"({entry.method.fidelity})."
        ),
    )
    eval_set.tags = benchmarks.set_tags(entry, plan.scope)
    session.add(eval_set)
    session.flush()

    # Provenance is written after the cases exist, because it fingerprints
    # exactly which ones landed — that is what later tells a modified set from
    # the one that was installed (D-056).
    created = create_cases(session, cases, set_id=eval_set.id)
    record = benchmarks.provenance(
        entry,
        plan.scope,
        imported=len(cases),
        seed=payload.sample_seed,
        fetched=fetched,
        case_ids=[c.id or 0 for c in created],
        case_updated_at=max((c.updated_at.isoformat() for c in created), default=""),
    )
    eval_set.provenance = record
    session.add(eval_set)
    session.commit()
    session.refresh(eval_set)

    # Drift first: "this is not the dataset the catalogue describes" outranks
    # every standing caveat about the benchmark itself.
    warnings = (fetched.drift if fetched else []) + list(plan.warnings)
    return InstallResult(
        ok=True,
        set_id=eval_set.id or 0,
        set_name=eval_set.name,
        imported=len(cases),
        scope=plan.scope,
        warnings=warnings,
        provenance=record,
    )
