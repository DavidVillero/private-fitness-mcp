"""Keep subprocess imports inside this checkout, never an installed private service."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The dashboard trusts only its Serve origin unless test hosts are opted in.
os.environ.setdefault("HQ_EXTRA_HOSTS", "testserver")
os.environ["PYTHONPATH"] = os.pathsep.join(
    str(ROOT / p)
    for p in [
        "services/private-fitness-mcp",
        "services/personal-context",
        ".",
    ]
)
