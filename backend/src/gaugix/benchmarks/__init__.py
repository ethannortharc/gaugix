"""Public benchmarks Gaugix can install as eval sets (PRD F1.3, extended).

`catalog` is the metadata, `adapters` turn each benchmark's native rows into
cases, `scorers` holds the scorer programs they arrive with, and `install`
performs the one network call the whole feature is allowed to make.
"""

from gaugix.benchmarks.catalog import (
    ADAPTATION,
    CATALOG,
    OFFICIAL,
    Benchmark,
    InstallPlan,
    Method,
    get,
)
from gaugix.benchmarks.install import (
    FULL,
    SAMPLE,
    SCOPES,
    Fetched,
    case_universe,
    drift_from_install,
    effective_provenance,
    installed_sets,
    legacy_provenance,
    load_cases,
    plan_install,
    provenance,
    set_tags,
)

__all__ = [
    "ADAPTATION",
    "CATALOG",
    "FULL",
    "OFFICIAL",
    "SAMPLE",
    "SCOPES",
    "Benchmark",
    "Fetched",
    "InstallPlan",
    "Method",
    "case_universe",
    "drift_from_install",
    "effective_provenance",
    "get",
    "installed_sets",
    "legacy_provenance",
    "load_cases",
    "plan_install",
    "provenance",
    "set_tags",
]
