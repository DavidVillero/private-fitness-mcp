"""Local-only freshness metadata. No measurement values, model calls or notifications."""

from datetime import datetime, timezone
from .store import instant


def sync_health(store, now=None):
    now = now or datetime.now(timezone.utc)
    with store.connect(True) as conn:
        last = conn.execute("SELECT max(received) AS last FROM batches").fetchone()[
            "last"
        ]
        completed = conn.execute(
            "SELECT max(received) AS last FROM batches WHERE batch_id LIKE 'sync-complete-%'"
        ).fetchone()["last"]
        background = conn.execute(
            "SELECT max(received) AS last FROM batches WHERE batch_id LIKE 'sync-complete-background-%'"
        ).fetchone()["last"]
    age = None if last is None else max(0, (now - instant(last)).total_seconds() / 3600)
    return {
        "state": "waiting_for_data"
        if age is None
        else "delayed"
        if age > 6
        else "recent_import",
        "last_import_utc": last,
        "last_completed_phone_sync_utc": completed,
        "last_completed_background_sync_utc": background,
        "hours_since_import": None if age is None else round(age, 2),
        "note": "Includes direct imports and phone batches. Recent receipt does not prove full measurement coverage or future scheduled work. A completion receipt confirms the paired app finished sending its outbox, including retries; it does not attest watch accuracy.",
    }
