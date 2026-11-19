"""Security and concurrency regressions using artificial, temporary inputs only."""

import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from context_service.api import create_app as context_app
from context_service.storage import Store as ContextStore
from context_service.tools import Service
from fitness.api import create_app as ingestion_app
from fitness.store import Store, prepare_batch, validate


@pytest.mark.parametrize("value", ["", "short", "x" * 31, "x" * 32 + " y", "é" * 40])
def test_context_rejects_unsafe_credentials_before_startup(tmp_path, value):
    token = tmp_path / "token"
    token.write_text(value)
    with pytest.raises(ValueError):
        context_app(Service(ContextStore(tmp_path / "unused")), {"write": token})


def test_context_rejects_duplicate_scope_credentials(tmp_path):
    token = tmp_path / "token"
    token.write_text("dummy-" * 8)
    with pytest.raises(ValueError, match="distinct"):
        context_app(
            Service(ContextStore(tmp_path / "unused")), {"read": token, "write": token}
        )


def test_context_token_file_truncation_cannot_enable_empty_bearer(tmp_path):
    store = ContextStore(tmp_path / "data")
    store.initialize()
    token = tmp_path / "token"
    token.write_text("dummy-" * 8)
    with TestClient(context_app(Service(store), {"read": token})) as client:
        token.write_text("")
        assert (
            client.get("/tools", headers={"Authorization": "Bearer "}).status_code
            == 401
        )
        assert (
            client.get(
                "/tools", headers={"Authorization": "Bearer " + "dummy-" * 8}
            ).status_code
            == 200
        )


def test_ingestion_database_work_does_not_block_event_loop(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("dummy-" * 8)
    app = ingestion_app(tmp_path / "data.sqlite", token)
    worker_threads = []

    def ingest(_store, _batch):
        worker_threads.append(threading.get_ident())
        return {"accepted": 0, "duplicate_batch": False}

    monkeypatch.setattr(Store, "ingest", ingest)

    async def exercise():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/ingest",
                headers={"Authorization": "Bearer " + "dummy-" * 8},
                json={
                    "schema_version": 1,
                    "batch_id": "dummy",
                    "records": [],
                    "deletions": [],
                },
            )
        assert response.status_code == 200
        assert worker_threads and all(
            worker != loop_thread for worker in worker_threads
        )

    asyncio.run(exercise())


def test_boolean_schema_version_is_not_an_integer_version():
    with pytest.raises(ValueError):
        prepare_batch(
            {
                "schema_version": True,
                "batch_id": "dummy",
                "records": [],
                "deletions": [],
            }
        )


@pytest.mark.parametrize("kind", [True, False, -1])
def test_activity_type_requires_nonnegative_integer(kind):
    with pytest.raises(ValueError):
        validate(
            {
                "origin": "synthetic",
                "record_id": "dummy",
                "kind": "activity",
                "start": "2000-01-01T00:00:00Z",
                "end": "2000-01-01T00:01:00Z",
                "modified": "2000-01-01T00:02:00Z",
                "data": {"exercise_type": kind},
            }
        )


@pytest.mark.parametrize("format", ["GIF", "BMP", "TIFF"])
def test_upload_rejects_decoders_outside_allowlist(tmp_path, monkeypatch, format):
    import io
    import app
    from PIL import Image

    monkeypatch.setattr(app, "STATE", tmp_path)
    raw = io.BytesIO()
    Image.new("RGB", (2, 2)).save(raw, format=format)
    headers = {
        "tailscale-user-login": app.LOGIN,
        "origin": app.ORIGIN,
        "x-hq-request": "1",
    }
    with TestClient(app.app) as client:
        response = client.post(
            "/api/photos", headers=headers, files={"file": ("image", raw.getvalue())}
        )
    assert response.status_code == 422
    assert not (tmp_path / "photos").exists()


def test_context_restore_rejects_tampering_and_existing_destination(tmp_path):
    from context_service.admin import backup, restore
    import json

    original = ContextStore(tmp_path / "original")
    original.initialize()
    saved = tmp_path / "backup"
    backup(original, saved)
    recovered = tmp_path / "recovered"
    assert restore(saved, recovered)["integrity"] == "ok"
    with pytest.raises(ValueError, match="new directory"):
        restore(saved, recovered)
    manifest = json.loads((saved / "manifest.json").read_text())
    name = next(iter(manifest["files"]))
    (saved / name).write_bytes(b"synthetic corruption")
    with pytest.raises(ValueError, match="checksum"):
        restore(saved, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize(
    "message,code",
    [
        (None, -32600),
        ({}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "missing"}, -32601),
    ],
)
def test_context_proxy_rejects_invalid_requests_without_network(message, code):
    from context_service.mcp import Proxy

    proxy = Proxy({"url": "http://127.0.0.1:8776"})
    assert proxy.handle(message)["error"]["code"] == code


def test_context_proxy_network_failure_is_redacted(monkeypatch):
    from context_service.mcp import Proxy

    proxy = Proxy({"url": "http://127.0.0.1:8776"})

    def fail(*args):
        raise OSError("synthetic-private-error-must-not-leak")

    monkeypatch.setattr(proxy, "request", fail)
    response = proxy.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "synthetic-private-error" not in str(response)
    assert "error" in response


def test_dashboard_crud_roundtrip_and_missing_record_errors(monkeypatch):
    import sqlite3
    import app

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for table, model in app.MODELS.items():
        columns = ["id TEXT PRIMARY KEY", "created_utc TEXT"] + [
            f"{key} TEXT" for key in model.model_fields
        ]
        connection.execute(f"CREATE TABLE {table} ({','.join(columns)})")

    def sql(query, args=(), fetch=False):
        cursor = connection.execute(query.replace("%s", "?"), args)
        connection.commit()
        return [dict(row) for row in cursor.fetchall()] if fetch else cursor.rowcount

    monkeypatch.setattr(app, "sql", sql)
    headers = {
        "tailscale-user-login": app.LOGIN,
        "origin": app.ORIGIN,
        "x-hq-request": "1",
    }
    fixtures = {
        "meals": {
            "day": "2020-01-01",
            "description": "Synthetic meal",
            "calories": 100,
        },
        "workouts": {
            "day": "2020-01-01",
            "category": "other",
            "exercise": "Synthetic movement",
        },
        "measurements": {"day": "2020-01-01", "weight_kg": 70},
    }
    try:
        with TestClient(app.app) as client:
            for table, value in fixtures.items():
                created = client.post("/api/" + table, headers=headers, json=value)
                assert created.status_code == 200
                path = "/api/" + table + "/" + created.json()["id"]
                assert (
                    client.put(
                        path, headers=headers, json={**value, "day": "2020-01-02"}
                    ).status_code
                    == 200
                )
                assert (
                    client.request("DELETE", path, headers=headers, json={}).status_code
                    == 200
                )
                assert client.put(path, headers=headers, json=value).status_code == 404
                assert (
                    client.request("DELETE", path, headers=headers, json={}).status_code
                    == 404
                )
            assert (
                client.post(
                    "/api/measurements", headers=headers, json={"day": "2020-01-01"}
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/meals",
                    headers=headers,
                    json={**fixtures["meals"], "photo_id": "a" * 32},
                ).status_code
                == 422
            )
            assert (
                client.request(
                    "DELETE", "/api/not-a-table/x", headers=headers, json={}
                ).status_code
                == 404
            )
    finally:
        connection.close()


def test_ingestion_socket_refuses_live_socket_and_recovers_stale(tmp_path):
    import socket
    from fitness.service import bind_private_socket

    # Use a short temporary socket path (Unix socket names have an OS size limit).
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="pf-sock-") as folder:
        path = Path(folder) / "ingest.sock"
        listener = bind_private_socket(path)
        assert path.stat().st_mode & 0o777 == 0o600
        with pytest.raises(RuntimeError, match="already serving"):
            bind_private_socket(path)
        listener.close()
        replacement = bind_private_socket(path)
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(str(path))
        finally:
            replacement.close()
