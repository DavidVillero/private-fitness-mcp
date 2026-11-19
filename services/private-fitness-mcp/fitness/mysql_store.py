"""MySQL storage with transactional retries and a separate SELECT-only identity."""

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .database import DatabaseUnavailable, ROOT
from .store import Store, prepare_batch

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS records (
    origin VARBINARY(1024) NOT NULL, record_id VARBINARY(1024) NOT NULL,
    kind VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `start` VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `end` VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    modified VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    data LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    deleted TINYINT NOT NULL DEFAULT 0, PRIMARY KEY(origin,record_id),
    INDEX records_time(`start`,`end`,kind)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS batches (
    batch_id VARBINARY(512) PRIMARY KEY,
    digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    received VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL) ENGINE=InnoDB""",
)


class Connection:
    """Small DB-API adapter for the shared read-only query surface."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        cursor = self.raw.cursor()
        sql = re.sub(r"\b(start|end)\b", r"`\1`", sql)
        if args:
            cursor.execute(sql.replace("?", "%s"), args)
        else:
            cursor.execute(sql)
        return cursor


class MySQLStore:
    def __init__(self, config, *, readonly=False):
        self.config = dict(config)
        self.readonly = readonly
        if config.get("host", "127.0.0.1") != "127.0.0.1":
            raise ValueError("This deployment permits localhost MySQL only")

    @contextmanager
    def connect(self, readonly=False):
        import pymysql

        ro = readonly or self.readonly
        account = self.config["reader" if ro else "writer"]
        password = (ROOT / Path(account["password_file"])).read_text().strip()
        raw = None
        try:
            raw = pymysql.connect(
                host="127.0.0.1",
                port=int(self.config.get("port", 3307)),
                user=account["user"],
                password=password,
                database=self.config["database"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
                read_timeout=30,
                write_timeout=30,
                autocommit=False,
                local_infile=False,
            )
            if ro:
                with raw.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                raw.begin()
            yield Connection(raw)
            if not ro:
                raw.commit()
        except pymysql.MySQLError:
            if raw is not None:
                try:
                    raw.rollback()
                except pymysql.MySQLError:
                    pass
            # Driver errors can contain query arguments, including clinical values.
            raise DatabaseUnavailable(
                "Local database temporarily unavailable"
            ) from None
        except BaseException:
            if raw is not None:
                try:
                    raw.rollback()
                except pymysql.MySQLError:
                    pass
            raise
        finally:
            if raw is not None:
                raw.close()

    def initialize(self):
        # Runtime users have no DDL rights. Provisioning creates the schema separately.
        with self.connect(True) as c:
            c.execute("SELECT digest FROM batches LIMIT 0")
            c.execute("SELECT origin FROM records LIMIT 0")

    def ingest(self, batch):
        if self.readonly:
            raise PermissionError("Read-only store")
        records, deletions, digest = prepare_batch(batch)
        with self.connect() as c:
            # A no-op duplicate update takes an exclusive key lock directly.
            # Catching duplicate INSERT then upgrading shared locks can deadlock
            # when two clients simultaneously replay an existing batch.
            claim = c.execute(
                "INSERT INTO batches VALUES (?,?,?) ON DUPLICATE KEY UPDATE digest=digest",
                (batch["batch_id"], digest, datetime.now(timezone.utc).isoformat()),
            )
            if claim.rowcount == 0:
                old = c.execute(
                    "SELECT digest FROM batches WHERE batch_id=? FOR UPDATE",
                    (batch["batch_id"],),
                ).fetchone()
                if old is None or old["digest"] != digest:
                    raise ValueError("batch ID reused with different contents")
                return {"accepted": 0, "duplicate_batch": True}
            # Record locks protect correction/deletion comparisons across concurrent writers.
            for r in records:
                args = (r["origin"], r["record_id"])
                old = c.execute(
                    "SELECT modified FROM records WHERE origin=? AND record_id=? FOR UPDATE",
                    args,
                ).fetchone()
                values = (
                    r["kind"],
                    r["start"],
                    r["end"],
                    r["modified"],
                    json.dumps(r["data"], allow_nan=False),
                )
                if old is None:
                    c.execute(
                        "INSERT INTO records VALUES (?,?,?,?,?,?,?,0)", args + values
                    )
                elif r["modified"] > old["modified"]:
                    c.execute(
                        "UPDATE records SET kind=?,start=?,end=?,modified=?,data=?,deleted=0 WHERE origin=? AND record_id=?",
                        values + args,
                    )
            for d in deletions:
                args = (d["origin"], d["record_id"])
                old = c.execute(
                    "SELECT modified FROM records WHERE origin=? AND record_id=? FOR UPDATE",
                    args,
                ).fetchone()
                if old is None:
                    c.execute(
                        "INSERT INTO records VALUES (?,?,'steps',?,?,?,'{}',1)",
                        args + (d["modified"],) * 3,
                    )
                elif d["modified"] >= old["modified"]:
                    c.execute(
                        "UPDATE records SET deleted=1,modified=? WHERE origin=? AND record_id=?",
                        (d["modified"],) + args,
                    )
        return {"accepted": len(records) + len(deletions), "duplicate_batch": False}

    def read(
        self, start, end, kinds=None, origin="com.garmin.android.apps.connectmobile"
    ):
        # Keep filtering, date boundaries and JSON semantics identical to SQLite.
        rows = Store.read(self, start, end, kinds, origin)
        for row in rows:
            for key in ("origin", "record_id"):
                if isinstance(row[key], bytes):
                    row[key] = row[key].decode("utf-8")
        return rows
