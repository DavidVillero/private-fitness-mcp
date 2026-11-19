"""Opt-in REAL MySQL contract tests. Only an empty database named fitness_test is allowed."""

import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest
from fitness.database import open_store, DatabaseUnavailable
from fitness.queries import Queries, TOOLS
from fitness.migration import copy_database, fingerprint
from fitness.store import Store

CONFIG = os.environ.get("FITNESS_MYSQL_TEST_CONFIG")
pytestmark = pytest.mark.skipif(
    not CONFIG,
    reason="Docker MySQL not enabled; set FITNESS_MYSQL_TEST_CONFIG to an empty fitness_test database",
)


def test_real_mysql_contract(tmp_path, monkeypatch):
    cfg = json.loads(Path(CONFIG).read_text())
    assert cfg["database"] == "fitness_test", (
        "Refusing to test against a real fitness database"
    )
    store = open_store(config_path=CONFIG)
    store.initialize()
    with store.connect(True) as c:
        assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM batches").fetchone()["n"] == 0
    # Migration preserves exact identity spelling, payloads, tombstones and receipt digests.
    source = Store(tmp_path / "synthetic.sqlite")
    source.initialize()

    def record(ident, modified="2020-10-17T02:00:00Z", count=123):
        return {
            "origin": "com.garmin.android.apps.connectmobile",
            "record_id": ident,
            "kind": "steps",
            "start": "2020-10-17T00:00:00Z",
            "end": "2020-10-17T01:00:00Z",
            "modified": modified,
            "data": {"count": count},
        }

    def batch(ident, records=(), deletions=()):
        return {
            "schema_version": 1,
            "batch_id": ident,
            "records": list(records),
            "deletions": list(deletions),
        }

    source.ingest(batch("original", [record(i) for i in ("A", "a", "A ", "日本語")]))
    source.ingest(
        batch(
            "tombstone",
            deletions=[
                {
                    "origin": record("x")["origin"],
                    "record_id": "x",
                    "modified": "2020-10-17T03:00:00Z",
                }
            ],
        )
    )
    copy_database(source.path, tmp_path / "snapshot.sqlite", store)
    with source.connect(True) as a, store.connect(True) as b:
        for table in ("records", "batches"):
            assert fingerprint(a, table) == fingerprint(b, table)
    original = batch("original", [record(i) for i in ("A", "a", "A ", "日本語")])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(store.ingest, [original, original]))
    assert all(r["duplicate_batch"] for r in results)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(store.ingest, [batch("concurrent-new"), batch("concurrent-new")])
        )
    assert sorted(r["duplicate_batch"] for r in results) == [False, True]
    with pytest.raises(ValueError):
        store.ingest(batch("original"))
    store.ingest(batch("corrected", [record("A", "2020-10-17T04:00:00Z", 150)]))
    store.ingest(batch("stale", [record("A"), record("x")]))
    rows = store.read("2020-10-01T00:00:00Z", "2020-11-01T00:00:00Z")
    assert len(rows) == 4
    assert next(r for r in rows if r["record_id"] == "A")["data"]["count"] == 150
    # Reader SQL account itself must reject writes, in addition to READ ONLY transactions.
    readonly = open_store(config_path=CONFIG, readonly=True)
    with pytest.raises(DatabaseUnavailable):
        with readonly.connect() as c:
            c.execute("DELETE FROM records")
    with pytest.raises(DatabaseUnavailable):
        with readonly.connect() as c:
            c.raw.rollback()  # Exit the read-only transaction; SQL grants must still deny writes.
            c.execute("UPDATE records SET deleted=1")
    for tool in TOOLS:
        assert Queries(readonly).call(tool, {"end_date": "2020-10-17"}) is not None
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_daily_metrics",
                "arguments": {"end_date": "2020-10-17"},
            },
        },
    ]
    env = {**os.environ, "FITNESS_DB_CONFIG": str(Path(CONFIG).resolve())}
    run = subprocess.run(
        [sys.executable, "-m", "fitness", "mcp"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    assert run.returncode == 0
    assert not json.loads(run.stdout.splitlines()[-1])["result"]["isError"]
    from fitness.sources import ZEPP

    zepp = record("A")
    zepp["origin"] = ZEPP
    zepp["kind"] = "oxygen_saturation"
    zepp["data"] = {
        "percent": 97,
        "_provenance": {"source_app": ZEPP, "unit": "percent", "device": None},
    }
    store.ingest(batch("zepp-new-metric", [zepp]))
    assert store.ingest(batch("zepp-new-metric", [zepp]))["duplicate_batch"]
    assert (
        readonly.read("2020-10-01T00:00:00Z", "2020-11-01T00:00:00Z", origin=ZEPP)[0][
            "data"
        ]["percent"]
        == 97
    )
    coverage = Queries(readonly).call(
        "get_source_coverage", {"end_date": "2020-10-17", "days": 1, "timezone": "UTC"}
    )
    assert (
        coverage["sources"]["zepp"]["metrics"]["oxygen_saturation"]["status"]
        == "observed"
    )
    from fastapi.testclient import TestClient
    from fitness import api

    token = tmp_path / "synthetic-token"
    token.write_text("x" * 48)
    monkeypatch.setattr(api, "open_store", lambda _: store)
    client = TestClient(api.create_app(None, token))
    assert client.post("/v1/ingest", json=batch("api-test")).status_code == 401
    headers = {"Authorization": "Bearer " + "x" * 48}
    assert (
        client.post("/v1/ingest", json=batch("api-test"), headers=headers).status_code
        == 200
    )
    assert client.post("/v1/ingest", json=batch("api-test"), headers=headers).json()[
        "duplicate_batch"
    ]
    # Real refused MySQL connection must produce retryable, payload-free HTTP.
    import socket

    reserved = socket.socket()
    reserved.bind(("127.0.0.1", 0))
    try:
        store.config["port"] = reserved.getsockname()[1]
        reply = client.post("/v1/ingest", json=batch("outage-test"), headers=headers)
        assert reply.status_code == 503 and reply.headers["retry-after"] == "30"
        assert reply.json() == {"detail": "temporarily unavailable"}
    finally:
        reserved.close()
