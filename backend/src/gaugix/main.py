"""FastAPI application factory.

Startup order matters: logging → data dirs → schema → recovery scan (M2+), so that
a crash-interrupted run is reclassified before any client can look at it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from gaugix import __version__
from gaugix.api import health
from gaugix.config import REPO_ROOT, get_settings, load_dotenv_into_environ
from gaugix.db import get_engine
from gaugix.engine.recovery import recover_interrupted_runs
from gaugix.errors import install_error_handlers
from gaugix.logging_setup import configure_logging, get_logger
from gaugix.migrate import upgrade_to_head

log = get_logger("gaugix.main")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_dirs()
    # Tests build their schema directly; the server migrates itself on boot so
    # nobody has to remember `alembic upgrade head` after pulling.
    if os.environ.get("GAUGIX_SKIP_CREATE_ALL") != "1":
        upgrade_to_head(settings)

    # Any run still claiming to be `running` died with the last process.
    report = recover_interrupted_runs(get_engine())
    if report.runs_interrupted:
        log.warning(
            "recovered_runs",
            runs=report.runs_interrupted,
            items=report.items_reclassified,
        )
    log.info(
        "gaugix_start",
        version=__version__,
        data_dir=str(settings.resolved_data_dir),
        db=str(settings.resolved_db_path),
    )
    yield

    # Stop any in-flight runs cleanly so the next boot has less to recover.
    from gaugix.engine.runner import registry

    await registry.cancel_all()
    log.info("gaugix_stop")


def create_app() -> FastAPI:
    """Build the ASGI app. Safe to call repeatedly (tests do)."""
    load_dotenv_into_environ()
    configure_logging()

    # Connect scoring to the engine. The runner has no scoring import of its own,
    # so this single call is what makes runs produce verdicts.
    from gaugix.scoring import install_runner_hook

    install_runner_hook()

    app = FastAPI(
        title="Gaugix",
        version=__version__,
        description="Local-first LLM evaluation workbench",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)

    # /api/health (unversioned, per ARCHITECTURE §7)
    app.include_router(health.router, prefix="/api")

    v1 = APIRouter(prefix="/api/v1")
    _mount_v1_routers(v1)
    app.include_router(v1)

    _mount_frontend(app)
    return app


def _mount_v1_routers(v1: APIRouter) -> None:
    """Attach every /api/v1 router. Extended as milestones land."""
    from gaugix.api import (
        artifacts,
        benchmarks,
        cases,
        compare,
        executors,
        gen,
        learn,
        runs,
        scores,
        sets,
        settings,
    )

    v1.include_router(cases.router)
    v1.include_router(benchmarks.router)
    v1.include_router(sets.router)
    v1.include_router(gen.router)
    v1.include_router(executors.router)
    v1.include_router(runs.router)
    v1.include_router(settings.router)
    v1.include_router(scores.router)
    v1.include_router(compare.router)
    v1.include_router(artifacts.router)
    v1.include_router(learn.router)


def _mount_frontend(app: FastAPI) -> None:
    """Serve `frontend/dist` at / after `make build` (single-process mode).

    In dev the Vite server owns the browser and proxies /api here, so a missing
    dist directory is normal and must not be an error.
    """
    if not FRONTEND_DIST.is_dir():

        @app.get("/", include_in_schema=False)
        def _no_frontend() -> dict[str, str]:
            return {
                "status": "ok",
                "message": (
                    "Gaugix API is running. The UI is served by Vite on :5173 in dev "
                    "(`make dev`), or run `make build` to serve it from here."
                ),
                "health": "/api/health",
                "docs": "/api/docs",
            }

        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = FRONTEND_DIST / "index.html"

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str) -> FileResponse:
        """Client-side routing: any non-API path falls back to index.html."""
        # An unknown API route must still answer with the JSON error envelope —
        # handing the frontend an HTML page would break every error path.
        if full_path.startswith(("api/", "artifact-app/")):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file() and _is_within(candidate, FRONTEND_DIST):
            return FileResponse(candidate)
        return FileResponse(index)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


app = create_app()
