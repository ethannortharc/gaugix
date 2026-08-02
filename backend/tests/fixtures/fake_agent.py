#!/usr/bin/env python
"""A stand-in for a real CLI agent, so the CliHarness can be tested for free.

Gate G6 requires the CLI harness be exercised without a real agent. This script
is that agent: it reads the prompt file, writes files into its working directory
the way a coding agent would, and prints a generic JSON usage envelope.

Behaviour is keyed off the prompt so one script can play every part:

* `timeout`  — sleep past any sane timeout
* `fail`     — exit non-zero with a message on stderr
* `noisy`    — write a file larger than a small size cap
* anything else — write `solution.py` and `notes.md`, then report usage
"""

from __future__ import annotations

import json
import pathlib
import sys
import time


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fake_agent.py PROMPT_FILE", file=sys.stderr)
        return 2

    prompt_path = pathlib.Path(sys.argv[1])
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
    workdir = pathlib.Path.cwd()

    if "timeout" in prompt:
        time.sleep(30)
        return 0

    if "fail" in prompt:
        print("the agent could not complete the task", file=sys.stderr)
        return 3

    if "noisy" in prompt:
        (workdir / "huge.bin").write_bytes(b"x" * 4096)
        (workdir / "small.txt").write_text("kept", encoding="utf-8")
    else:
        (workdir / "solution.py").write_text('def solve():\n    return "ok"\n', encoding="utf-8")
        (workdir / "notes.md").write_text("# Notes\n\nDid the thing.\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": "Here is the solution:\n\n```python\ndef solve():\n    return 'ok'\n```",
                "usage": {"input_tokens": 12, "output_tokens": 34},
                "total_cost_usd": 0.00042,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
