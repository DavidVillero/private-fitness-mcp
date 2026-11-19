"""Opt-in launchd entry point. Imports local inbox then generates local reports."""

import json
import os
import fcntl
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fitness.database import open_store  # noqa: E402 - import from this checkout after path bootstrap
from fitness.queries import Queries  # noqa: E402 - import from this checkout after path bootstrap
from fitness.operations import sync_health  # noqa: E402 - import from this checkout after path bootstrap


def run():
    os.umask(0o077)
    output = ROOT / "reports"
    output.mkdir(exist_ok=True, mode=0o700)
    lock = (output / "job.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    s = open_store()
    s.initialize()
    inbox = ROOT / "data/inbox"
    done = inbox / "processed"
    done.mkdir(parents=True, exist_ok=True, mode=0o700)
    failures = 0
    for path in sorted(inbox.glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            failures += 1
            continue
        try:
            s.ingest(json.loads(path.read_text()))
            path.replace(done / path.name)
        except (ValueError, KeyError, TypeError):
            failures += 1
    q = Queries(s)
    day = (
        datetime.now(ZoneInfo(os.environ.get("FITNESS_TIMEZONE", "UTC")))
        .date()
        .isoformat()
    )
    output = ROOT / "reports"
    output.mkdir(exist_ok=True, mode=0o700)
    reports = {
        "daily": {
            "sync_health": sync_health(s),
            "metrics": q.call("get_daily_metrics", {"end_date": day}),
            "recovery": q.call("get_recovery_summary", {"end_date": day}),
        }
    }
    # Rebuild rolling weekly report daily, so interrupted Mondays are recovered.
    reports["weekly"] = q.call("get_weekly_fitness_report", {"end_date": day})
    reports["operations"] = sync_health(s)
    for name, value in reports.items():
        path = output / f"{name}-{day}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    print(
        f"Local reports updated; invalid inbox file count={failures}. No model or network calls."
    )
    return bool(failures)


if __name__ == "__main__":
    sys.exit(run())
