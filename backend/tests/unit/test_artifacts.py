"""Code-block extraction and the artifact store (PRD F6.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaugix.artifacts import store
from gaugix.artifacts.extract import extract_code_blocks, language_file

# -- extraction ----------------------------------------------------------------


def test_a_fenced_block_becomes_a_typed_file():
    blocks = extract_code_blocks("Here you go:\n\n```python\nprint(1)\n```\n")
    assert len(blocks) == 1
    assert blocks[0].content == "print(1)\n"
    assert blocks[0].filename == "block-1.py"
    assert blocks[0].mime == "text/x-python"


def test_several_blocks_keep_the_order_they_appeared_in():
    text = "```go\na\n```\ntext\n```sql\nb\n```"
    blocks = extract_code_blocks(text)
    assert [b.filename for b in blocks] == ["block-1.go", "block-2.sql"]
    assert [b.index for b in blocks] == [0, 1]


def test_an_unlabelled_fence_stays_a_txt_file():
    """Guessing an extension is a lie that only surfaces when someone runs it."""
    blocks = extract_code_blocks("```\nsome text\n```")
    assert blocks[0].filename == "block-1.txt"
    assert blocks[0].language is None


def test_an_unknown_language_is_recorded_but_not_guessed():
    blocks = extract_code_blocks("```brainfuck\n+++\n```")
    assert blocks[0].language == "brainfuck"
    assert blocks[0].filename.endswith(".txt")


def test_content_is_stored_byte_for_byte():
    text = "```python\n  indented = True   \n\n```"
    assert extract_code_blocks(text)[0].content == "  indented = True   \n\n"


def test_an_unclosed_final_fence_still_yields_its_block():
    """A truncated answer is exactly when you want to see how far it got."""
    blocks = extract_code_blocks("```python\nprint(1)\nprint(2)")
    assert len(blocks) == 1
    assert "print(2)" in blocks[0].content


def test_an_empty_fence_is_punctuation_not_a_file():
    assert extract_code_blocks("```python\n\n```") == []


def test_tilde_fences_work_too():
    blocks = extract_code_blocks("~~~js\nlet a = 1\n~~~")
    assert blocks[0].filename == "block-1.js"


def test_extra_info_after_the_language_is_ignored():
    blocks = extract_code_blocks('```python title="solution.py"\nx = 1\n```')
    assert blocks[0].language == "python"
    assert blocks[0].filename == "block-1.py"


def test_prose_with_no_fences_produces_nothing():
    assert extract_code_blocks("Just an explanation, no code.") == []
    assert extract_code_blocks("") == []


def test_language_file_numbers_from_one():
    assert language_file("python", 0)[0] == "block-1.py"
    assert language_file("python", 4)[0] == "block-5.py"


# -- store safety --------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../.ssh/id_rsa",
        "/etc/passwd",
        "..",
        ".",
        "....//....//etc/passwd",
        "with/slashes.py",
    ],
)
def test_a_hostile_filename_cannot_escape_its_directory(hostile: str):
    """Filenames come from model output and agent workdirs — never trusted."""
    safe = store.safe_filename(hostile)
    assert "/" not in safe
    assert safe not in {"", ".", ".."}


def test_a_normal_filename_survives_intact():
    assert store.safe_filename("solution.py") == "solution.py"
    assert store.safe_filename("my-notes_2.md") == "my-notes_2.md"


def test_resolve_refuses_a_path_outside_the_artifacts_root(isolated_data_dir: Path):
    store.artifacts_root().mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="escapes"):
        store.resolve("../../../etc/passwd")


def test_resolve_accepts_a_path_inside_the_root(isolated_data_dir: Path):
    store.artifacts_root().mkdir(parents=True, exist_ok=True)
    assert store.resolve("1/2/3/output.md").is_relative_to(store.artifacts_root().resolve())


# -- writing -------------------------------------------------------------------


def test_writing_an_artifact_records_its_size_and_hash(isolated_data_dir: Path):
    stored = store.write_artifact(
        run_id=1,
        item_id=2,
        attempt_n=1,
        filename="output.md",
        content=b"hello",
        kind="raw_output",
    )

    assert stored.size_bytes == 5
    assert len(stored.sha256) == 64
    assert stored.rel_path == "1/2/1/output.md"
    assert store.resolve(stored.rel_path).read_bytes() == b"hello"


def test_the_stored_path_is_relative_so_the_directory_can_be_moved(isolated_data_dir: Path):
    stored = store.write_artifact(
        run_id=1, item_id=1, attempt_n=1, filename="a.txt", content=b"x", kind="raw_output"
    )
    assert not Path(stored.rel_path).is_absolute()


def test_collecting_a_workdir_skips_what_it_is_told_to(tmp_path: Path):
    (tmp_path / "prompt.md").write_text("the prompt")
    (tmp_path / "answer.py").write_text("x = 1")

    collected = store.collect_workdir(tmp_path, skip={"prompt.md"})

    assert [name for name, _ in collected] == ["answer.py"]


def test_collecting_a_workdir_recurses_into_subdirectories(tmp_path: Path):
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    (nested / "mod.py").write_text("y = 2")

    collected = store.collect_workdir(tmp_path)

    assert [name for name, _ in collected] == ["src/pkg/mod.py"]


def test_collecting_a_missing_directory_is_empty_not_an_error(tmp_path: Path):
    assert store.collect_workdir(tmp_path / "nope") == []
