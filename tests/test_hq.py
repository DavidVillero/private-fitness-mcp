import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from PIL import Image
import app

H = {"tailscale-user-login": app.LOGIN, "origin": app.ORIGIN, "x-hq-request": "1"}
client = TestClient(app.app, raise_server_exceptions=False)


def test_boundary():
    assert client.get("/").status_code == 401
    assert client.get("/", headers=H).status_code == 200
    assert client.get("/", headers={**H, "host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/meals", headers={**H, "origin": "https://evil.example"}, json={}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/meals",
            headers=H,
            json={"day": "2020-10-19", "description": "a", "calories": -1},
        ).status_code
        == 422
    )


def test_photos(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATE", tmp_path)
    assert (
        client.post(
            "/api/photos", headers=H, files={"file": ("x.jpg", b"bad", "image/jpeg")}
        ).status_code
        == 422
    )
    raw = io.BytesIO()
    Image.new("RGB", (10, 10)).save(raw, "JPEG", exif=b"Exif\x00\x00test")
    r = client.post(
        "/api/photos",
        headers=H,
        files={"file": ("x.jpg", raw.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 200
    path = tmp_path / "photos" / (r.json()["photo_id"] + ".jpg")
    assert (path.stat().st_mode & 0o777) == 0o600
    assert not Image.open(path).getexif()
    assert (
        client.get("/api/photos/" + r.json()["photo_id"], headers=H).status_code == 200
    )


def test_safe_energy():
    class Fake:
        def read(self, start, end, kinds, origin):
            source = "garmin" if "garmin" in origin else "zepp"
            return [
                {
                    "kind": "total_calories",
                    "start": "2020-10-18T05:00:00+00:00",
                    "end": "2020-10-19T05:00:00+00:00",
                    "record_id": source,
                    "data": {"kcal": 100 if source == "garmin" else 200},
                }
            ]

    order = {"total_calories": ["garmin", "zepp"]}
    r = app.energy(
        Fake(), "2020-10-18", "America/Chicago", "preferred", order, "total_calories"
    )
    assert r["kcal"] == 100 and r["source"] == "garmin"

    class Overlap(Fake):
        def read(self, *a, **kw):
            return super().read(*a, **kw) * 2

    assert (
        app.energy(
            Overlap(),
            "2020-10-18",
            "America/Chicago",
            "preferred",
            order,
            "total_calories",
        )["kcal"]
        is None
    )


def test_only_configured_hosts_are_trusted():
    for host in ["127.0.0.1:8787", "localhost:8787", "evil.example"]:
        assert client.get("/", headers={**H, "host": host}).status_code == 400
    origin_host = app.ORIGIN.removeprefix("https://")
    assert client.get("/", headers={**H, "host": origin_host}).status_code == 200


def test_test_host_is_not_trusted_without_opt_in(monkeypatch):
    import importlib

    monkeypatch.delenv("HQ_EXTRA_HOSTS", raising=False)
    fresh = importlib.reload(app)
    try:
        assert "testserver" not in fresh.TRUSTED_HOSTS
        assert fresh.TRUSTED_HOSTS == {fresh.ORIGIN.removeprefix("https://")}
    finally:
        monkeypatch.setenv("HQ_EXTRA_HOSTS", "testserver")
        importlib.reload(app)
