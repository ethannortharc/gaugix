# Running Gaugix in Docker

One container, one process, one port. The API serves the built UI — the same single-process mode as `make build && make dev-api` — so there is no separate web container and no reverse proxy to configure.

Everything that must outlive the image lives in a Docker volume mounted at `/data`: the SQLite database, artifacts, exports, logs, and backups. Rebuilding or replacing the image never touches it.

## Quick start

```bash
GAUGIX_HOST_PORT=8317 docker compose -f docker/compose.yaml up -d --build
```

Open [http://127.0.0.1:8317](http://127.0.0.1:8317).

`GAUGIX_HOST_PORT` is optional and defaults to `8317`. Set it when that port is already taken — a `make dev-api` running outside Docker holds exactly this port.

> Docker Compose v2 is required. If your Docker CLI has no `compose` subcommand, the standalone `docker-compose` binary works identically; substitute it in every command below.

### Load the offline demo

The bundled demo runs on deterministic fake executors, so the whole workflow works with no API key and no network model call.

```bash
docker compose -f docker/compose.yaml stop
docker compose -f docker/compose.yaml run --rm -e GAUGIX_FORCE=1 gaugix seed
docker compose -f docker/compose.yaml start
```

> [!CAUTION]
> `seed` erases everything in the data volume — database, artifacts, exports — before loading demo data. `GAUGIX_FORCE=1` is the confirmation. Stop the service first: the running server holds the database open.

To seed automatically the very first time a volume is used, uncomment `GAUGIX_SEED_ON_EMPTY: "1"` in `compose.yaml`. It only fires when `/data/gaugix.db` does not exist, so it can never overwrite real data.

## Provider keys

`compose.yaml` reads the repository-root `.env` at start time. Keys are never copied into an image layer — `.env` is excluded from the build context by `.dockerignore`.

```bash
cp .env.example .env      # then fill in only the providers you use
docker compose -f docker/compose.yaml up -d
```

Changing `.env` requires a restart to take effect: `docker compose -f docker/compose.yaml up -d`.

The app-level settings in `.env` (`GAUGIX_PORT`, `GAUGIX_DATA_DIR`) are deliberately overridden by `compose.yaml`, because inside the container those are fixed by the image layout. Set the container-facing values in `compose.yaml` instead.

## Where the data lives

The default is a named volume, `gaugix_gaugix-data`:

```bash
docker volume inspect gaugix_gaugix-data
```

Named rather than a bind mount on purpose. SQLite runs in WAL mode, and WAL depends on file-locking semantics that the virtualised filesystems backing bind mounts on macOS and Windows do not always reproduce faithfully. A named volume is a native Linux filesystem inside the VM, which is what SQLite expects.

### Using a host directory instead

If you want the files directly on your host and you are on Linux — or you accept the locking caveat above — replace the volume in `compose.yaml`:

```yaml
    volumes:
      - ../data:/data          # instead of: gaugix-data:/data
```

and delete the top-level `volumes:` block. The container runs as uid/gid 1000, which matches the first human account on a typical Linux host. If your host user differs, either `chown -R 1000:1000 data` or pin the container to your own ids:

```yaml
    user: "${UID:-1000}:${GID:-1000}"
```

## Backups

`gaugix.backup` snapshots the database through SQLite's own backup API, so a live WAL database produces a consistent archive. It excludes `.env` by design.

```bash
docker compose -f docker/compose.yaml exec gaugix python -m gaugix.backup
docker compose -f docker/compose.yaml cp gaugix:/data/backups ./backups
```

Restore instructions travel inside each archive as `RESTORE.md`.

## Upgrading

```bash
git pull
docker compose -f docker/compose.yaml up -d --build
```

Alembic migrations run automatically on boot (`upgrade_to_head` in the app's lifespan), so a volume written by an older version upgrades itself. Take a backup first if the data matters.

`docker compose down` stops and removes the container but keeps the volume. `docker compose down -v` **deletes the volume and all evaluation data.**

## Exposure and security

Gaugix has no authentication layer and no tenant isolation. Read [SECURITY.md](../SECURITY.md) before changing anything in this section.

Two separate addresses are in play, and only one of them is a security boundary:

| | Address | What it controls |
|---|---|---|
| Inside the container | `GAUGIX_BIND_HOST`, default `0.0.0.0` | Which interfaces uvicorn listens on *within the container's own network namespace*. Not reachable from anywhere until a port is published. |
| On the host | the `ports:` entry, default `127.0.0.1:8317` | Who can actually reach Gaugix. **This is the boundary.** |

The default publishes to `127.0.0.1`, so Gaugix is reachable only from the machine running Docker. Changing it to `"8317:8317"` publishes on every host interface and hands an unauthenticated application to your entire network. This is what ARCHITECTURE's security boundary means by "loopback or another explicitly trusted environment": the container plus a loopback-published port is such an environment; a LAN-published port is not.

Note that other containers on the same Docker network can still reach the service directly, published port or not. Keep Gaugix on its own network if that matters.

`GAUGIX_HOST` — the application's own loopback guard — has no effect here and is ignored with a warning if it is inherited from a workstation `.env`. It rejects any non-loopback value at settings construction, which would abort the container before its first log line; the entrypoint drops it so that a shared `.env` cannot break the container.

## Command reference

Every command assumes `-f docker/compose.yaml`.

| Command | Purpose |
|---|---|
| `docker compose up -d --build` | Build if needed, then start in the background. |
| `docker compose logs -f` | Follow the application log. |
| `docker compose ps` | Status, including the health check. |
| `docker compose stop` / `start` | Stop and restart without recreating. |
| `docker compose down` | Remove the container; **keeps** the data volume. |
| `docker compose down -v` | Remove the container **and delete all data**. |
| `docker compose run --rm -e GAUGIX_FORCE=1 gaugix seed` | Reset the volume and load demo data. |
| `docker compose exec gaugix python -m gaugix.backup` | Write a backup into `/data/backups`. |
| `docker compose run --rm gaugix sh` | A shell in the runtime image. |

The image entrypoint understands `serve` (default), `seed`, and `backup`; anything else is executed verbatim.

## How the image is built

Three stages, from the repository root as build context:

1. **`web`** — `node:22-bookworm-slim` runs `npm ci && npm run build`. Debian rather than Alpine because Tailwind v4 and Vite depend on native binaries whose glibc builds are the best-tested ones. Playwright browser downloads are skipped; they are only needed by `make e2e` on a workstation.
2. **`api`** — the `uv` image resolves `backend/uv.lock` with `--locked --no-dev`. Dependencies install before the source is copied, so editing `backend/src` reuses the dependency layer.
3. **`runtime`** — `python:3.12-slim-bookworm` receives the virtualenv, the backend source, Alembic migrations, and the built UI. It runs as the non-root `gaugix` user.

The runtime layout deliberately mirrors the repository:

```
/app
  backend/.venv/        the resolved environment
  backend/src/gaugix/   the package (installed editable, so this path is load-bearing)
  backend/migrations/   Alembic revisions
  frontend/dist/        the built UI
/data                   the volume
```

That mirroring is required, not stylistic. `config.py` derives `REPO_ROOT` from its own file location (`parents[3]`), and `main.py` derives `FRONTEND_DIST` from `REPO_ROOT`. Installing the wheel into `site-packages` instead would resolve `REPO_ROOT` to somewhere inside the Python installation and the UI would silently 404.

The build uses no BuildKit-only syntax, so it works with either builder.

## Troubleshooting

**`Bind for 127.0.0.1:8317 failed: port is already allocated`** — something else owns the port, most likely a local `make dev-api`. Start with `GAUGIX_HOST_PORT=18317 docker compose ... up -d`.

**The UI loads but the health chip is red** — check `docker compose logs`. A failed migration on boot is the usual cause; the log line comes from `alembic.runtime.migration`.

**`PermissionError` on `/data`** — a bind mount whose host directory is owned by a uid other than 1000. See *Using a host directory instead*.

**The container is `unhealthy`** — `curl http://127.0.0.1:${GAUGIX_HOST_PORT:-8317}/api/health` from the host. The check requires `status: "ok"`; `degraded` means the process is up but the database is not reachable.

**Changes to `.env` seem ignored** — `env_file` is read when the container is created. Re-run `docker compose up -d`; `restart` alone reuses the old environment.
