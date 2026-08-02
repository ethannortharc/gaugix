"""Gaugix — a local-first LLM evaluation workbench."""

import os

__version__ = "0.1.0"

# litellm fetches its model-cost map over the network at import time unless told
# to use the copy bundled in the wheel. Gaugix is local-first and its tests must
# pass with no network at all, so the bundled map is the only one we use (D-023).
# This has to be set before anything imports litellm, hence the package root.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
