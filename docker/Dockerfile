# Gaugix — one container, one process, one port.
#
# The API serves the built UI (see `_mount_frontend` in gaugix/main.py), so the
# single-process production mode described in the README is exactly what runs
# here. Everything that must outlive the image lives under /data.
#
# Build from the repository root — the context is the repo, not docker/:
#
#     docker build -f docker/Dockerfile -t gaugix:0.1.0 .
#     docker compose -f docker/compose.yaml up -d --build

# -----------------------------------------------------------------------------
# stage 1 — frontend
# -----------------------------------------------------------------------------
# Debian rather than Alpine on purpose: Tailwind v4 and Vite pull in native
# binaries (lightningcss, @tailwindcss/oxide) whose glibc builds are the
# best-tested ones. This stage is discarded, so its size costs nothing.
FROM node:22-bookworm-slim AS web

# @playwright/test is a devDependency of the build. Its browsers are only used
# by `make e2e` on a workstation and would add hundreds of megabytes here.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    npm_config_audit=false \
    npm_config_fund=false

WORKDIR /src/frontend

# Lock file first: this layer is reused until a dependency actually changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# `npm run build` is `tsc -b && vite build`, and tsconfig.node.json also checks
# playwright.config.ts and eslint.config.js — so the whole directory is copied.
COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# stage 2 — python environment
# -----------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS api

# UV_PYTHON_DOWNLOADS=never keeps uv on the image's own interpreter, which is
# what makes the resulting .venv portable into the runtime stage below.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies resolve from the committed lock only; --locked fails loudly if
# uv.lock and pyproject.toml have drifted apart. Splitting this from the source
# copy below is what lets an edit to backend/src reuse the dependency layer.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./backend/
RUN uv sync --project backend --locked --no-dev --no-install-project

# Then the package itself. uv installs the project in editable mode, so the
# runtime stage must keep backend/src at this exact path.
COPY backend/src ./backend/src
RUN uv sync --project backend --locked --no-dev

# -----------------------------------------------------------------------------
# stage 3 — runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Gaugix" \
      org.opencontainers.image.description="A local-first workbench for building, running, auditing, and comparing LLM evaluations." \
      org.opencontainers.image.source="https://github.com/ethannortharc/gaugix" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:${PATH}" \
    GAUGIX_DATA_DIR=/data \
    GAUGIX_PORT=8317 \
    # Container-only knob, read by the entrypoint and handed to uvicorn. The
    # application's own GAUGIX_HOST stays loopback-only by design; what makes
    # this safe is publishing the port to 127.0.0.1 on the host. See docker/README.md.
    GAUGIX_BIND_HOST=0.0.0.0

# uid/gid 1000 matches the first human user on a typical Linux host, so a bind
# mount of ./data works without a chown dance.
RUN groupadd --gid 1000 gaugix \
 && useradd --uid 1000 --gid 1000 --home-dir /app --shell /usr/sbin/nologin gaugix

WORKDIR /app

COPY --from=api /app/backend/.venv ./backend/.venv
COPY backend/src ./backend/src
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/migrations ./backend/migrations
COPY --from=web /src/frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/gaugix-entrypoint

# /data is created here so a fresh named volume inherits this ownership.
RUN chmod +x /usr/local/bin/gaugix-entrypoint \
 && mkdir -p /data \
 && chown -R gaugix:gaugix /app /data

USER gaugix
EXPOSE 8317

# No curl in the slim image, and the venv's python is already on PATH.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,os,urllib.request; \
u='http://127.0.0.1:'+os.environ.get('GAUGIX_PORT','8317')+'/api/health'; \
raise SystemExit(0 if json.load(urllib.request.urlopen(u, timeout=4))['status']=='ok' else 1)"

ENTRYPOINT ["gaugix-entrypoint"]
CMD ["serve"]
