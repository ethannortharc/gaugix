# Gaugix — the single entry point for every workflow (ARCHITECTURE §14).
#
# Everything runs from the repo root. Python is managed by uv, Node by npm;
# nothing is installed globally and nothing needs sudo.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend
UV       := uv run --project $(BACKEND)
NPM      := npm --prefix $(FRONTEND)
PORT     ?= 8317
VITE_PORT ?= 5173

# Compose v2 ships either as a `docker` subcommand or as a standalone binary.
COMPOSE_BIN := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; else echo "docker-compose"; fi)
COMPOSE  := $(COMPOSE_BIN) -f docker/compose.yaml

# Colours only when attached to a terminal.
BOLD := $(shell tput bold 2>/dev/null)
DIM  := $(shell tput dim 2>/dev/null)
RST  := $(shell tput sgr0 2>/dev/null)

.PHONY: help setup dev dev-api dev-web check check-backend check-frontend test test-frontend \
        lint fmt typecheck e2e seed smoke build backup clean \
        docker-up docker-down docker-logs docker-seed

help: ## Show available targets
	@echo "$(BOLD)Gaugix$(RST) — local-first LLM evaluation workbench"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BOLD)%-16s$(RST) %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

setup: ## Install backend + frontend toolchains (idempotent)
	@echo "$(BOLD)▸ backend (uv sync)$(RST)"
	@uv sync --project $(BACKEND)
	@echo "$(BOLD)▸ frontend (npm install)$(RST)"
	@$(NPM) install --no-audit --no-fund
	@echo "$(BOLD)▸ playwright chromium$(RST)"
	@$(NPM) exec -- playwright install chromium 2>/dev/null \
	  || echo "$(DIM)  playwright chromium unavailable — 'make e2e' will report skipped$(RST)"
	@echo "$(BOLD)✓ setup complete$(RST)  →  make dev"

# ---------------------------------------------------------------------------
# development
# ---------------------------------------------------------------------------

dev: ## Run API (:8317) and Vite (:5173) together
	@$(NPM) exec -- concurrently --names "api,web" --prefix-colors "cyan,magenta" --kill-others \
	  "$(MAKE) dev-api" "$(MAKE) dev-web"

dev-api: ## Run only the API with reload
	@$(UV) uvicorn gaugix.main:app --host 127.0.0.1 --port $(PORT) --reload \
	  --reload-dir $(BACKEND)/src

dev-web: ## Run only the Vite dev server
	@$(NPM) run dev -- --port $(VITE_PORT)

# ---------------------------------------------------------------------------
# quality gates  (target: < 3 min; never includes e2e or real API calls)
# ---------------------------------------------------------------------------

check: check-backend check-frontend ## All fast gates: ruff, mypy, pytest, eslint, tsc, vitest
	@echo "$(BOLD)✓ make check green$(RST)"

check-backend:
	@echo "$(BOLD)▸ ruff$(RST)"        && cd $(BACKEND) && uv run ruff check .
	@echo "$(BOLD)▸ ruff format$(RST)" && cd $(BACKEND) && uv run ruff format --check .
	@echo "$(BOLD)▸ mypy$(RST)"        && cd $(BACKEND) && uv run mypy
	@echo "$(BOLD)▸ pytest$(RST)"      && cd $(BACKEND) && uv run pytest

check-frontend:
	@echo "$(BOLD)▸ eslint$(RST)"    && $(NPM) run lint -- --max-warnings 0
	@echo "$(BOLD)▸ prettier$(RST)"  && $(NPM) run format:check
	@echo "$(BOLD)▸ tsc$(RST)"       && $(NPM) run typecheck
	@echo "$(BOLD)▸ vitest$(RST)"    && $(NPM) run test

test: ## Backend tests only
	@cd $(BACKEND) && uv run pytest

test-frontend: ## Frontend tests only
	@$(NPM) run test

lint: ## Lint both sides
	@cd $(BACKEND) && uv run ruff check .
	@$(NPM) run lint

fmt: ## Auto-format both sides
	@cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .
	@$(NPM) run format

typecheck: ## Type-check both sides
	@cd $(BACKEND) && uv run mypy
	@$(NPM) run typecheck

# ---------------------------------------------------------------------------
# end-to-end (owned by M7; meaningful once M5's report export exists)
# ---------------------------------------------------------------------------

e2e: build ## Playwright golden path (builds the UI, then drives the real stack)
	@if [ -f $(FRONTEND)/playwright.config.ts ]; then \
	  $(NPM) run e2e; \
	else \
	  echo "$(DIM)make e2e: playwright.config.ts missing — run make setup.$(RST)"; \
	fi

# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

seed: ## Reset data/ and load demo data (requires GAUGIX_FORCE=1)
	@if [ -f $(BACKEND)/src/gaugix/seed.py ]; then \
	  $(UV) python -m gaugix.seed; \
	else \
	  echo "$(DIM)make seed: demo data arrives with M1 — not yet available (exit 0).$(RST)"; \
	fi

smoke: ## Real-API smoke — costs money, capped by GAUGIX_SMOKE_MAX_CALLS
	@if [ -f scripts/smoke_direct.py ]; then \
	  $(UV) python scripts/smoke_direct.py $(ARGS); \
	else \
	  echo "$(DIM)make smoke: arrives with M2 — not yet available (exit 0).$(RST)"; \
	fi

backup: ## Zip the database + artifacts (excludes .env; restore doc inside)
	@if $(UV) python -c "import gaugix.backup" 2>/dev/null; then \
	  $(UV) python -m gaugix.backup; \
	else \
	  echo "$(DIM)make backup: arrives with M7 — not yet available (exit 0).$(RST)"; \
	fi

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

build: ## Build the frontend; the API then serves it at http://127.0.0.1:8317
	@$(NPM) run build
	@echo "$(BOLD)✓ built$(RST) → run: make dev-api  (UI at http://127.0.0.1:$(PORT))"

# ---------------------------------------------------------------------------
# docker  (see docker/README.md; data lives in a volume, not in data/)
# ---------------------------------------------------------------------------

docker-up: ## Build and start the container (GAUGIX_HOST_PORT=... to change the port)
	@$(COMPOSE) up -d --build
	@echo "$(BOLD)✓ up$(RST) → http://127.0.0.1:$${GAUGIX_HOST_PORT:-$(PORT)}"

docker-down: ## Stop and remove the container (keeps the data volume)
	@$(COMPOSE) down
	@echo "$(DIM)data volume kept; 'docker compose -f docker/compose.yaml down -v' deletes it$(RST)"

docker-logs: ## Follow the container log
	@$(COMPOSE) logs -f

docker-seed: ## Reset the container's data volume and load demo data
	@if [ "$$GAUGIX_FORCE" != "1" ]; then \
	  echo "docker-seed deletes everything in the Gaugix data volume."; \
	  echo "Re-run with GAUGIX_FORCE=1 to confirm:"; \
	  echo ""; \
	  echo "    GAUGIX_FORCE=1 make docker-seed"; \
	  echo ""; \
	  exit 2; \
	fi
	@$(COMPOSE) stop
	@$(COMPOSE) run --rm -e GAUGIX_FORCE=1 gaugix seed
	@$(COMPOSE) start

clean: ## Remove build outputs and caches (never touches data/)
	@rm -rf $(FRONTEND)/dist $(FRONTEND)/node_modules/.tmp
	@find $(BACKEND) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	@echo "cleaned (data/ untouched)"
