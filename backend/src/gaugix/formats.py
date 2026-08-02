"""Foreign eval formats, in and out (PRD F1.3, extended).

`caseio` owns Gaugix's own JSONL/YAML/JSON shape. This module owns everybody
else's, so a benchmark you found on GitHub is one paste away from being a set:

* **csv** — any table, with a column mapping (guessed when you do not give one);
* **openai_evals** — the `{"input": [...], "ideal": ...}` JSONL used by
  openai/evals and by most files that copied it;
* **huggingface** — a `datasets-server` `/rows` payload, or a bare list of rows;
* **promptfoo** — `tests:` with `vars:` and `assert:`, whose assertions are
  translated into Gaugix scorers where an honest translation exists.

Two rules, both learned the hard way:

**Guessing is allowed; guessing silently is not.** A CSV whose prompt column
cannot be identified is a row-level error naming the columns it did find, not a
best-effort import that quietly evaluates the wrong field.

**A translation that loses meaning is a warning, not a success.** promptfoo's
`javascript` assertions have no Gaugix equivalent. Dropping them silently would
leave a case that looks scored and is not, so they come back as warnings and the
importer says which cases lost which checks.

Everything here is pure: strings in, `CaseIO` out. No database, no network.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

import yaml

from gaugix.domain import Message, Role, ScorerSpec, ScorerType
from gaugix.schemas.cases import CaseIO, FieldMapping, ImportRowError

CSV = "csv"
OPENAI_EVALS = "openai_evals"
HUGGINGFACE = "huggingface"
PROMPTFOO = "promptfoo"

#: Formats this module owns. `caseio.FORMATS` owns the native ones.
FOREIGN_FORMATS = (CSV, OPENAI_EVALS, HUGGINGFACE, PROMPTFOO)

#: Column names that usually hold the thing you want to send to the model.
#: Ordered by specificity: `question` beats `text` when a table has both.
INPUT_CANDIDATES = (
    "input",
    "prompt",
    "question",
    "instruction",
    "problem",
    "query",
    "turns",
    "text",
    "content",
)
REFERENCE_CANDIDATES = (
    "reference",
    "ideal",
    "answer",
    "expected",
    "target",
    "solution",
    "gold",
    "best_answer",
    "canonical_solution",
    "label",
    "output",
)
TITLE_CANDIDATES = ("title", "name", "task_id", "id", "key")
TAG_CANDIDATES = ("tags", "category", "categories", "topic", "subject", "type")
SYSTEM_CANDIDATES = ("system", "system_prompt", "context")


# -- field mapping -------------------------------------------------------------


def _lookup(row: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    """First candidate column present in the row, matched case-insensitively."""
    lowered = {str(key).strip().lower(): key for key in row}
    for candidate in candidates:
        if candidate in lowered:
            return str(lowered[candidate])
    return None


def resolve_mapping(rows: list[dict[str, Any]], mapping: FieldMapping | None) -> FieldMapping:
    """Fill in whatever the caller left unset by looking at the first row.

    Explicit always wins. The guess only ever fills a blank, so re-importing
    with a mapping cannot be silently overridden by the heuristic.
    """
    explicit = mapping or FieldMapping()
    if not rows:
        return explicit
    sample = rows[0]
    return FieldMapping(
        input=explicit.input or _lookup(sample, INPUT_CANDIDATES),
        reference=explicit.reference or _lookup(sample, REFERENCE_CANDIDATES),
        title=explicit.title or _lookup(sample, TITLE_CANDIDATES),
        system=explicit.system or _lookup(sample, SYSTEM_CANDIDATES),
        tags=explicit.tags or _lookup(sample, TAG_CANDIDATES),
        notes=explicit.notes,
        title_prefix=explicit.title_prefix,
    )


def _as_text(value: Any) -> str:
    """Flatten a cell into text without inventing content.

    Datasets nest freely: a `turns` column is often a list of strings, and a
    `choices` column a dict. Rendering those as `str(dict)` would put Python
    repr into a prompt, so structured values become JSON and lists become lines.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, list):
        if all(isinstance(v, str) for v in value):
            return "\n\n".join(value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[,;|]", str(value)) if part.strip()]


def adapt_rows(
    rows: list[dict[str, Any]],
    mapping: FieldMapping | None = None,
    *,
    first_line: int = 1,
    scoring: list[ScorerSpec] | None = None,
    extra_tags: list[str] | None = None,
) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Turn arbitrary tabular rows into cases using a (possibly guessed) mapping."""
    if not rows:
        return [], [ImportRowError(line=0, message="no rows found in input")]

    resolved = resolve_mapping(rows, mapping)
    if not resolved.input:
        columns = ", ".join(sorted(str(k) for k in rows[0])[:12]) or "(none)"
        return [], [
            ImportRowError(
                line=0,
                message=(
                    "could not tell which column holds the prompt — "
                    f"set `mapping.input` explicitly. Columns found: {columns}"
                ),
            )
        ]

    cases: list[CaseIO] = []
    errors: list[ImportRowError] = []
    for index, row in enumerate(rows):
        line = first_line + index
        prompt = _as_text(row.get(resolved.input)).strip()
        if not prompt:
            errors.append(
                ImportRowError(
                    line=line, message=f"column {resolved.input!r} is empty — nothing to ask"
                )
            )
            continue

        messages: list[Message] = []
        if resolved.system:
            system = _as_text(row.get(resolved.system)).strip()
            if system:
                messages.append(Message(role=Role.system, content=system))
        messages.append(Message(role=Role.user, content=prompt))

        raw_title = _as_text(row.get(resolved.title)).strip() if resolved.title else ""
        title = raw_title or f"{resolved.title_prefix} {index + 1}".strip()

        reference = None
        if resolved.reference:
            reference = _as_text(row.get(resolved.reference)).strip() or None

        tags = _split_tags(row.get(resolved.tags)) if resolved.tags else []
        notes = _as_text(row.get(resolved.notes)).strip() or None if resolved.notes else None

        cases.append(
            CaseIO(
                title=title[:200],
                input=messages,
                reference=reference,
                scoring=list(scoring or []),
                tags=sorted({*tags, *(extra_tags or [])}),
                notes=notes,
            )
        )
    return cases, errors


# -- csv -----------------------------------------------------------------------


def parse_csv(
    content: str, mapping: FieldMapping | None = None
) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Parse a CSV/TSV table. Line 1 is the header, so data starts at line 2."""
    if not content.strip():
        return [], [ImportRowError(line=0, message="no rows found in input")]
    try:
        dialect: Any = csv.Sniffer().sniff(content[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        return [], [ImportRowError(line=1, message="the file has no header row")]

    rows = [{k: v for k, v in row.items() if k is not None} for row in reader]
    return adapt_rows(rows, mapping, first_line=2)


def dump_csv(cases: list[CaseIO]) -> str:
    """Export as a flat table. Multi-turn inputs collapse to the last user turn.

    Lossy on purpose and only in one direction: CSV has nowhere to put a
    transcript or a scorer config, so anything structural is dropped rather than
    encoded into a cell that no other tool would read back.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["title", "input", "reference", "tags", "notes"])
    for case in cases:
        prompt = next(
            (m.content for m in reversed(case.input) if m.role == Role.user),
            case.input[0].content if case.input else "",
        )
        writer.writerow(
            [
                case.title,
                prompt,
                case.reference or "",
                ",".join(case.tags),
                case.notes or "",
            ]
        )
    return buffer.getvalue()


# -- openai/evals --------------------------------------------------------------


def parse_openai_evals(content: str) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Parse `{"input": [...], "ideal": ...}` JSONL.

    `ideal` is often a list of acceptable answers. Gaugix's `reference` is one
    string, so the first becomes the reference and every alternative is written
    into `notes` — losing them would quietly narrow what counts as correct.
    """
    cases: list[CaseIO] = []
    errors: list[ImportRowError] = []

    for lineno, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(ImportRowError(line=lineno, message=f"invalid JSON: {exc.msg}", raw=raw))
            continue
        if not isinstance(payload, dict):
            errors.append(
                ImportRowError(line=lineno, message="expected an object", raw=raw[:200] or None)
            )
            continue

        messages, error = _evals_messages(payload.get("input"), lineno, raw)
        if error is not None:
            errors.append(error)
            continue

        ideal = payload.get("ideal")
        reference: str | None = None
        notes: str | None = None
        if isinstance(ideal, list) and ideal:
            reference = _as_text(ideal[0]).strip() or None
            if len(ideal) > 1:
                alternatives = "; ".join(_as_text(v).strip() for v in ideal[1:])
                notes = f"Also accepted: {alternatives}"
        elif ideal is not None:
            reference = _as_text(ideal).strip() or None

        first_user = next((m.content for m in messages if m.role == Role.user), "")
        cases.append(
            CaseIO(
                title=_title_from(payload, first_user, lineno),
                input=messages,
                reference=reference,
                tags=_split_tags(payload.get("tags")),
                notes=notes,
            )
        )

    if not cases and not errors:
        errors.append(ImportRowError(line=0, message="no cases found in input"))
    return cases, errors


def _evals_messages(
    raw_input: Any, lineno: int, raw: str
) -> tuple[list[Message], ImportRowError | None]:
    """`input` is either a chat array or, in older files, a bare string."""
    if isinstance(raw_input, str) and raw_input.strip():
        return [Message(role=Role.user, content=raw_input)], None
    if not isinstance(raw_input, list) or not raw_input:
        return [], ImportRowError(
            line=lineno, message="`input` must be a non-empty string or message list", raw=raw[:200]
        )

    messages: list[Message] = []
    for entry in raw_input:
        if not isinstance(entry, dict):
            return [], ImportRowError(
                line=lineno, message="each `input` entry must be an object", raw=raw[:200]
            )
        role = str(entry.get("role", "user")).lower()
        # openai/evals writes `system`, `user`, `assistant`; anything else
        # (`tool`, a custom name) has no Gaugix equivalent and becomes a user
        # turn rather than being dropped.
        if role not in {r.value for r in Role}:
            role = Role.user.value
        content = _as_text(entry.get("content")).strip()
        if content:
            messages.append(Message(role=Role(role), content=content))

    if not messages:
        return [], ImportRowError(line=lineno, message="`input` had no content", raw=raw[:200])
    return messages, None


def _title_from(payload: dict[str, Any], fallback: str, lineno: int) -> str:
    for key in TITLE_CANDIDATES:
        value = payload.get(key)
        if value:
            return _as_text(value).strip()[:200]
    summary = " ".join(fallback.split())[:80]
    return summary or f"Case {lineno}"


def dump_openai_evals(cases: list[CaseIO]) -> str:
    """Export as openai/evals JSONL — the closest thing to a lingua franca."""
    lines = []
    for case in cases:
        payload: dict[str, Any] = {
            "input": [m.as_api_dict() for m in case.input],
        }
        if case.reference is not None:
            payload["ideal"] = case.reference
        payload["title"] = case.title
        if case.tags:
            payload["tags"] = case.tags
        lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


# -- huggingface ---------------------------------------------------------------


def parse_huggingface(
    content: str, mapping: FieldMapping | None = None
) -> tuple[list[CaseIO], list[ImportRowError]]:
    """Parse a `datasets-server` `/rows` payload, or a bare list of row objects."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return [], [ImportRowError(line=exc.lineno, message=f"invalid JSON: {exc.msg}")]

    rows = extract_hf_rows(payload)
    if rows is None:
        return [], [
            ImportRowError(
                line=0,
                message="expected a `rows` array (datasets-server) or a list of row objects",
            )
        ]
    return adapt_rows(rows, mapping, first_line=1)


def extract_hf_rows(payload: Any) -> list[dict[str, Any]] | None:
    """Unwrap the `{"rows": [{"row_idx": n, "row": {...}}]}` envelope.

    Shared with the benchmark installer, which fetches the same endpoint.
    Returns None when the payload is not row-shaped at all.
    """
    if isinstance(payload, dict):
        payload = payload.get("rows", payload.get("data"))
    if not isinstance(payload, list):
        return None

    rows: list[dict[str, Any]] = []
    for entry in payload:
        if isinstance(entry, dict) and isinstance(entry.get("row"), dict):
            rows.append(entry["row"])
        elif isinstance(entry, dict):
            rows.append(entry)
    return rows


# -- promptfoo -----------------------------------------------------------------

#: promptfoo assertion type -> how to build the equivalent Gaugix scorer.
#: Anything absent from this table is reported rather than silently dropped.
_PROMPTFOO_DIRECT = {
    "contains": (ScorerType.contains, "text", {}),
    "icontains": (ScorerType.contains, "text", {"case_sensitive": False}),
    "not-contains": (ScorerType.not_contains, "text", {}),
    "not-icontains": (ScorerType.not_contains, "text", {"case_sensitive": False}),
    "regex": (ScorerType.regex, "pattern", {"should_match": True}),
    "not-regex": (ScorerType.regex, "pattern", {"should_match": False}),
    "llm-rubric": (ScorerType.llm_judge, "rubric", {}),
    "model-graded-closedqa": (ScorerType.llm_judge, "rubric", {}),
}


def parse_promptfoo(
    content: str,
) -> tuple[list[CaseIO], list[ImportRowError], list[ImportRowError]]:
    """Parse a promptfoo config into cases, errors and *warnings*.

    The third return value is what makes this honest: an assertion Gaugix cannot
    express (`javascript`, a custom function) must not vanish into a case that
    then looks fully scored. It comes back as a warning naming the case.
    """
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 1) if mark is not None else 0
        return [], [ImportRowError(line=line, message=f"invalid YAML: {exc}")], []

    if not isinstance(document, dict):
        return [], [ImportRowError(line=0, message="expected a promptfoo config object")], []

    tests = document.get("tests")
    if not isinstance(tests, list) or not tests:
        return [], [ImportRowError(line=0, message="no `tests:` found in the config")], []

    templates, external = _promptfoo_templates(document.get("prompts"))
    default_asserts = _assert_list(document.get("defaultTest"))

    cases: list[CaseIO] = []
    errors: list[ImportRowError] = []
    warnings: list[ImportRowError] = []

    if external:
        warnings.append(
            ImportRowError(
                line=0,
                message=(
                    f"{len(external)} prompt(s) live outside this config and were skipped "
                    f"({', '.join(external[:3])}). promptfoo resolves file:// references and "
                    "prompt functions at run time; Gaugix imports only inline prompts."
                ),
            )
        )

    if len(templates) > 1:
        warnings.append(
            ImportRowError(
                line=0,
                message=(
                    f"This config has {len(templates)} prompts, and promptfoo runs every test "
                    f"against each of them. Each test therefore imports as {len(templates)} "
                    "cases, one per prompt."
                ),
            )
        )

    # One template means one case per test; several mean the matrix promptfoo
    # would actually evaluate. `[None]` covers a config with no prompts at all,
    # where the variable itself is the prompt.
    for slot, template in enumerate(templates or [None], start=1):
        for index, raw_test in enumerate(tests, start=1):
            test = {"vars": {"input": raw_test}} if isinstance(raw_test, str) else raw_test
            if not isinstance(test, dict):
                if slot == 1:
                    errors.append(ImportRowError(line=index, message="each test must be an object"))
                continue

            raw_vars = test.get("vars")
            variables: dict[str, Any] = raw_vars if isinstance(raw_vars, dict) else {}
            prompt = _render_prompt(template, variables)
            if not prompt:
                if slot == 1:
                    errors.append(
                        ImportRowError(
                            line=index,
                            message=(
                                "could not build a prompt — the test has no `vars` this config uses"
                            ),
                        )
                    )
                continue

            title = str(test.get("description") or "").strip() or f"Test {index}"
            if len(templates) > 1:
                title = f"{title} · prompt {slot}"
            scoring, unmapped = _promptfoo_scorers(default_asserts + _assert_list(test))
            if unmapped and slot == 1:
                kinds = ", ".join(sorted(set(unmapped)))
                warnings.append(
                    ImportRowError(
                        line=index,
                        message=(
                            f"{title}: dropped {len(unmapped)} assertion(s) Gaugix cannot "
                            f"express ({kinds}) — this case imports with the rest"
                        ),
                    )
                )

            cases.append(
                CaseIO(
                    title=title[:200],
                    input=[Message(role=Role.user, content=prompt)],
                    reference=_as_text(variables.get("expected") or variables.get("ideal")).strip()
                    or None,
                    scoring=scoring,
                    tags=_split_tags(test.get("tags")),
                )
            )

    if not cases and not errors:
        errors.append(ImportRowError(line=0, message="no cases found in input"))
    return cases, errors, warnings


def _promptfoo_templates(prompts: Any) -> tuple[list[str], list[str]]:
    """Every inline prompt the config carries, and the ones Gaugix cannot read.

    promptfoo evaluates prompts × tests as a matrix, so a config with three
    prompts and ten tests describes thirty evaluations.

    A prompt does not need `{{var}}` to be a prompt. Requiring one dropped
    every literal prompt in the config — silently, and without even the matrix
    warning, because a config whose prompts were all literal looked like a
    config with no prompts at all.

    What genuinely cannot be imported is a prompt that lives somewhere else:
    `file://` references and JavaScript/Python prompt functions are resolved by
    promptfoo at run time against files Gaugix has never seen. Those come back
    as descriptions to warn about, not as silence.
    """
    if isinstance(prompts, str):
        return ([], [prompts]) if _is_external_prompt(prompts) else ([prompts], [])

    templates: list[str] = []
    external: list[str] = []
    if isinstance(prompts, list):
        for entry in prompts:
            raw = entry if isinstance(entry, str) else None
            if isinstance(entry, dict):
                candidate = entry.get("raw") or entry.get("label") or entry.get("id")
                raw = candidate if isinstance(candidate, str) else None
                # A chat-format prompt is a list of messages, not a string.
                if raw is None and isinstance(entry.get("raw"), list):
                    external.append("a chat-format prompt")
                    continue
            if raw is None:
                continue
            (external if _is_external_prompt(raw) else templates).append(raw)
    return templates, external


def _is_external_prompt(raw: str) -> bool:
    """True for prompts promptfoo resolves from disk or from a function."""
    stripped = raw.strip()
    return stripped.startswith(("file://", "python:", "exec:")) or bool(
        re.match(r"^[\w./-]+\.(js|mjs|cjs|ts|py|txt|json|yaml|yml|j2)(:[\w.]+)?$", stripped)
    )


def _render_prompt(template: str | None, variables: dict[str, Any]) -> str:
    """Substitute `{{var}}` in the template, or fall back to a likely var."""
    if template:
        rendered = re.sub(
            r"\{\{\s*(\w+)\s*\}\}",
            lambda m: _as_text(variables.get(m.group(1), m.group(0))),
            template,
        )
        return rendered.strip()

    for key in INPUT_CANDIDATES:
        if key in variables:
            return _as_text(variables[key]).strip()
    # A single-variable test needs no template: the variable is the prompt.
    if len(variables) == 1:
        return _as_text(next(iter(variables.values()))).strip()
    return ""


def _assert_list(container: Any) -> list[dict[str, Any]]:
    if not isinstance(container, dict):
        return []
    asserts = container.get("assert")
    if not isinstance(asserts, list):
        return []
    return [a for a in asserts if isinstance(a, dict)]


def _promptfoo_scorers(asserts: list[dict[str, Any]]) -> tuple[list[ScorerSpec], list[str]]:
    """Translate assertions, returning the scorers and the types that did not map."""
    scorers: list[ScorerSpec] = []
    unmapped: list[str] = []

    for entry in asserts:
        kind = str(entry.get("type", "")).strip().lower()
        value = entry.get("value")
        weight = float(entry.get("weight", 1) or 1)

        if kind in _PROMPTFOO_DIRECT:
            scorer_type, param, extra = _PROMPTFOO_DIRECT[kind]
            text = _as_text(value).strip()
            if not text:
                unmapped.append(kind)
                continue
            scorers.append(
                ScorerSpec(type=scorer_type, params={param: text, **extra}, weight=weight)
            )
        elif kind in {"equals", "is-equals"}:
            # No `equals` scorer exists. An anchored, escaped regex is exactly
            # equality modulo surrounding whitespace — a real translation rather
            # than the `contains` approximation, which would pass on a superstring.
            escaped = re.escape(_as_text(value).strip())
            scorers.append(
                ScorerSpec(
                    type=ScorerType.regex,
                    params={"pattern": rf"^\s*{escaped}\s*$", "should_match": True},
                    weight=weight,
                )
            )
        elif kind in {"is-json", "is_json"}:
            schema = value if isinstance(value, dict) else {}
            scorers.append(ScorerSpec(type=ScorerType.json_schema, params={"schema": schema}))
        elif kind == "python":
            code = _as_text(value).strip()
            if code:
                scorers.append(ScorerSpec(type=ScorerType.python, params={"code": code}))
            else:
                unmapped.append(kind)
        elif kind:
            unmapped.append(kind)

    return scorers, unmapped


# -- dispatch ------------------------------------------------------------------


def parse_foreign(
    content: str, fmt: str, mapping: FieldMapping | None = None
) -> tuple[list[CaseIO], list[ImportRowError], list[ImportRowError]]:
    """Parse one of {@link FOREIGN_FORMATS}. Returns (cases, errors, warnings)."""
    if fmt == CSV:
        cases, errors = parse_csv(content, mapping)
        return cases, errors, []
    if fmt == OPENAI_EVALS:
        cases, errors = parse_openai_evals(content)
        return cases, errors, []
    if fmt == HUGGINGFACE:
        cases, errors = parse_huggingface(content, mapping)
        return cases, errors, []
    if fmt == PROMPTFOO:
        return parse_promptfoo(content)
    return [], [ImportRowError(line=0, message=f"unsupported format {fmt!r}")], []


def dump_foreign(cases: list[CaseIO], fmt: str) -> str:
    if fmt == CSV:
        return dump_csv(cases)
    if fmt == OPENAI_EVALS:
        return dump_openai_evals(cases)
    raise ValueError(f"{fmt!r} cannot be exported — it is an import-only format")


#: Formats that round-trip out again. promptfoo and huggingface are import-only:
#: writing a promptfoo config would have to invent prompt templates, and the
#: datasets-server payload is a server's response, not a file anyone authors.
EXPORTABLE_FOREIGN = (CSV, OPENAI_EVALS)

MEDIA_TYPES = {
    CSV: "text/csv",
    OPENAI_EVALS: "application/x-ndjson",
    HUGGINGFACE: "application/json",
    PROMPTFOO: "application/yaml",
}

FILE_EXTENSIONS = {CSV: "csv", OPENAI_EVALS: "jsonl", HUGGINGFACE: "json", PROMPTFOO: "yaml"}
