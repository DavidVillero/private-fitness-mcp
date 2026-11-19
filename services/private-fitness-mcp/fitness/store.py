import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .sources import UNITS

KINDS = set(UNITS)
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
 origin TEXT NOT NULL, record_id TEXT NOT NULL, kind TEXT NOT NULL,
 start TEXT NOT NULL, end TEXT NOT NULL, modified TEXT NOT NULL,
 data TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(origin, record_id));
CREATE INDEX IF NOT EXISTS records_time ON records(start,end,kind);
CREATE TABLE IF NOT EXISTS batches (
 batch_id TEXT PRIMARY KEY, digest TEXT NOT NULL, received TEXT NOT NULL);
"""


def instant(s):
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamps require an explicit UTC offset")
    return d.astimezone(timezone.utc)


def utc(s):
    return instant(s).isoformat()


def number(x, lo, hi):
    if (
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or not math.isfinite(x)
        or not lo <= x <= hi
    ):
        raise ValueError("measurement outside accepted bounds")
    return x


def validate(record):
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    r = dict(record)
    if set(r) != {"origin", "record_id", "kind", "start", "end", "modified", "data"}:
        raise ValueError("unexpected or missing record fields")
    for k in ["origin", "record_id"]:
        if not isinstance(r[k], str) or not 1 <= len(r[k]) <= 256:
            raise ValueError("invalid identity")
    if r["kind"] not in KINDS:
        raise ValueError("unsupported metric")
    for k in ["start", "end", "modified"]:
        r[k] = utc(r[k])
    if r["end"] < r["start"]:
        raise ValueError("end precedes start")
    d = r["data"]
    if not isinstance(d, dict):
        raise ValueError("data must be an object")
    d = dict(d)
    provenance = d.pop("_provenance", None)
    if provenance is not None:
        if (
            not isinstance(provenance, dict)
            or len(json.dumps(provenance, allow_nan=False)) > 8192
        ):
            raise ValueError("Invalid provenance")
        if provenance.get("source_app", r["origin"]) != r["origin"]:
            raise ValueError("Source provenance mismatch")
        if provenance.get("unit", UNITS[r["kind"]]) != UNITS[r["kind"]]:
            raise ValueError("Unit mismatch")
        device = provenance.get("device")
        if device is not None:
            if not isinstance(device, dict):
                raise ValueError("Invalid device metadata")
            for key in ("manufacturer", "model", "identifier"):
                value = device.get(key)
                if value is not None and (
                    not isinstance(value, str) or len(value) > 1024
                ):
                    raise ValueError("Invalid device identifier")
        for key in ("original_start", "original_end"):
            if (
                key in provenance
                and utc(provenance[key])
                != r["start" if key == "original_start" else "end"]
            ):
                raise ValueError("Timestamp provenance mismatch")
    ranges = {
        "resting_heart_rate": ("bpm", 20, 250),
        "hrv_rmssd": ("ms", 0, 1000),
        "steps": ("count", 0, 1000000),
        "weight": ("kg", 1, 500),
        "body_fat": ("percent", 0, 100),
        "oxygen_saturation": ("percent", 0, 100),
        "respiratory_rate": ("breaths_per_minute", 0, 200),
        "height": ("cm", 1, 300),
        "lean_body_mass": ("kg", 0, 500),
        "bone_mass": ("kg", 0, 100),
        "body_water_mass": ("kg", 0, 500),
        "distance": ("meters", 0, 10000000),
        "active_calories": ("kcal", 0, 100000),
        "total_calories": ("kcal", 0, 100000),
    }
    if r["kind"] in ranges:
        key, lo, hi = ranges[r["kind"]]
        if set(d) != {key}:
            raise ValueError("unexpected measurement fields")
        number(d[key], lo, hi)
        if key == "count" and int(d[key]) != d[key]:
            raise ValueError("steps must be integral")
    elif r["kind"] == "heart_rate":
        if (
            set(d) != {"samples"}
            or not isinstance(d["samples"], list)
            or not 1 <= len(d["samples"]) <= 10000
        ):
            raise ValueError("invalid heart rate samples")
        samples = []
        for s in d["samples"]:
            if set(s) != {"time", "bpm"}:
                raise ValueError("invalid sample fields")
            t = utc(s["time"])
            number(s["bpm"], 20, 250)
            if not r["start"] <= t <= r["end"]:
                raise ValueError("sample outside interval")
            samples.append({"time": t, "bpm": s["bpm"]})
        d = {"samples": samples}
    elif r["kind"] == "sleep":
        if set(d) != {"stages"} or not isinstance(d["stages"], list):
            raise ValueError("invalid sleep stages")
        stages = []
        for s in d["stages"]:
            if set(s) != {"start", "end", "stage"} or s["stage"] not in [
                "unknown",
                "awake",
                "sleeping",
                "out_of_bed",
                "light",
                "deep",
                "rem",
                "awake_in_bed",
            ]:
                raise ValueError("invalid sleep stage")
            a, b = utc(s["start"]), utc(s["end"])
            if not r["start"] <= a < b <= r["end"]:
                raise ValueError("stage outside session")
            stages.append({"start": a, "end": b, "stage": s["stage"]})
        stages.sort(key=lambda s: s["start"])
        if any(a["end"] > b["start"] for a, b in zip(stages, stages[1:])):
            raise ValueError("overlapping sleep stages")
        d = {"stages": stages}
    elif r["kind"] == "activity":
        if (
            set(d) != {"exercise_type"}
            or type(d["exercise_type"]) is not int
            or d["exercise_type"] < 0
        ):
            raise ValueError("invalid exercise type")
    if provenance is not None:
        d["_provenance"] = provenance
    r["data"] = d
    return r


def prepare_batch(batch):
    import hashlib

    if (
        not isinstance(batch, dict)
        or set(batch) != {"schema_version", "batch_id", "records", "deletions"}
        or type(batch["schema_version"]) is not int
        or batch["schema_version"] != 1
    ):
        raise ValueError("invalid batch envelope")
    if not isinstance(batch["batch_id"], str) or not 1 <= len(batch["batch_id"]) <= 128:
        raise ValueError("invalid batch ID")
    if (
        not isinstance(batch["records"], list)
        or not isinstance(batch["deletions"], list)
        or len(batch["records"]) + len(batch["deletions"]) > 1000
    ):
        raise ValueError("batch limit is 1000 records and deletions")
    records = [validate(r) for r in batch["records"]]
    deletions = []
    for d in batch["deletions"]:
        if set(d) != {"origin", "record_id", "modified"}:
            raise ValueError("invalid deletion")
        if any(
            not isinstance(d[k], str) or not 1 <= len(d[k]) <= 256
            for k in ["origin", "record_id"]
        ):
            raise ValueError("invalid deletion identity")
        deletions.append({**d, "modified": utc(d["modified"])})
    digest = hashlib.sha256(
        json.dumps(
            batch, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return records, deletions, digest


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self, readonly=False):
        uri = "file:" + quote(str(self.path), safe="/") + "?mode=ro"
        c = sqlite3.connect(
            uri if readonly else str(self.path), uri=readonly, timeout=10
        )
        c.row_factory = sqlite3.Row
        if readonly:
            c.execute("PRAGMA query_only=ON")
        try:
            with c:
                yield c
        finally:
            c.close()

    def ingest(self, batch):
        records, deletions, digest = prepare_batch(batch)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute(
                "SELECT digest FROM batches WHERE batch_id=?", (batch["batch_id"],)
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError("batch ID reused with different contents")
                return {"accepted": 0, "duplicate_batch": True}
            for r in records:
                c.execute(
                    """INSERT INTO records VALUES (?,?,?,?,?,?,?,0)
                ON CONFLICT(origin,record_id) DO UPDATE SET kind=excluded.kind,start=excluded.start,end=excluded.end,
                modified=excluded.modified,data=excluded.data,deleted=0 WHERE excluded.modified>records.modified""",
                    (
                        r["origin"],
                        r["record_id"],
                        r["kind"],
                        r["start"],
                        r["end"],
                        r["modified"],
                        json.dumps(r["data"], allow_nan=False),
                    ),
                )
            for d in deletions:
                c.execute(
                    """INSERT INTO records VALUES (?,?,'steps',?,?,?,'{}',1)
                ON CONFLICT(origin,record_id) DO UPDATE SET deleted=1,modified=excluded.modified
                WHERE excluded.modified>=records.modified""",
                    (
                        d["origin"],
                        d["record_id"],
                        d["modified"],
                        d["modified"],
                        d["modified"],
                    ),
                )
            c.execute(
                "INSERT INTO batches VALUES (?,?,?)",
                (batch["batch_id"], digest, datetime.now(timezone.utc).isoformat()),
            )
        return {"accepted": len(records) + len(deletions), "duplicate_batch": False}

    def read(
        self, start, end, kinds=None, origin="com.garmin.android.apps.connectmobile"
    ):
        start, end = utc(start), utc(end)
        if start >= end:
            raise ValueError("invalid query interval")
        sql = (
            "SELECT * FROM records WHERE deleted=0 AND start<? AND end>=? AND origin=?"
        )
        args = [end, start, origin]
        if kinds:
            sql += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
            args += list(kinds)
        with self.connect(True) as c:
            rows = c.execute(sql + " ORDER BY start,record_id", args).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]
