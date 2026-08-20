"""Case import/export: JSONL (canonical), YAML, and JSON-array.

Pure functions — no database, no HTTP — so the format rules are unit-testable on
their own. Two properties matter (PRD F1.3):

* **row-level errors**: a bad row reports its 1-based line number and why;
* **atomicity**: the caller writes nothing unless every row parsed. Parsing here
  therefore always returns *all* errors, never the first one.

Foreign formats (CSV, openai/evals, HuggingFace rows, promptfoo) live in
`gaugix.formats`; :func:`parse_any` is the single door both go through.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import ValidationError

from gaugix import formats
from gaugix.schemas.cases import CaseIO, FieldMapping, ImportRowError

JSONL = "jsonl"
YAML = "yaml"
JSON = "json"
FORMATS = (JSONL, YAML, JSON)

#: Every format the importer accepts, native and foreign.
ALL_IMPORT_FORMATS = FORMATS + formats.FOREIGN_FORMATS
#: Every format the exporter can write back out.
ALL_EXPORT_FORMATS = FORMATS + formats.EXPORTABLE_FOREIGN


def _describe(exc: ValidationError) -> str:
    """Flatten a pydantic error into one readable sentence."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts[:4])


def parse_cases(content: str, fmt: str = JSONL) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Parse `content` into cases plus a list of per-row errors.

    Returns every error found, so the UI can show a complete report rather than
    making the user fix one line at a time.
    """
    if fmt == JSONL:
        return _parse_jsonl(content)
    if fmt == YAML:
        return _parse_structured(_load_yaml(content))
    if fmt == JSON:
        return _parse_structured(_load_json(content))
    return [], [ImportRowError(line=0, message=f"unsupported format {fmt!r}")]


def parse_any(
    content: str, fmt: str = JSONL, mapping: FieldMapping | None = None
) -> tuple[list[CaseIO], list[ImportRowError], list[ImportRowError]]:
    """Parse any supported format. Returns (cases, errors, warnings).

    The one entry point callers should use: native formats never warn, foreign
    ones sometimes do, and nobody outside this module should have to know which
    family a format belongs to.
    """
    if fmt in formats.FOREIGN_FORMATS:
        return formats.parse_foreign(content, fmt, mapping)
    cases, errors = parse_cases(content, fmt)
    return cases, errors, []


def _parse_jsonl(content: str) -> tuple[list[CaseIO], list[ImportRowError]]:
    cases: list[CaseIO] = []
    errors: list[ImportRowError] = []
    for lineno, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(ImportRowError(line=lineno, message=f"invalid JSON: {exc.msg}", raw=raw))
            continue
        case, error = _validate_row(payload, lineno, raw)
        if error:
            errors.append(error)
        elif case:
            cases.append(case)
    if not cases and not errors:
        errors.append(ImportRowError(line=0, message="no cases found in input"))
    return cases, errors


def _load_yaml(content: str) -> Any | ImportRowError:
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return ImportRowError(line=_yaml_line(exc), message=f"invalid YAML: {exc}")


def _yaml_line(exc: yaml.YAMLError) -> int:
    mark = getattr(exc, "problem_mark", None)
    return (mark.line + 1) if mark is not None else 0


def _load_json(content: str) -> Any | ImportRowError:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return ImportRowError(line=exc.lineno, message=f"invalid JSON: {exc.msg}")


def _parse_structured(document: Any) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Handle a parsed YAML/JSON document: a list, or `{cases: [...]}`."""
    if isinstance(document, ImportRowError):
        return [], [document]
    if document is None:
        return [], [ImportRowError(line=0, message="no cases found in input")]
    if isinstance(document, dict):
        document = document.get("cases", document)
    if not isinstance(document, list):
        return [], [ImportRowError(line=0, message="expected a list of cases (or a `cases:` key)")]

    cases: list[CaseIO] = []
    errors: list[ImportRowError] = []
    for index, payload in enumerate(document, start=1):
        case, error = _validate_row(payload, index, None)
        if error:
            errors.append(error)
        elif case:
            cases.append(case)
    if not cases and not errors:
        errors.append(ImportRowError(line=0, message="no cases found in input"))
    return cases, errors


def _validate_row(
    payload: Any, line: int, raw: str | None
) -> tuple[CaseIO | None, ImportRowError | None]:
    if not isinstance(payload, dict):
        return None, ImportRowError(
            line=line, message=f"expected an object, got {type(payload).__name__}", raw=raw
        )
    try:
        return CaseIO.model_validate(payload), None
    except ValidationError as exc:
        return None, ImportRowError(line=line, message=_describe(exc), raw=raw)


# -- export --------------------------------------------------------------------


def dump_cases(cases: list[CaseIO], fmt: str = JSONL) -> str:
    """Serialise cases. JSONL round-trips exactly through :func:`parse_cases`.

    The foreign formats do not round-trip and are not meant to: CSV has nowhere
    to put a transcript or a scorer, so exporting to it drops them rather than
    encoding them into a cell nothing else would read.
    """
    if fmt in formats.EXPORTABLE_FOREIGN:
        return formats.dump_foreign(cases, fmt)

    payloads = []
    for case in cases:
        payload = case.model_dump(mode="json")
        # Preserve the established canonical shape for ungrouped exports while
        # allowing a set-scoped file to rebuild its branches on import.
        if not case.group_path:
            payload.pop("group_path", None)
        payloads.append(payload)
    if fmt == JSONL:
        return "".join(json.dumps(p, ensure_ascii=False, sort_keys=False) + "\n" for p in payloads)
    if fmt == YAML:
        return yaml.safe_dump(
            {"cases": payloads}, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
    if fmt == JSON:
        return json.dumps(payloads, ensure_ascii=False, indent=2) + "\n"
    raise ValueError(f"unsupported format {fmt!r}")


MEDIA_TYPES = {
    JSONL: "application/x-ndjson",
    YAML: "application/yaml",
    JSON: "application/json",
    **formats.MEDIA_TYPES,
}

FILE_EXTENSIONS = {
    JSONL: "jsonl",
    YAML: "yaml",
    JSON: "json",
    **formats.FILE_EXTENSIONS,
}
