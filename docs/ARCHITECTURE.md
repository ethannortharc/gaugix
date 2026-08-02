# Gaugix architecture

This document describes the public architecture of Gaugix 0.1.0. Gaugix is a
local, single-user evaluation workbench: one FastAPI process owns the API and
run engine, one SQLite database stores durable state, and a React application
provides the user interface.

## Design principles

1. **Local by default.** The server binds to loopback and stores data in a
   user-controlled directory.
2. **Frozen inputs, append-oriented history.** A completed run must remain
   interpretable after a case, set, model profile, or scorer is edited.
3. **Unknown is not zero.** Missing scores, usage, coverage, and cost remain
   explicit instead of being converted into optimistic values.
4. **Execution and evaluation are separate.** Transport success does not imply
   a passing evaluation, and a scorer failure is not a model answer.
5. **Every aggregate drills down.** Run, set, case, attempt, and score records
   retain enough context to explain the number shown in the UI.

## Components

The React application communicates with FastAPI through REST and Server-Sent
Events. FastAPI owns the run engine, scoring engine, SQLite persistence,
artifacts, and report generation. The run engine invokes one of three harness
types: direct model API, local CLI, or deterministic fake.

### Backend

The backend lives under **backend/src/gaugix/** and uses:

- FastAPI for HTTP and Server-Sent Events;
- SQLModel and SQLite for persistence;
- Alembic for schema migrations;
- Pydantic for frozen domain snapshots and API schemas;
- Jinja2 plus inline SVG for self-contained HTML reports.

The application starts in this order: configure logging, create the data
directories, migrate the database, recover interrupted runs, then serve
requests. Shutdown asks active run tasks to stop cleanly.

### Frontend

The frontend lives under **frontend/src/** and uses:

- React and TypeScript;
- Vite for development and production builds;
- TanStack Query for server state;
- Tailwind CSS and Radix primitives for UI;
- Recharts for interactive charts.

The development server proxies API requests to FastAPI. A production build is
served directly by FastAPI, so a normal local installation needs only one
process.

## Domain model

Cases and sets are editable library objects. Runs are historical records. A run
contains run items; a run item has attempts, scores, and artifacts.

At planning time, Gaugix freezes:

- case input, expected output, scoring configuration, tags, and notes;
- set identity, name, selected case count, available case count, and universe
  hash;
- executor, model, harness, parameters, pricing, and judge selection.

**RunItem** is the durable relationship between a run, set context, case, and
executor. Set and case history pages query these immutable records rather than
storing duplicated run-id arrays on mutable entities.

## Run lifecycle

1. **Preflight** validates selected sets, executors, scorers, judges, code
   execution requirements, and an estimated item/cost envelope.
2. **Planning** expands selected cases times executors into ordered run items
   and writes all frozen snapshots before execution starts.
3. **Invocation** runs each executor lane through its harness with bounded
   concurrency and retries.
4. **Scoring** appends scorer results and computes the item verdict.
5. **Aggregation** updates run totals without treating unscored items as
   passes or missing cost as zero.
6. **Events** publish status and usage deltas over SSE while durable state stays
   authoritative in SQLite.

Cancellation marks unstarted work as skipped. Startup recovery changes an
in-progress run to interrupted and makes unfinished items resumable. A rerun
supersedes old attempts instead of deleting them. Re-scoring appends score
versions against the stored output.

## Harnesses

The harness interface isolates how an executor is invoked:

- **direct** sends a chat-style request through the configured model provider;
- **cli** runs a local command in an isolated working directory with a minimal,
  allowlisted environment;
- **fake** returns deterministic scripted responses for demos and tests.

All harnesses return the same invocation result shape: output, messages, token
usage, latency, cost, retry count, error category, and artifacts.

## Scoring

Scorers produce an optional boolean pass, optional numeric value, rationale,
and metadata. The aggregate verdict is:

- false when a required resolved scorer fails;
- true when every required resolved scorer passes;
- unresolved when no scorer has produced a verdict;
- flagged for human review while a human scorer remains unresolved.

LLM judge calls use the same harness layer as evaluated outputs, so judge usage
and cost are included. Each judge score stores the judge identity, rubric hash,
scale, parsed signals, and contradiction notes.

Python scorers run in an isolated Python subprocess with a timeout, but this is
not a security sandbox. Importing or executing unknown scorer code requires a
stronger operating-system isolation boundary.

## Persistence and reliability

- SQLite runs in WAL mode with foreign keys and a busy timeout.
- Schema migrations run automatically at server startup.
- State transitions are committed frequently so process interruption loses at
  most in-flight work.
- Backup uses SQLite's backup API and packages the database with artifacts and
  restore instructions. Environment files are never included.
- Reports are self-contained HTML files with inline CSS, SVG, and small
  progressive-enhancement scripts; they make no external requests.

## Security boundary

Gaugix intentionally has no authentication or multi-tenant isolation. It must
remain bound to loopback or another explicitly trusted environment. API keys
are read from environment variables and are not persisted in the database.

HTML artifacts use sandboxed iframes. Native artifacts, CLI tools, Python
scorers, and explicit artifact execution can run local code and must be treated
as untrusted. See [SECURITY.md](../SECURITY.md).

## Repository layout

    backend/
      migrations/          Alembic migrations
      src/gaugix/
        api/                FastAPI routers
        artifacts/          extraction, storage, rendering, execution
        benchmarks/         catalog, adapters, samples, installers
        engine/             planning, running, events, recovery
        harness/            direct, CLI, and fake invocation adapters
        learn/              built-in evaluation guide
        models/             SQLModel persistence models
        report/             self-contained report generation
        scoring/            assertions, Python, judge, human aggregation
      tests/                unit, engine, and API tests
    frontend/
      e2e/                  Playwright golden path
      src/
        api/                typed API hooks
        components/         shared UI and domain components
        pages/              route-level screens
    docs/
      images/               reviewed README screenshots

## Test strategy

- Unit tests cover scoring, normalization, pricing, parsing, benchmark
  adapters, backup, and pure presentation utilities.
- Engine tests use real planning and persistence with deterministic fake
  harnesses, including retry, cancellation, recovery, and rerun behavior.
- API tests use a temporary SQLite database per test and no provider network
  calls.
- Frontend tests cover API handling and key domain components.
- One Playwright golden path exercises the built application end to end.

**make check** runs the full static, type, backend, and frontend suite.
**make e2e** builds the UI and runs the browser workflow.
