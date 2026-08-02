"""Writing and reading artifact files (PRD F6.1, ARCHITECTURE §3).

Layout: `data/artifacts/{run_id}/{item_id}/{attempt_n}/{filename}`. Predictable
enough to navigate in Finder, which matters the first time someone wants to open
a generated Go file in their editor.

Every path that reaches the filesystem goes through `resolve()`, which refuses
anything that escapes the artifacts root. Artifact filenames can come from a
model's fence info or a CLI agent's working directory — neither is trusted input,
and `../../.ssh/id_rsa` is exactly the filename an attacker would choose.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, col, select

from gaugix.config import get_settings
from gaugix.models.artifacts import Artifact

#: Anything outside this is replaced — no separators, no traversal, no control chars.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Per-file cap for collected workdir files (PRD F6.1). Configurable per harness.
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


@dataclass(slots=True)
class StoredArtifact:
    kind: str
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    rel_path: str
    language: str | None = None
    block_index: int | None = None


def artifacts_root() -> Path:
    return get_settings().resolved_data_dir / "artifacts"


def safe_filename(name: str, fallback: str = "file") -> str:
    """A filename that cannot escape its directory, however hostile the input."""
    # Take the last component first: "../../etc/passwd" must not survive as a path.
    base = Path(name).name
    cleaned = UNSAFE.sub("_", base).strip("._-")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:120]


def resolve(rel_path: str) -> Path:
    """An absolute path inside the artifacts root, or a refusal.

    The guard is `Path.relative_to` on the *resolved* path, so symlinks and
    `..` segments are both caught — checking the string alone would not be.
    """
    root = artifacts_root().resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes the artifacts root: {rel_path!r}") from exc
    return candidate


def attempt_dir(run_id: int, item_id: int, attempt_n: int) -> Path:
    return artifacts_root() / str(run_id) / str(item_id) / str(attempt_n)


def write_artifact(
    *,
    run_id: int,
    item_id: int,
    attempt_n: int,
    filename: str,
    content: bytes,
    kind: str,
    mime: str = "text/plain",
    language: str | None = None,
    block_index: int | None = None,
) -> StoredArtifact:
    """Write one file and describe it. Does not touch the database."""
    directory = attempt_dir(run_id, item_id, attempt_n)
    directory.mkdir(parents=True, exist_ok=True)
    name = safe_filename(filename)
    path = directory / name
    path.write_bytes(content)

    root = artifacts_root()
    return StoredArtifact(
        kind=kind,
        filename=name,
        mime=mime,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        rel_path=str(path.relative_to(root)),
        language=language,
        block_index=block_index,
    )


def persist(session: Session, attempt_id: int, stored: StoredArtifact) -> Artifact:
    row = Artifact(
        attempt_id=attempt_id,
        kind=stored.kind,
        filename=stored.filename,
        mime=stored.mime,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        rel_path=stored.rel_path,
        language=stored.language,
        block_index=stored.block_index,
    )
    session.add(row)
    return row


def read_artifact(artifact: Artifact) -> bytes:
    path = resolve(artifact.rel_path)
    if not path.is_file():
        raise FileNotFoundError(f"artifact file is missing: {artifact.rel_path}")
    return path.read_bytes()


def artifacts_for_attempt(session: Session, attempt_id: int) -> list[Artifact]:
    return list(
        session.exec(
            select(Artifact)
            .where(Artifact.attempt_id == attempt_id)
            .order_by(col(Artifact.kind), col(Artifact.block_index), col(Artifact.id))
        ).all()
    )


def artifacts_for_attempts(session: Session, attempt_ids: list[int]) -> list[Artifact]:
    if not attempt_ids:
        return []
    return list(
        session.exec(
            select(Artifact)
            .where(col(Artifact.attempt_id).in_(attempt_ids))
            .order_by(col(Artifact.attempt_id), col(Artifact.kind), col(Artifact.id))
        ).all()
    )


def collect_workdir(
    workdir: Path, *, skip: set[str] | None = None, max_bytes: int = DEFAULT_MAX_BYTES
) -> list[tuple[str, bytes]]:
    """Files a CLI agent left behind, as `(relative name, bytes)`.

    Oversized files are skipped rather than truncated — half a binary is worse
    than none, and the size cap exists to protect the disk, not to sample.
    """
    if not workdir.is_dir():
        return []
    skip = skip or set()
    out: list[tuple[str, bytes]] = []
    for path in sorted(workdir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = str(path.relative_to(workdir))
        if relative in skip:
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
            out.append((relative, path.read_bytes()))
        except OSError:
            continue
    return out


def remove_run_artifacts(run_id: int) -> None:
    """Delete a run's artifact directory. Used when a run is deleted."""
    directory = artifacts_root() / str(run_id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
