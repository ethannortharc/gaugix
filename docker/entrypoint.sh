#!/bin/sh
# Gaugix container entrypoint.
#
# Subcommands mirror the Makefile targets that make sense in a container:
#
#     serve    (default)  run the API + built UI
#     seed                load synthetic demo data (destructive, see below)
#     backup              write a consistent archive into /data/backups
#
# Anything else is executed verbatim, so `docker compose run --rm gaugix sh`
# and `... gaugix python -m gaugix.backup` both work.
set -eu

PORT="${GAUGIX_PORT:-8317}"
BIND="${GAUGIX_BIND_HOST:-0.0.0.0}"
DATA_DIR="${GAUGIX_DATA_DIR:-/data}"

# GAUGIX_HOST is the application's loopback guard: Settings rejects anything
# outside 127.0.0.1/localhost/::1, and a rejected value raises during settings
# construction — the container would die before printing a useful line. In here
# the bind address comes from GAUGIX_BIND_HOST and reachability is decided by
# which host address the port is published to, so a GAUGIX_HOST inherited from
# a workstation .env is dropped with an explanation instead of being fatal.
case "${GAUGIX_HOST:-}" in
  '' | 127.0.0.1 | localhost | ::1) ;;
  *)
    echo "gaugix: ignoring GAUGIX_HOST=${GAUGIX_HOST} — inside the container the" >&2
    echo "        bind address is GAUGIX_BIND_HOST (${BIND}); control exposure by" >&2
    echo "        choosing what to publish the port to (see docker/README.md)." >&2
    unset GAUGIX_HOST
    ;;
esac

# Optional first-run convenience: seed only when there is demonstrably nothing
# to lose. The database file is the test, so this can never overwrite real data
# even if the flag is left on.
seed_if_empty() {
  [ "${GAUGIX_SEED_ON_EMPTY:-0}" = "1" ] || return 0
  [ -f "${DATA_DIR}/gaugix.db" ] && return 0
  echo "gaugix: GAUGIX_SEED_ON_EMPTY=1 and no database at ${DATA_DIR}/gaugix.db — seeding demo data." >&2
  GAUGIX_FORCE=1 gaugix seed
}

case "${1:-serve}" in
  serve)
    seed_if_empty
    # `gaugix serve` would bind settings.host (loopback) and be unreachable
    # from outside the container, so uvicorn is invoked directly. Flags match
    # `make dev-api` minus --reload.
    exec uvicorn gaugix.main:app --host "$BIND" --port "$PORT"
    ;;
  seed)
    shift
    exec gaugix seed "$@"
    ;;
  backup)
    shift
    exec python -m gaugix.backup "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
