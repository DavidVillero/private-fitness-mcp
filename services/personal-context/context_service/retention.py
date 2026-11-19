"""Explicit operator-only retention. No age-based deletion runs automatically."""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from .storage import ROOT, Store, now


def purge_record(store, ident, confirmation):
    if confirmation != ident:
        raise ValueError("Confirmation must match exact record ID")
    with store.connect(False) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM records WHERE id=?", (ident,)).fetchone()
        if not row or not row["deleted"]:
            raise ValueError(
                "Soft-delete record first; active records cannot be purged"
            )
        if c.execute("SELECT 1 FROM links WHERE related_id=?", (ident,)).fetchone():
            raise ValueError("Referenced by another record; resolve links first")
        payload = json.loads(row["payload"])
        c.execute("DELETE FROM records_fts WHERE id=?", (ident,))
        c.execute("DELETE FROM links WHERE record_id=?", (ident,))
        c.execute("DELETE FROM versions WHERE record_id=?", (ident,))
        c.execute(
            "DELETE FROM idempotency WHERE json_extract(result,'$.id')=?", (ident,)
        )
        c.execute("DELETE FROM records WHERE id=?", (ident,))
        c.execute(
            "INSERT INTO audit(record_id,action,timestamp,actor,authorization,version) VALUES(?,?,?,?,?,?)",
            (ident, "purge", now(), "operator", "user_requested", row["version"]),
        )
        sha = payload.get("content_hash") if row["category"] == "file" else None
        if sha:
            # Remove only a service-owned hash path, and only when no retained version references it.
            if c.execute(
                "SELECT 1 FROM records WHERE json_extract(payload,'$.content_hash')=? UNION SELECT 1 FROM versions WHERE json_extract(payload,'$.content_hash')=?",
                (sha, sha),
            ).fetchone():
                sha = None
    if sha:
        target = store.root / "files" / sha
        if (
            target.is_file()
            and not target.is_symlink()
            and target.parent == store.root / "files"
        ):
            target.unlink()
    # SQLite logical deletion is not a promise of forensic erasure from WAL, disk or backups.
    return {
        "purged_record": ident,
        "retained": "audit metadata and independent backups; logical deletion is not forensic erasure",
    }


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("purge")
    q.add_argument("record_id")
    q.add_argument("--confirm-record-id", required=True)
    q = sub.add_parser("preview-backups")
    q.add_argument("--older-than-days", type=int, default=30)
    args = p.parse_args()
    if args.command == "purge":
        result = purge_record(
            Store(args.data_dir), args.record_id, args.confirm_record_id
        )
    else:
        if args.older_than_days < 1:
            raise ValueError("Positive age required")
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.older_than_days)
        result = {
            "action": "preview_only",
            "candidates": [
                str(d)
                for d in (ROOT / "backups").iterdir()
                if d.is_dir()
                and datetime.fromtimestamp(d.stat().st_mtime, timezone.utc) < cutoff
            ],
            "note": "Review and move selected backups to macOS Trash manually. No backups removed automatically.",
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
