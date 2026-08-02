# Contributing to Gaugix

Thank you for helping improve Gaugix. Bug reports, benchmark-method corrections, focused features, documentation fixes, and tests are welcome.

## Before opening an issue

- Search existing issues first.
- For bugs, include the Gaugix version, operating system, reproduction steps, expected behavior, and sanitized logs when useful.
- Never include API keys, `.env` contents, private prompts, model outputs, or user data.
- For benchmark changes, identify the dataset revision, license, published scoring method, and every intentional deviation.

Security vulnerabilities should be reported privately as described in [SECURITY.md](SECURITY.md), not through a public issue.

## Development setup

```bash
git clone https://github.com/ethannortharc/gaugix.git
cd gaugix
make setup
make check
```

Start the development servers with:

```bash
make dev
```

Tests use isolated SQLite databases and the deterministic fake harness. They must not require provider credentials or network model calls.

## Pull requests

1. Keep the change focused and explain the user-facing behavior.
2. Add tests for new behavior and regressions.
3. Run `make check`; run `make e2e` for workflow or UI changes.
4. Update the README or architecture documentation when public behavior changes.
5. Use your own Git identity. Do not add automated co-author or generated-by trailers.

For evaluation logic, prefer explicit failure over silently changing the measurement. Preserve frozen run history and distinguish unknown values from zero.

## Style

- Python is formatted and linted with Ruff and typed with mypy.
- TypeScript is formatted with Prettier, linted with ESLint, and checked with `tsc`.
- Follow existing domain language: case, set, executor, run, run item, attempt, and score.
