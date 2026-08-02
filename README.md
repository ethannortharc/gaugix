<p align="center">
  <img src="docs/images/gaugix-mark.svg" width="72" height="72" alt="Gaugix logo">
</p>

<h1 align="center">Gaugix</h1>

<p align="center">
  A local-first workbench for building, running, auditing, and comparing LLM evaluations.
</p>

<p align="center">
  <a href="https://github.com/ethannortharc/gaugix/actions/workflows/ci.yml"><img src="https://github.com/ethannortharc/gaugix/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776ab" alt="Python 3.12 or newer">
  <img src="https://img.shields.io/badge/telemetry-none-5cc8c8" alt="No telemetry">
</p>

Gaugix helps you evaluate models on the tasks that matter to your product—not only on a public leaderboard. Define realistic cases, run them through one or more model/harness combinations, combine deterministic checks with model judges and human review, and keep every result inspectable down to the exact attempt and scorer rationale.

Everything is stored locally in SQLite. The server binds to `127.0.0.1` by default, API keys stay in environment variables, and the application contains no telemetry.

![Gaugix dashboard showing completed runs, baselines, and per-set pass-rate trends](docs/images/gaugix-dashboard.png)

## Why Gaugix?

An aggregate score is useful only when you can explain what produced it. Gaugix treats evaluation as an auditable workflow:

- **Build the right test set.** Create cases in the UI, import JSON/JSONL/YAML, generate a structured authoring prompt, or install a bundled public benchmark sample.
- **Run fair comparisons.** Evaluate the same frozen cases against multiple executors, track cost and latency, and keep partial runs visibly separate from full-set results.
- **Use more than one kind of evidence.** Combine assertions, JSON Schema, Python scorers, LLM judges, and human review.
- **Debug individual failures.** Inspect frozen inputs, outputs, attempts, errors, artifacts, scores, judge metadata, and rationales.
- **Compare without losing context.** Mark per-set baselines, inspect matrices and diffs, and follow set/case run history over time.
- **Share results honestly.** Export self-contained HTML reports with methodology, coverage, model, scorer, judge, cost, and provenance details.

## Product tour

### Inspect a run, not just its average

Every run shows execution health separately from evaluation outcomes. Filter the item board, open any case, and trace the exact result that changed the score.

![Completed Gaugix run with lane progress, evaluation totals, filters, and individual case results](docs/images/gaugix-run-detail.png)

### Keep benchmark history attached to the benchmark

Set history is scoped to the selected set even when a run contains multiple sets. Full runs, partial runs, baselines, executors, and pass rates remain explicit.

![Gaugix set detail showing full and partial run history alongside evaluation cases](docs/images/gaugix-set-history.png)

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- npm and GNU Make

### Run the offline demo

```bash
git clone https://github.com/ethannortharc/gaugix.git
cd gaugix

make setup
GAUGIX_FORCE=1 make seed
make dev
```

Open [http://localhost:5173](http://localhost:5173). The seed includes synthetic evaluation sets and deterministic fake executors, so the complete workflow works without an API key or network model call.

> [!CAUTION]
> `GAUGIX_FORCE=1 make seed` resets the configured Gaugix data directory before loading demo data. Do not run it against data you want to keep.

### Use real models

Copy the environment template and add only the provider keys you need:

```bash
cp .env.example .env
```

```dotenv
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
```

Then open **Executors** and create a model profile, harness profile, and executor. Gaugix also supports CLI executors for evaluating a local command instead of calling a model API directly.

For a single-process production-style build:

```bash
make build
make dev-api
```

The built UI is served by FastAPI at [http://127.0.0.1:8317](http://127.0.0.1:8317).

## Core concepts

| Concept | Meaning |
|---|---|
| **Case** | One frozen input, optional reference answer, tags, notes, and scoring specification. |
| **Set** | An ordered collection of cases representing a benchmark or product behavior. |
| **Executor** | A model profile paired with a harness profile and optional parameter overrides. |
| **Run** | The frozen expansion of one or more sets × one or more executors. |
| **Run item** | One case executed by one executor in one set context. |
| **Attempt** | One invocation, including output, usage, latency, cost, errors, and retry lineage. |
| **Score** | One scorer's result, rationale, metadata, and version. |

Runs are append-oriented. Re-runs and re-scoring keep earlier attempts and score versions available for audit instead of rewriting history.

## Scoring

Gaugix can combine multiple required or optional scorers with weights:

- exact, contains, and not-contains assertions;
- regular expressions and JSON Schema validation;
- Python scorers for task-specific deterministic logic;
- LLM-as-judge rubrics with explicit scales and thresholds;
- human review with keyboard-first pass/fail workflows.

Pass rate is calculated as `passed / scored`. Unscored items remain visible and are not silently counted as passes or failures. Unknown cost remains unknown instead of being presented as zero.

## Public benchmark library

The built-in catalog currently includes adapters and offline samples for:

- GSM8K
- MT-Bench
- IFEval
- HumanEval
- SimpleQA
- TruthfulQA

Every catalog entry states its source, dataset license, scoring method, known deviations, caveats, and whether the resulting number is comparable with the published benchmark. Full dataset installation is explicit and verifies pinned revisions, checksums, and expected row counts where the source permits it.

Dataset content remains subject to each dataset's own license; the repository's MIT license does not replace those terms.

## Architecture

```mermaid
flowchart LR
    UI[React + TypeScript] --> API[FastAPI]
    API --> DB[(SQLite)]
    API --> ENGINE[Run + scoring engine]
    ENGINE --> DIRECT[Direct model harness]
    ENGINE --> CLI[CLI harness]
    ENGINE --> FAKE[Deterministic fake harness]
    ENGINE --> REPORTS[Offline HTML reports]
```

- **Backend:** Python, FastAPI, SQLModel, Alembic, Pydantic, Jinja2
- **Frontend:** React, TypeScript, Vite, TanStack Query, Tailwind CSS, Radix UI
- **Persistence:** SQLite with WAL mode; artifacts and exports live under the configured data directory
- **Execution:** a single local process with resumable runs and Server-Sent Events

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed data model and runtime design.

## Commands

| Command | Purpose |
|---|---|
| `make setup` | Install backend, frontend, and Playwright dependencies. |
| `make dev` | Start the API and Vite development server. |
| `make check` | Run backend/frontend lint, format, type, and unit/API/component tests. |
| `make e2e` | Build the app and run the Playwright golden path. |
| `make build` | Build the frontend for single-process serving. |
| `make seed` | Reset the configured data directory and load synthetic demo data. |
| `make backup` | Create a consistent database + artifact archive without `.env`. |
| `make smoke` | Make explicitly capped real-model smoke calls; this may spend money. |

## Data and security

- Gaugix is a local, single-user application and has **no authentication layer**. Do not expose its port to an untrusted network.
- `.env`, SQLite data, artifacts, logs, exports, and backups are excluded from Git.
- API keys are read from the environment and are not stored in the database or included in reports.
- HTML artifacts render in sandboxed iframes.
- Python scorers and explicit artifact execution run local code. Treat imported scorers and generated artifacts as untrusted code and review them before execution.

Read [SECURITY.md](SECURITY.md) before running untrusted scorers or artifacts.

## Project status

Gaugix is an early `0.1.0` release. It is designed for local evaluation work, not multi-tenant hosting. The current engine is single-process, result tables are not yet virtualized for extremely large runs, and the E2E suite intentionally covers one golden path while the backend and component suites carry broader behavior coverage.

Issues and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Gaugix source code is available under the [MIT License](LICENSE). Bundled benchmark samples and downloaded datasets may use different licenses, which are shown in the benchmark catalog.

Copyright © 2026 Ethan H.B. Zhou.
