"""One-way verified copy into an EMPTY MySQL database. Source SQLite is never edited."""

import hashlib
import json
import sqlite3
from pathlib import Path
from .store import Store

TABLES = {
    "records": (
        "origin",
        "record_id",
        "kind",
        "start",
        "end",
        "modified",
        "data",
        "deleted",
    ),
    "batches": ("batch_id", "digest", "received"),
}


def normalized(row, columns):
    return [
        row[k].decode("utf-8") if isinstance(row[k], bytes) else row[k] for k in columns
    ]


def fingerprint(connection, table):
    columns = TABLES[table]
    order = "origin,record_id" if table == "records" else "batch_id"
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):
        digest.update(
            json.dumps(
                normalized(row, columns), ensure_ascii=True, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        count += 1
    return count, digest.hexdigest()


def copy_database(source, snapshot, target):
    snapshot = Path(snapshot)
    if snapshot.exists():
        raise ValueError("Snapshot destination already exists")
    snapshot.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot.touch(mode=0o600, exist_ok=False)
    # Online SQLite backup yields a consistent snapshot even if called before quiescing.
    # Activation MUST quiesce ingestion and copy again; this function never switches services.
    with Store(source).connect(True) as original:
        backup = sqlite3.connect(snapshot)
        try:
            original.backup(backup)
        finally:
            backup.close()
    with Store(snapshot).connect(True) as source_db, target.connect() as destination:
        for table in TABLES:
            if destination.execute(f"SELECT count(*) AS n FROM {table}").fetchone()[
                "n"
            ]:
                raise ValueError("Destination must be empty; no data was overwritten")
        proof = {}
        for table, columns in TABLES.items():
            placeholders = ",".join("?" for _ in columns)
            for row in source_db.execute(f"SELECT * FROM {table}"):
                destination.execute(
                    f"INSERT INTO {table} VALUES ({placeholders})",
                    normalized(row, columns),
                )
            expected = fingerprint(source_db, table)
            actual = fingerprint(destination, table)
            if expected != actual:
                raise RuntimeError(
                    "Migration verification failed; transaction rolled back"
                )
            proof[table] = {"copied_and_verified": True}
    return proof
