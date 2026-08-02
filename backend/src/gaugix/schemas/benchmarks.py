"""DTOs for the benchmark catalogue.

The detail payload is deliberately verbose. Deciding whether to install a
benchmark means reading its licence, its caveats and its scoring method, and a
UI can only show what the API sends.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gaugix.schemas.cases import CaseIO


class BenchmarkSource(BaseModel):
    """The one URL an install would contact, stated before it is contacted."""

    model_config = ConfigDict(extra="forbid")

    url: str
    host: str
    encoding: str
    approx_bytes: int
    #: The immutable revision the URL pins, when the host publishes one.
    revision: str = ""
    #: Expected checksum and row count, verified on download.
    sha256: str = ""
    expected_rows: int = 0


class BenchmarkMethod(BaseModel):
    """Whether a number from Gaugix is the benchmark's number.

    Travels with every summary, not only the detail page: the distinction
    between reproducing a method and running its data through another one is
    the difference between a comparable score and a private one.
    """

    model_config = ConfigDict(extra="forbid")

    fidelity: str
    comparable: bool
    deviations: list[str]
    version: str


class InstalledSetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    case_count: int


class BenchmarkSummary(BaseModel):
    """A catalogue row — enough to choose what to read about."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    publisher: str
    year: int
    licence: str
    task: str
    summary: str
    full_size: int
    sample_size: int
    tags: list[str]
    requires_judge: bool
    requires_code_execution: bool
    method: BenchmarkMethod
    #: Sets already installed from this benchmark. Empty is the normal state.
    installed: list[InstalledSetRef] = Field(default_factory=list)


class BenchmarkDetail(BenchmarkSummary):
    """Everything needed to decide, including the reasons not to."""

    description: str
    what_it_measures: str
    caveats: list[str]
    scoring_note: str
    languages: list[str]
    homepage: str
    licence_url: str
    licence_note: str | None = None
    paper: str | None
    source: BenchmarkSource | None
    #: Real cases built from the bundled rows — what an install actually creates.
    sample_cases: list[CaseIO]


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(default="sample", pattern="^(sample|full)$")
    set_name: str | None = None
    #: Cap the full download, for trying a large benchmark without all of it.
    limit: int | None = Field(default=None, ge=1, le=100_000)
    #: With a limit, take a reproducible random sample rather than the first N.
    #: A benchmark's file order is rarely arbitrary, so the head of the file is
    #: not a sample of the set.
    sample_seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    #: Required for benchmarks whose scoring executes model-written code.
    accept_code_execution: bool = False
    #: Required when the download does not match the checksum or row count this
    #: catalogue entry describes — the caveats and size on the page are then
    #: about a different version of the dataset.
    accept_drift: bool = False


class InstallPreview(BaseModel):
    """What an install would do. No network, no writes."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    scope: str
    set_name: str
    case_count: int
    warnings: list[str]
    source: BenchmarkSource | None
    requires_judge: bool
    requires_code_execution: bool
    method: BenchmarkMethod


class InstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    set_id: int
    set_name: str
    imported: int
    scope: str
    warnings: list[str] = Field(default_factory=list)
    #: Revision, checksum, licence and scorer version of what was installed.
    provenance: dict[str, object] = Field(default_factory=dict)
