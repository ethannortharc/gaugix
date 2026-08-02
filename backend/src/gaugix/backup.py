"""Backup: everything that cannot be regenerated, in one zip (PRD F8.2).

What goes in: the SQLite database and the artifacts directory. What stays out:
`.env` (secrets never travel in a backup, and the restore procedure says to
recreate it), logs, and the smoke-call counter.

The database is copied through SQLite's own backup API rather than by reading
the file. A live WAL-mode database on disk is not a consistent snapshot — the
committed truth is split between the `.db` and its `-wal`, and a plain file copy
taken mid-write restores to something that never existed.
"""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from gaugix.config import Settings, get_settings

#: Never backed up: secrets, and things that are not state.
EXCLUDED_NAMES = {".env", ".smoke_calls"}
EXCLUDED_DIRS = {"logs", "tmp"}


def default_backup_path(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return cfg.resolved_data_dir / "backups" / f"gaugix-backup-{stamp}.zip"


def _snapshot_database(db_path: Path, into: Path) -> None:
    """A consistent copy of a live WAL-mode database."""
    into.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(into)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def create_backup(destination: Path | None = None, settings: Settings | None = None) -> Path:
    """Write a backup zip and return its path."""
    cfg = settings or get_settings()
    target = destination or default_backup_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)

    db_path = cfg.resolved_db_path
    staged_db = target.parent / f".{target.stem}.db"

    try:
        if db_path.is_file():
            _snapshot_database(db_path, staged_db)

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            if staged_db.is_file():
                archive.write(staged_db, arcname=f"data/{db_path.name}")

            artifacts = cfg.resolved_data_dir / "artifacts"
            for path in sorted(artifacts.rglob("*")) if artifacts.is_dir() else []:
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(cfg.resolved_data_dir)
                if relative.parts[0] in EXCLUDED_DIRS or path.name in EXCLUDED_NAMES:
                    continue
                # A backup directory inside data/ would nest backups in backups.
                if "backups" in relative.parts:
                    continue
                archive.write(path, arcname=f"data/{relative}")

            archive.writestr("RESTORE.md", RESTORE_INSTRUCTIONS)
    finally:
        staged_db.unlink(missing_ok=True)

    return target


RESTORE_INSTRUCTIONS = """# Restoring a Gaugix backup

This archive contains your database and artifacts. It deliberately does **not**
contain `.env` — API keys never travel in a backup.

1. Stop Gaugix if it is running.
2. Move your current `data/` aside rather than deleting it:
   `mv data data.before-restore`
3. Unzip this archive at the repo root, which recreates `data/`:
   `unzip gaugix-backup-*.zip`
4. Recreate `.env` with your provider keys.
5. Start Gaugix. Migrations run automatically on boot, so a backup from an
   older version upgrades itself.

To check the restore worked: the dashboard should show your sets and recent
runs, and opening any item should show its stored output.
"""


def main() -> int:
    """`make backup` entry point."""
    from gaugix.config import load_dotenv_into_environ

    load_dotenv_into_environ()
    path = create_backup()
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Backup written: {path} ({size_mb:.1f} MB)")
    print("It contains the database and artifacts, and excludes .env by design.")
    print("Restore instructions are inside the archive as RESTORE.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
