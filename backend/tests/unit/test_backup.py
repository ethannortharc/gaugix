"""Backup contents and consistency (PRD F8.2)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from gaugix.backup import create_backup
from gaugix.config import get_settings


def make_artifact(text: str = "hello") -> Path:
    root = get_settings().resolved_data_dir / "artifacts" / "1" / "1" / "1"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "output.md"
    path.write_text(text)
    return path


def names_in(archive_path: Path) -> set[str]:
    with zipfile.ZipFile(archive_path) as archive:
        return set(archive.namelist())


def test_a_backup_contains_the_database_and_artifacts(engine, isolated_data_dir: Path):
    make_artifact()

    names = names_in(create_backup())

    assert any(name.endswith(".db") for name in names)
    assert "data/artifacts/1/1/1/output.md" in names


def test_a_backup_carries_its_own_restore_instructions():
    names = names_in(create_backup())
    assert "RESTORE.md" in names


def test_secrets_never_travel_in_a_backup(isolated_data_dir: Path):
    """`.env` is excluded by construction — a backup is not a key leak."""
    (isolated_data_dir / ".env").write_text("OPENAI_API_KEY=test-secret")

    with zipfile.ZipFile(create_backup()) as archive:
        blob = b"".join(archive.read(name) for name in archive.namelist())

    assert b"sk-secret" not in blob
    assert not any(".env" in name for name in names_in(create_backup()))


def test_backups_do_not_nest_inside_each_other(engine, isolated_data_dir: Path):
    make_artifact()
    first = create_backup()

    names = names_in(create_backup())

    assert not any(first.name in name for name in names)
    assert not any("backups" in name for name in names)


def test_the_database_copy_is_a_real_snapshot(engine, isolated_data_dir: Path):
    """Copied through SQLite's backup API — a WAL-mode file copy is not consistent."""
    import sqlite3

    archive_path = create_backup()
    with zipfile.ZipFile(archive_path) as archive:
        db_name = next(name for name in archive.namelist() if name.endswith(".db"))
        extracted = isolated_data_dir / "restored.db"
        extracted.write_bytes(archive.read(db_name))

    connection = sqlite3.connect(extracted)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()

    assert "run" in tables
    assert "eval_case" in tables
