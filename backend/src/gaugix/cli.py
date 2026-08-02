"""`gaugix` command line entry point."""

from __future__ import annotations

import argparse
import sys

from gaugix import __version__
from gaugix.config import get_settings, load_dotenv_into_environ


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gaugix", description="Gaugix evaluation workbench")
    parser.add_argument("--version", action="version", version=f"gaugix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API server (loopback only)")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    sub.add_parser("seed", help="load demo data into the data directory")

    args = parser.parse_args(argv)
    load_dotenv_into_environ()
    settings = get_settings()

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "gaugix.main:app",
            host=settings.host,
            port=args.port or settings.port,
            reload=args.reload,
            log_config=None,
        )
        return 0

    if args.command == "seed":
        from gaugix.seed import seed_command

        exit_code: int = seed_command()
        return exit_code

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
