"""Copy a SQLite snapshot; never switches ingestion, MCP or report configuration."""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fitness.database import open_store  # noqa: E402 - import from this checkout after path bootstrap
from fitness.migration import copy_database  # noqa: E402 - import from this checkout after path bootstrap

if __name__ == "__main__":
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("--after-approval", action="store_true")
    p.add_argument("--source", default=str(ROOT / "data/fitness.sqlite"))
    p.add_argument("--config", default=str(ROOT / "config/mysql.local.json"))
    p.add_argument("--snapshot", required=True)
    args = p.parse_args()
    if not args.after_approval:
        raise SystemExit(
            "Approval required to access MySQL credentials and migrate health records."
        )
    try:
        target = open_store(config_path=args.config)
        target.initialize()
        proof = copy_database(args.source, args.snapshot, target)
    except (ValueError, RuntimeError, OSError):
        raise SystemExit(
            "Migration did not complete. Active configuration was not changed; inspect locally before retrying."
        ) from None
    proof["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    proof["active_backend_changed"] = False
    proof["source_snapshot"] = str(Path(args.snapshot).resolve())
    out = ROOT / "reports/mysql-migration.json"
    out.parent.mkdir(exist_ok=True, mode=0o700)
    out.write_text(json.dumps(proof, indent=2) + "\n")
    out.chmod(0o600)
    print(
        "All records, deletion markers and sync receipts copied and verified. Active backend unchanged."
    )
