import json
import sqlite3
import subprocess
import sys
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from fitness.store import Store, instant
from fitness.api import create_app
from fitness.queries import Queries, bounds, iso, TOOLS


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "fitness.sqlite")
    s.initialize()
    return s


def record(
    ident="one",
    kind="heart_rate",
    data=None,
    start="2020-10-17T12:00:00Z",
    end="2020-10-17T12:01:00Z",
    modified="2020-10-17T13:00:00Z",
):
    return {
        "origin": "com.garmin.android.apps.connectmobile",
        "record_id": ident,
        "kind": kind,
        "start": start,
        "end": end,
        "modified": modified,
        "data": data or {"samples": [{"time": start, "bpm": 62}]},
    }


def batch(*records, ident="batch", deletions=None):
    return {
        "schema_version": 1,
        "batch_id": ident,
        "records": list(records),
        "deletions": deletions or [],
    }


def read(s):
    return s.read("2020-10-01T00:00:00Z", "2020-11-01T00:00:00Z")


def test_retry_and_correction(store):
    b = batch(record())
    store.ingest(b)
    assert store.ingest(b)["duplicate_batch"]
    store.ingest(batch(record(), ident="retry"))
    assert len(read(store)) == 1
    r = record(modified="2020-10-17T14:00:00Z")
    r["data"]["samples"][0]["bpm"] = 65
    store.ingest(batch(r, ident="updated"))
    store.ingest(batch(record(), ident="stale"))
    assert read(store)[0]["data"]["samples"][0]["bpm"] == 65
    with pytest.raises(ValueError):
        store.ingest(batch(r))


def test_transaction_rollback_and_validation(store):
    r = record()
    r["start"] = "2020-10-17T12:00:00"
    with pytest.raises(ValueError):
        store.ingest(batch(record(), r))
    assert read(store) == []
    r = record()
    r["data"]["samples"][0]["bpm"] = float("nan")
    with pytest.raises(ValueError):
        store.ingest(batch(r))


def test_deletion_no_resurrection(store):
    store.ingest(batch(record()))
    store.ingest(
        batch(
            ident="deleted",
            deletions=[
                {
                    "origin": record()["origin"],
                    "record_id": "one",
                    "modified": "2020-10-17T14:00:00Z",
                }
            ],
        )
    )
    store.ingest(batch(record(), ident="old-replay"))
    assert read(store) == []


def test_readonly(store):
    with store.connect(True) as c:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM records")


def test_authentication_and_size(store, tmp_path):
    secret = tmp_path / "token"
    secret.write_text("x" * 48)
    with TestClient(create_app(store.path, secret)) as client:
        assert client.post("/v1/ingest", json=batch(record())).status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 48}
        assert (
            client.post("/v1/ingest", json=batch(record()), headers=headers).status_code
            == 200
        )
        assert client.post("/v1/ingest", json=batch(record()), headers=headers).json()[
            "duplicate_batch"
        ]
        assert (
            client.post(
                "/v1/ingest", content=b" " * 2_000_001, headers=headers
            ).status_code
            == 413
        )
        assert (
            client.post("/v1/ingest", json={"oops": 1}, headers=headers).status_code
            == 422
        )


def test_dst_and_local_dates(store):
    a, b = bounds("2020-11-01", "America/Chicago")
    assert (instant(iso(b)) - instant(iso(a))).total_seconds() == 25 * 3600
    a, b = bounds("2020-03-08", "America/Chicago")
    assert (instant(iso(b)) - instant(iso(a))).total_seconds() == 23 * 3600
    store.ingest(
        batch(record(start="2020-10-18T02:00:00Z", end="2020-10-18T02:00:00Z"))
    )
    q = Queries(store)
    assert q.daily("2020-10-17", "America/Chicago")["heart_rate"]["sample_count"] == 1
    assert q.daily("2020-10-18", "America/Chicago")["heart_rate"]["sample_count"] == 0


def test_sleep_not_awake_and_not_resting_hr(store):
    r = record(
        kind="sleep",
        start="2020-10-17T04:00:00Z",
        end="2020-10-17T12:00:00Z",
        data={
            "stages": [
                {
                    "start": "2020-10-17T04:00:00Z",
                    "end": "2020-10-17T11:00:00Z",
                    "stage": "light",
                },
                {
                    "start": "2020-10-17T11:00:00Z",
                    "end": "2020-10-17T12:00:00Z",
                    "stage": "awake",
                },
            ]
        },
    )
    store.ingest(batch(r, record(ident="hr")))
    d = Queries(store).daily("2020-10-17", "America/Chicago")
    assert d["sleep_hours"] == 7
    assert d["resting_heart_rate_bpm"] is None
    assert (
        Queries(store).recovery("2020-10-17", "America/Chicago")["status"]
        == "insufficient_data"
    )


def test_recovery_requires_multiple_signals(store):
    from datetime import date

    records = []
    for i in range(24):
        d = date(2020, 10, 1) + timedelta(days=i)
        recent = i >= 21
        records.append(
            record(
                str(i),
                kind="resting_heart_rate",
                start=f"{d}T12:00:00Z",
                end=f"{d}T12:00:00Z",
                modified=f"{d}T13:00:00Z",
                data={"bpm": 65 if recent else 55},
            )
        )
    store.ingest(batch(*records))
    q = Queries(store)
    assert q.recovery("2020-10-24", "America/Chicago")["status"] == "insufficient_data"
    for i in range(24):
        d = date(2020, 10, 1) + timedelta(days=i)
        r = record(
            "v" + str(i),
            kind="hrv_rmssd",
            start=f"{d}T12:00:00Z",
            end=f"{d}T12:00:00Z",
            modified=f"{d}T13:00:00Z",
            data={"ms": 30 if i >= 21 else 60},
        )
        store.ingest(batch(r, ident="v" + str(i)))
    assert (
        q.recovery("2020-10-24", "America/Chicago")["status"]
        == "multiple_adverse_signals"
    )


def test_source_filter_and_steps_overlap(store):
    other = record()
    other["origin"] = "other.app"
    store.ingest(batch(other))
    assert (
        Queries(store).daily("2020-10-17", "America/Chicago")["heart_rate"][
            "sample_count"
        ]
        == 0
    )
    store.ingest(
        batch(
            record("steps1", kind="steps", data={"count": 100}),
            record("steps2", kind="steps", data={"count": 100}),
            ident="steps",
        )
    )
    assert Queries(store).daily("2020-10-17", "America/Chicago")["steps"] is None


def test_mcp_subprocess_all_tools(store):
    store.ingest(batch(record()))
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    requests += [
        {
            "jsonrpc": "2.0",
            "id": i + 3,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {"end_date": "2020-10-17"}},
        }
        for i, tool in enumerate(TOOLS)
    ]
    result = subprocess.run(
        [sys.executable, "-m", "fitness", "--db", str(store.path), "mcp"],
        input="".join(json.dumps(x) + "\n" for x in requests),
        capture_output=True,
        text=True,
        check=True,
    )
    responses = [json.loads(x) for x in result.stdout.splitlines()]
    assert len(responses) == len(TOOLS) + 2
    assert len(responses[1]["result"]["tools"]) == len(TOOLS) + 3
    assert all(not r["result"]["isError"] for r in responses[2:])
    daily = json.loads(responses[2]["result"]["content"][0]["text"])
    assert daily["heart_rate"]["sample_mean_bpm"] == 62


def test_interrupted_ingestion_retry(store):
    store.ingest(batch(record()))
    reopened = Store(store.path)
    assert reopened.ingest(batch(record()))["duplicate_batch"]
    assert len(read(reopened)) == 1


def test_unknown_sleep_not_zero(store):
    r = record(
        kind="sleep",
        data={
            "stages": [
                {
                    "start": "2020-10-17T12:00:00Z",
                    "end": "2020-10-17T12:01:00Z",
                    "stage": "unknown",
                }
            ]
        },
    )
    store.ingest(batch(r))
    assert Queries(store).daily("2020-10-17", "America/Chicago")["sleep_hours"] is None


def test_bad_mcp_input(store):
    from fitness.mcp_server import handle

    q = Queries(store)
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_daily_metrics",
                "arguments": {"timezone": "not/a/timezone"},
            },
        },
        q,
    )
    assert response["result"]["isError"]
    assert (
        handle({"jsonrpc": "2.0", "id": 2, "method": "delete"}, q)["error"]["code"]
        == -32601
    )


def test_authenticated_ingestion_to_mcp_end_to_end(store, tmp_path):
    token = tmp_path / "token"
    token.write_text("prototype-token-" * 4)
    with TestClient(create_app(store.path, token)) as client:
        response = client.post(
            "/v1/ingest",
            json=batch(record()),
            headers={"Authorization": "Bearer " + "prototype-token-" * 4},
        )
        assert response.status_code == 200
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_daily_metrics",
                "arguments": {"end_date": "2020-10-17"},
            },
        },
    ]
    result = subprocess.run(
        [sys.executable, "-m", "fitness", "--db", str(store.path), "mcp"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(result.stdout.splitlines()[-1])
    value = json.loads(response["result"]["content"][0]["text"])
    assert value["heart_rate"]["sample_mean_bpm"] == 62


def test_delete_before_record_and_mismatched_batch_id(store):
    d = {
        "origin": record()["origin"],
        "record_id": "one",
        "modified": "2020-10-17T14:00:00Z",
    }
    store.ingest(batch(ident="delete-first", deletions=[d]))
    store.ingest(batch(record()))
    assert read(store) == []
    with pytest.raises(ValueError):
        store.ingest(batch(record(ident="different")))


def test_records_cannot_inject_query(store):
    r = record()
    r["origin"] = "garmin' OR 1=1;--"
    store.ingest(batch(r))
    assert Queries(store).daily("2020-10-17", "America/Chicago")["record_count"] == 0


def test_ingest_ack_is_bound_to_batch(store, tmp_path):
    token = tmp_path / "token"
    token.write_text("test-ack-token-" * 4)
    with TestClient(create_app(store.path, token)) as client:
        headers = {"Authorization": "Bearer " + token.read_text()}
        first = client.post(
            "/v1/ingest", json=batch(record(), ident="bound-ack"), headers=headers
        ).json()
        again = client.post(
            "/v1/ingest", json=batch(record(), ident="bound-ack"), headers=headers
        ).json()
        assert first["batch_id"] == "bound-ack"
        assert again["batch_id"] == "bound-ack" and again["duplicate_batch"]


def test_busy_database_is_retryable_without_payload_leak(store, tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("retry-test-token-" * 4)

    def busy(self, payload):
        raise sqlite3.OperationalError("database is locked; sensitive diagnostic")

    with TestClient(create_app(store.path, token)) as client:
        monkeypatch.setattr(Store, "ingest", busy)
        response = client.post(
            "/v1/ingest",
            json=batch(record()),
            headers={"Authorization": "Bearer " + token.read_text()},
        )
        assert response.status_code == 503 and response.headers["retry-after"] == "30"
        assert "sensitive" not in response.text and "62" not in response.text


def test_freshness_never_means_measurement_completeness(store):
    from fitness.operations import sync_health

    assert sync_health(store)["state"] == "waiting_for_data"
    store.ingest(batch(record()))
    with store.connect(True) as c:
        last = instant(c.execute("SELECT max(received) FROM batches").fetchone()[0])
    assert sync_health(store, last + timedelta(hours=7))["state"] == "delayed"
    assert sync_health(store, last)["state"] == "recent_import"
    assert "does not prove" in sync_health(store, last)["note"]


def test_unix_socket_ingestion_transport(tmp_path):
    import time
    import tempfile
    import httpx

    # macOS has short Unix socket path limits; keep this test socket under /tmp.
    with tempfile.TemporaryDirectory(prefix="fit-uds-", dir="/tmp") as folder:
        root = __import__("pathlib").Path(folder)
        token = root / "token"
        token.write_text("uds-synthetic-token-" * 4)
        db = root / "test.sqlite"
        sock = root / "ingest.sock"
        code = 'import os;os.umask(0o077);import uvicorn;from fitness.api import create_app;from fitness.service import bind_private_socket;uvicorn.Server(uvicorn.Config(create_app(__import__("sys").argv[1],__import__("sys").argv[2]),log_level="critical",access_log=False)).run(sockets=[bind_private_socket(__import__("sys").argv[3])])'
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(db), str(token), str(sock)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if sock.exists():
                    break
                assert process.poll() is None
                time.sleep(0.03)
            assert sock.exists() and sock.stat().st_mode & 0o077 == 0
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(sock)),
                base_url="http://localhost",
                timeout=5,
            ) as client:
                assert (
                    client.post("/v1/ingest", json=batch(record())).status_code == 401
                )
                r = client.post(
                    "/v1/ingest",
                    json=batch(record()),
                    headers={"Authorization": "Bearer " + token.read_text()},
                )
                assert r.status_code == 200 and r.json()["batch_id"] == "batch"
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_private_socket_does_not_replace_regular_file(tmp_path):
    from fitness.service import bind_private_socket

    p = tmp_path / "keep.txt"
    p.write_text("retain")
    with pytest.raises(RuntimeError):
        bind_private_socket(p)
    assert p.read_text() == "retain"


def test_completion_receipt_distinguishes_background_from_partial_data(store):
    from fitness.operations import sync_health

    store.ingest(batch(record()))
    assert sync_health(store)["last_completed_phone_sync_utc"] is None
    store.ingest(batch(ident="sync-complete-foreground-example"))
    health = sync_health(store)
    assert health["last_completed_phone_sync_utc"] is not None
    assert health["last_completed_background_sync_utc"] is None
    store.ingest(batch(ident="sync-complete-background-example"))
    assert sync_health(store)["last_completed_background_sync_utc"] is not None
    assert len(read(store)) == 1
