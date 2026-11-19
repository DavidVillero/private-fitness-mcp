import json
import pytest
from fitness.database import open_store
from fitness.store import Store
from fitness.migration import copy_database, fingerprint


def seed(store):
    store.initialize()
    record = {
        "origin": "com.garmin.android.apps.connectmobile",
        "record_id": "A ",
        "kind": "steps",
        "start": "2020-10-17T00:00:00Z",
        "end": "2020-10-17T01:00:00Z",
        "modified": "2020-10-17T02:00:00Z",
        "data": {"count": 123},
    }
    store.ingest(
        {
            "schema_version": 1,
            "batch_id": "synthetic",
            "records": [record],
            "deletions": [],
        }
    )
    store.ingest(
        {
            "schema_version": 1,
            "batch_id": "deleted",
            "records": [],
            "deletions": [
                {
                    "origin": record["origin"],
                    "record_id": "missing",
                    "modified": record["modified"],
                }
            ],
        }
    )


def test_verified_copy_preserves_tombstones_receipts_and_source(tmp_path):
    source = Store(tmp_path / "source.sqlite")
    seed(source)
    target = Store(tmp_path / "target.sqlite")
    target.initialize()
    with source.connect(True) as c:
        before = {t: fingerprint(c, t) for t in ("records", "batches")}
    proof = copy_database(source.path, tmp_path / "snapshot.sqlite", target)
    assert all(p["copied_and_verified"] for p in proof.values())
    for store in (source, target, Store(tmp_path / "snapshot.sqlite")):
        with store.connect(True) as c:
            assert {t: fingerprint(c, t) for t in before} == before
    assert (tmp_path / "snapshot.sqlite").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="empty"):
        copy_database(source.path, tmp_path / "snapshot-two.sqlite", target)


def test_failed_verification_rolls_back_all_tables(tmp_path, monkeypatch):
    source = Store(tmp_path / "source.sqlite")
    seed(source)
    target = Store(tmp_path / "target.sqlite")
    target.initialize()
    import fitness.migration as migration

    original = migration.fingerprint
    calls = 0

    def mismatch(c, table):
        nonlocal calls
        calls += 1
        return original(c, table) if calls == 1 else (0, "wrong")

    monkeypatch.setattr(migration, "fingerprint", mismatch)
    with pytest.raises(RuntimeError, match="verification"):
        copy_database(source.path, tmp_path / "snapshot.sqlite", target)
    with target.connect(True) as c:
        for table in ("records", "batches"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_explicit_config_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        open_store(config_path=tmp_path / "missing.json")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"backend": "not-a-backend"}))
    with pytest.raises(ValueError):
        open_store(config_path=path)


def test_mysql_disallows_remote_database():
    from fitness.mysql_store import MySQLStore

    with pytest.raises(ValueError):
        MySQLStore({"host": "example.com"})


def test_mysql_readonly_object_cannot_ingest():
    from fitness.mysql_store import MySQLStore

    store = MySQLStore({"host": "127.0.0.1"}, readonly=True)
    with pytest.raises(PermissionError):
        store.ingest({})
