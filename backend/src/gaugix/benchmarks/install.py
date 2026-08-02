"""Installing a catalogue benchmark as an eval set.

Two scopes, and the difference between them is the whole design:

* **sample** reads rows committed to this repo. No network, works on a plane,
  and every test in the suite uses it.
* **full** performs exactly one outbound HTTPS GET, to the URL the catalogue
  entry names and the UI shows you before you press the button.

Gaugix is a local-first tool with no telemetry, and a dataset download is the
only request it will ever make on your behalf. So it is explicit, one host, one
URL, no redirects to anywhere else, and never automatic — nothing here runs
unless a person pressed *Install full* (D-034).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlmodel import Session, col, select

from gaugix.benchmarks.catalog import (
    HTTP_CSV,
    HTTP_JSONL,
    HTTP_JSONL_GZ,
    Benchmark,
    InstallPlan,
    get,
)
from gaugix.errors import ValidationError
from gaugix.models.cases import EvalSet
from gaugix.schemas.cases import CaseIO

SAMPLE = "sample"
FULL = "full"
SCOPES = (SAMPLE, FULL)

#: A dataset download is a foreground action a user is waiting on. Long enough
#: for a few megabytes on a slow line, short enough to fail rather than hang.
FETCH_TIMEOUT_S = 60.0
#: Refuse a body large enough to suggest the URL now points at something else.
MAX_BODY_BYTES = 64 * 1024 * 1024
#: Same-host hops only, and few of them. Blob stores redirect to sign a URL;
#: nothing legitimate needs a chain.
MAX_REDIRECTS = 3


def plan_install(
    session: Session,
    benchmark: Benchmark,
    *,
    scope: str,
    set_name: str | None = None,
    accept_code_execution: bool = False,
) -> InstallPlan:
    """Validate an install and describe it, without fetching or writing anything."""
    if scope not in SCOPES:
        raise ValidationError(f"scope must be one of {', '.join(SCOPES)}")
    if scope == FULL and benchmark.source is None:
        raise ValidationError(f"{benchmark.name} has no downloadable source")
    if benchmark.requires_code_execution and not accept_code_execution:
        raise ValidationError(
            f"Scoring {benchmark.name} runs model-written code on this machine, outside any "
            "sandbox. Install it only if you accept that — resend with "
            "accept_code_execution=true."
        )

    name = (set_name or _default_set_name(benchmark, scope)).strip()
    if not name:
        raise ValidationError("the set needs a name")
    if session.exec(select(EvalSet).where(EvalSet.name == name)).first() is not None:
        raise ValidationError(
            f"a set called {name!r} already exists — rename it, or give this install another name"
        )

    warnings = list(benchmark.caveats)
    if scope == SAMPLE:
        warnings.insert(
            0,
            f"This installs {len(benchmark.sample_rows())} sample cases bundled with Gaugix, "
            f"not the full {benchmark.full_size}. Numbers from it are a smoke test, not a result.",
        )
    return InstallPlan(
        benchmark=benchmark,
        scope=scope,
        case_count=len(benchmark.sample_rows()) if scope == SAMPLE else benchmark.full_size,
        set_name=name,
        warnings=warnings,
    )


def _default_set_name(benchmark: Benchmark, scope: str) -> str:
    return f"{benchmark.name} (sample)" if scope == SAMPLE else benchmark.name


@dataclass(slots=True)
class Fetched:
    """A downloaded dataset with everything needed to say which one it was."""

    rows: list[dict[str, Any]]
    sha256: str
    byte_count: int
    #: Empty when the checksum matched or none was declared; otherwise what went
    #: wrong, so the install can warn rather than silently import a new dataset.
    drift: list[str] = field(default_factory=list)


def load_cases(
    benchmark: Benchmark, scope: str, *, limit: int | None = None, seed: int | None = None
) -> tuple[list[CaseIO], Fetched | None]:
    """The cases an install would create. Only `scope='full'` touches the network."""
    fetched = None if scope == SAMPLE else fetch(benchmark)
    rows = benchmark.sample_rows() if fetched is None else fetched.rows
    rows = take(rows, limit, seed)
    cases = benchmark.adapter(rows)
    if not cases:
        raise ValidationError(
            f"{benchmark.name} produced no usable cases — the source file's shape may have changed"
        )
    return cases, fetched


def take(rows: list[dict[str, Any]], limit: int | None, seed: int | None) -> list[dict[str, Any]]:
    """The first `limit` rows, or a reproducible random sample of that size.

    A benchmark's file order is rarely arbitrary — GSM8K's is roughly by
    difficulty, SimpleQA's clusters by topic — so the first 100 rows are not a
    sample of the set. A seeded shuffle is, and recording the seed makes the
    same 100 reachable again (D-051).
    """
    if limit is None or limit >= len(rows):
        return rows
    if seed is None:
        return rows[:limit]
    order = random.Random(seed).sample(range(len(rows)), limit)
    return [rows[i] for i in sorted(order)]


def fetch(benchmark: Benchmark) -> Fetched:
    """One HTTPS GET to the catalogue's declared URL, decoded and identified."""
    source = benchmark.source
    if source is None:  # pragma: no cover — plan_install rejects this first
        raise ValidationError(f"{benchmark.name} has no downloadable source")

    try:
        body = _get_within_host(source.url, source.host)
    except httpx.HTTPStatusError as exc:
        raise ValidationError(
            f"{source.host} answered {exc.response.status_code} for {benchmark.name}. "
            "The dataset may have moved; the sample install still works offline."
        ) from exc
    except httpx.HTTPError as exc:
        raise ValidationError(
            f"could not reach {source.host} ({exc}). The sample install works without network."
        ) from exc

    if len(body) > MAX_BODY_BYTES:
        raise ValidationError(
            f"{source.host} returned {len(body) / 1e6:.0f} MB, far more than the "
            f"~{source.approx_bytes / 1e6:.1f} MB expected — refusing to import it."
        )

    digest = hashlib.sha256(body).hexdigest()
    rows = decode_rows(body, source.encoding)
    return Fetched(
        rows=rows, sha256=digest, byte_count=len(body), drift=_drift(source, digest, rows)
    )


def _get_within_host(url: str, host: str) -> bytes:
    """One GET, following redirects only while they stay on the declared host.

    The UI promises "a single HTTPS GET to this address, and nothing else".
    `follow_redirects=True` quietly made that untrue: a redirect could send the
    request to any host at all, and the page would still be showing the
    original URL as the only thing contacted. Same-host hops are allowed —
    blob stores use them for signing — and a hop elsewhere is refused (D-059).
    """
    from urllib.parse import urlparse

    with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = client.get(current)
            if not response.is_redirect:
                response.raise_for_status()
                return response.content

            target = str(response.headers.get("location") or "")
            landing = urlparse(target if "://" in target else f"https://{host}{target}")
            if landing.hostname and landing.hostname != host:
                raise ValidationError(
                    f"{host} redirected to {landing.hostname}, which this benchmark does not "
                    "declare. Gaugix contacts one host per install and refuses to follow a "
                    "dataset somewhere else."
                )
            current = landing.geturl()

    raise ValidationError(f"{host} redirected more than {MAX_REDIRECTS} times — giving up.")


def _drift(source: Any, digest: str, rows: list[dict[str, Any]]) -> list[str]:
    """How the download differs from the dataset the catalogue describes.

    A warning rather than a refusal. The file that arrives *is* the current
    dataset; what must not happen is importing it under a description of a
    different one, which is how TruthfulQA came to be described as 817
    questions while shipping 790 (D-050).
    """
    problems: list[str] = []
    if source.sha256 and digest != source.sha256:
        problems.append(
            f"The download's checksum is {digest[:12]}…, not the {source.sha256[:12]}… this "
            "catalogue entry describes. The dataset has changed since Gaugix last checked, so "
            "its caveats and size may be out of date."
        )
    if source.expected_rows and len(rows) != source.expected_rows:
        problems.append(
            f"The download holds {len(rows)} rows, not the {source.expected_rows} expected. "
            "Scores over it are not comparable with scores over the documented version."
        )
    return problems


def decode_rows(body: bytes, encoding: str) -> list[dict[str, Any]]:
    """Decode a fetched body into row dicts. Pure, so the shapes are testable."""
    if encoding == HTTP_JSONL_GZ:
        body = gzip.decompress(body)
        encoding = HTTP_JSONL

    text = body.decode("utf-8", errors="replace")
    if encoding == HTTP_CSV:
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    if encoding == HTTP_JSONL:
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    raise ValidationError(f"unsupported source encoding {encoding!r}")


def installed_sets(session: Session, slug: str) -> list[EvalSet]:
    """Live sets already installed from this benchmark, newest first.

    Membership is recorded as a tag rather than a foreign key: an installed set
    is an ordinary set the moment it exists — editable, deletable, mergeable —
    and a benchmark table would imply a link Gaugix does not maintain.
    """
    rows = session.exec(
        select(EvalSet).where(
            col(EvalSet.deleted_at).is_(None),
            col(EvalSet.tags_json).contains(f'"benchmark:{slug}"'),
        )
    ).all()
    return sorted(rows, key=lambda s: s.id or 0, reverse=True)


def set_tags(benchmark: Benchmark, scope: str) -> list[str]:
    """Tags stamped on an installed set, including the provenance marker."""
    return sorted({f"benchmark:{benchmark.slug}", scope, *benchmark.tags})


def drift_from_install(session: Session, eval_set: EvalSet) -> dict[str, Any]:
    """Whether this set still holds what the benchmark installed into it.

    A benchmark set that someone has added cases to, or removed cases from, or
    edited, is a *derived* set. It may be a better eval than the original; what
    it is not is the benchmark, and the catalogue would otherwise keep
    presenting it as one (D-056).

    Two signals, both cheap: the set of live case ids against the ids installed,
    and the newest case edit against the install time. Returns an empty dict for
    hand-made sets, which have nothing to drift from.
    """
    from gaugix.models.cases import EvalCase, SetMembership

    record = eval_set.provenance
    if not record.get("benchmark"):
        return {}

    live = session.exec(
        select(EvalCase)
        .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
        .where(SetMembership.set_id == eval_set.id, col(EvalCase.deleted_at).is_(None))
    ).all()

    reasons: list[str] = []
    installed_universe = str(record.get("case_universe") or "")
    if installed_universe:
        current = case_universe([c.id or 0 for c in live])
        if current != installed_universe:
            delta = len(live) - int(record.get("case_count") or 0)
            change = (
                f"{abs(delta)} case(s) {'added' if delta > 0 else 'removed'}"
                if delta
                else "its cases were swapped"
            )
            reasons.append(f"Membership has changed since the install — {change}.")

    # Against the newest case timestamp *at install*, not against `installed_at`
    # — which is truncated to the second, so a case written 400ms into the same
    # second read as edited-since-install on every fresh install.
    installed_edit = str(record.get("case_updated_at") or "")
    if installed_edit and live:
        newest = max(c.updated_at for c in live).isoformat()
        if newest > installed_edit:
            reasons.append("At least one case has been edited since the install.")

    return {"modified": bool(reasons), "modified_reasons": reasons}


def legacy_provenance(eval_set: EvalSet) -> dict[str, Any]:
    """A stand-in record for a benchmark set installed before provenance existed.

    The migration added the column empty and did not backfill, because the
    revision and checksum of a past install are not recoverable. What *is*
    recoverable is which benchmark it came from — it is in the tags — and
    saying "installed before Gaugix recorded this" is better than a blank space
    that reads as a hand-made set (D-062).

    `legacy` is the flag readers should branch on: this record asserts the
    benchmark and nothing else. It is not an adaptation and not a verified
    install; its method and revision are simply unknown.
    """
    if eval_set.provenance:
        return {}
    slug = next(
        (t.split(":", 1)[1] for t in eval_set.tags if t.startswith("benchmark:")),
        None,
    )
    if not slug:
        return {}
    entry = get(slug)
    return {
        "benchmark": slug,
        "benchmark_name": entry.name if entry else slug,
        "legacy": True,
        "method_fidelity": "unrecorded",
        "method_version": "unrecorded",
    }


def effective_provenance(session: Session, eval_set: EvalSet) -> dict[str, Any]:
    """The provenance record to display, freeze into a run, and report from.

    One function because there were two: the API inferred a legacy record on
    read, and the planner froze `eval_set.provenance` raw. So a set installed
    before provenance existed showed its benchmark on screen and then produced
    runs whose report had no dataset section at all — the reader saw a number
    with no statement of what it was measured against (D-066).

    Layered stored-over-inferred, then drift last: a real install overwrites
    every inferred field, and a set edited since install says so wherever it is
    shown.
    """
    record: dict[str, Any] = {**legacy_provenance(eval_set), **eval_set.provenance}
    if not record:
        return {}
    return {**record, **drift_from_install(session, eval_set)}


def case_universe(case_ids: list[int]) -> str:
    """Fingerprint of exactly which cases a set holds. Order-independent."""
    return hashlib.sha256(",".join(str(i) for i in sorted(case_ids)).encode()).hexdigest()[:16]


def provenance(
    benchmark: Benchmark,
    scope: str,
    *,
    imported: int,
    seed: int | None,
    fetched: Fetched | None,
    case_ids: list[int] | None = None,
    case_updated_at: str = "",
) -> dict[str, Any]:
    """Everything needed to say which dataset this set is, months later.

    Written into the set's description block at install time. A set that cannot
    name its revision, its checksum and its scorer version cannot support a
    claim about a model — and "we ran IFEval in August" is exactly the kind of
    claim that gets made from one (D-050).
    """
    source = benchmark.source
    return {
        "benchmark": benchmark.slug,
        "benchmark_name": benchmark.name,
        "scope": scope,
        "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "case_count": imported,
        # Which cases, not just how many: a swap that keeps the count the same
        # still makes this a different eval.
        "case_universe": case_universe(case_ids or []),
        #: Newest case timestamp at install, so a later edit is detectable.
        "case_updated_at": case_updated_at,
        "sample_seed": seed,
        "licence": benchmark.licence,
        "method_fidelity": benchmark.method.fidelity,
        "method_version": benchmark.method.version,
        "comparable_to_published": benchmark.method.comparable,
        "source_url": source.url if source else None,
        "source_revision": (source.revision or None) if source else None,
        # The checksum of what actually arrived, not what was expected: this is
        # the field that identifies the data, so it must describe the download.
        "source_sha256": fetched.sha256 if fetched else None,
        "source_bytes": fetched.byte_count if fetched else None,
        "rows_downloaded": len(fetched.rows) if fetched else None,
    }
