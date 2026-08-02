# Gaugix product specification

## Product

Gaugix is a local-first web application for building, running, and accumulating
LLM evaluations. It helps an individual engineer or small product team answer
two practical questions:

1. Which model or execution setup works best for our tasks?
2. Did a new model, prompt, harness, or guardrail regress against a known
   baseline?

The product prioritizes inspectable evidence over leaderboard-style scores.

## Goals

- Make realistic evaluation cases fast to create, organize, import, and reuse.
- Run one or more sets against one or more executors with frozen configuration.
- Combine deterministic, model-based, and human scoring.
- Preserve outputs, attempts, scorer rationales, usage, cost, and artifacts.
- Compare runs and baselines without hiding partial coverage or missing data.
- Export results in a self-contained format that can be opened offline.
- Teach the evaluation concepts required to interpret the results honestly.

## Non-goals for 0.1.0

- Multi-user accounts, authentication, permissions, or hosted tenancy.
- Distributed workers or remote queues.
- A public leaderboard.
- A secure sandbox for arbitrary untrusted native or Python code.
- Statistical claims such as significance tests or pass-at-k aggregation.

## Terminology

- **Case:** one input, optional expected result, scoring specification, tags,
  and notes.
- **Set:** an ordered collection of cases.
- **Model profile:** provider, model id, default parameters, and optional
  pricing.
- **Harness profile:** the mechanism used to invoke a model or local command.
- **Executor:** model profile plus harness profile and optional overrides.
- **Run:** a frozen evaluation of one or more sets by one or more executors.
- **Run item:** one case executed by one executor in one set context.
- **Attempt:** one invocation, including output, usage, cost, latency, and
  errors.
- **Score:** one scorer result, rationale, metadata, and version.
- **Baseline:** the selected reference run for one or more sets.

## Functional requirements

### F1. Case and set library

- Create, edit, duplicate, soft-delete, restore, and permanently delete cases.
- Create and organize ordered sets with tags, descriptions, and default
  scoring.
- Search and filter cases; perform safe bulk tag, move, copy, and delete
  operations.
- Import and export JSON, JSONL, and YAML with atomic validation and useful row
  errors.
- Build a structured generation prompt from a set's schema and examples.
- Show case and set run history derived from immutable run items.

### F2. Executors

- Store model, harness, and executor profiles separately so configurations can
  be reused.
- Support direct model APIs, local CLI commands, and deterministic fake
  harnesses.
- Test profile connectivity without exposing credentials.
- Record model parameters, reasoning controls, pricing, and harness
  configuration in each run snapshot.

### F3. Run engine

- Preflight selected sets, cases, scorers, executors, judges, and code-execution
  requirements before spending money.
- Expand sets times executors into durable run items before execution begins.
- Run executor lanes concurrently with bounded provider concurrency.
- Stream progress through Server-Sent Events while SQLite remains authoritative.
- Support cancellation, startup recovery, resume, rerun-from, and re-score.
- Preserve superseded attempts and earlier score versions.
- Freeze full and partial set coverage, including the case-universe hash.

### F4. Scoring

- Provide deterministic text, regex, JSON, JSON Schema, and task-specific
  assertion scorers.
- Support Python scorers with timeout and visible infrastructure errors.
- Support LLM judges with explicit rubrics, scales, thresholds, judge identity,
  usage, cost, and parse diagnostics.
- Support human pass/fail or numeric review.
- Combine required and optional weighted scorers without turning unresolved
  scores into passes or failures.
- Keep classification, threshold, and judge pass signals auditable when they
  disagree.

### F5. Analysis and reporting

- Show run execution health separately from evaluation results.
- Filter and inspect individual run items, attempts, scores, and artifacts.
- Compare selected runs as a matrix, aggregate summary, leaderboard, or
  baseline diff.
- Keep set-level metrics scoped to the selected set in multi-set runs.
- Exclude partial runs from full-set trends by default and name what was
  excluded.
- Export one self-contained HTML report with methodology, coverage, model,
  harness, scorer, judge, cost, provenance, and per-case results.

### F6. Artifacts and learning

- Extract and store text, code, HTML, and files produced by an invocation.
- Render HTML in a sandboxed iframe.
- Require an explicit confirmation before local artifact execution.
- Include an in-product guide covering cases, scorers, rubrics, judges,
  guardrails, comparison, statistics, and honest reporting.

### F7. Public benchmark library

- Provide offline samples and adapters for selected public benchmarks.
- State each benchmark's publisher, source revision, dataset license, task,
  scoring method, deviations, caveats, and comparability.
- Verify pinned revisions, checksums, and row counts for full downloads where
  the upstream source permits it.
- Track provenance and detect local drift after installation.

## Result semantics

- **Pass rate** equals passed divided by scored.
- An unscored item is neither passed nor failed.
- A required scorer infrastructure error fails the item and remains visible.
- Unknown cost is displayed as unknown or as a known floor, never as zero.
- Judge usage and cost are included in run totals.
- A partial run's metrics describe only its selected cases.
- Historical coverage uses the denominator frozen when the run was planned.

## Data and privacy

- Bind to loopback by default.
- Store application data in SQLite and a local artifact directory.
- Read credentials from environment variables; do not store them in the
  database, logs, backups, or reports.
- Include no telemetry or analytics library.
- Keep backups consistent and exclude environment files.

## Quality requirements

- Backend and frontend code are linted, formatted, and type-checked.
- Tests use isolated temporary databases and deterministic fake harnesses.
- The normal test suite performs no provider network calls.
- Every page provides loading, empty, and error states.
- The golden path can create data, run an evaluation, inspect results, compare
  runs, and export a report.
