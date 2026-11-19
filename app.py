"""Private Fitness HQ. Sensor access is SELECT-only; user logs use a separate schema."""

import io
import logging
import os
import warnings
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image, ImageOps
from fitness.queries import Queries, bounds, iso
from fitness.sources import priorities, read_selected
from fitness.store import Store, instant
from fitness.mysql_store import Connection
from fitness.operations import sync_health

ROOT = Path(__file__).parent
STATE = Path(os.environ.get("HQ_STATE", "/state"))
HOST = os.environ.get("HQ_DB_HOST", "host.docker.internal")
PORT = int(os.environ.get("HQ_DB_PORT", "3307"))
ORIGIN = os.environ.get("HQ_ORIGIN", "https://fitness.example.invalid:9443")
LOGIN = os.environ.get("HQ_OWNER", "owner@example.invalid")
TZ = os.environ.get("FITNESS_TIMEZONE", "UTC")
# Only the Serve origin is trusted by default. Tailscale Serve strips and resets
# identity headers on tailnet requests; direct loopback requests carry no such
# guarantee, so loopback/test host names are opt-in (HQ_EXTRA_HOSTS, comma list).
# Local processes on the host remain inside the trust boundary: see docs/setup.md.
TRUSTED_HOSTS = frozenset(
    {ORIGIN.removeprefix("https://")}
    | {h.strip() for h in os.environ.get("HQ_EXTRA_HOSTS", "").split(",") if h.strip()}
)
Image.MAX_IMAGE_PIXELS = 25_000_000


def db(role):
    import pymysql

    return pymysql.connect(
        host=HOST,
        port=PORT,
        user="fitness_reader" if role == "reader" else "fitness_hq",
        password=Path(os.environ.get("HQ_SECRETS_DIR", "/run/secrets"), role)
        .read_text()
        .strip(),
        database="fitness" if role == "reader" else "fitness_hq",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=10,
        autocommit=False,
        local_infile=False,
    )


class SensorStore(Store):
    def __init__(self):
        pass

    @contextmanager
    def connect(self, readonly=True):
        c = db("reader")
        try:
            with c.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
            c.begin()
            yield Connection(c)
        finally:
            c.close()

    def read(self, *a, **kw):
        rows = super().read(*a, **kw)
        for r in rows:
            for k in ("origin", "record_id"):
                if isinstance(r[k], bytes):
                    r[k] = r[k].decode()
        return rows


@contextmanager
def logs():
    c = db("logs")
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def sql(query, args=(), fetch=False):
    with logs() as c, c.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchall() if fetch else cur.rowcount


app = FastAPI(title="Fitness HQ", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def private_boundary(request, call_next):
    if request.url.path == "/healthz":
        return JSONResponse({"status": "running"})
    host = request.headers.get("host", "")
    if host not in TRUSTED_HOSTS:
        return JSONResponse({"detail": "Unknown host"}, 400)
    # Docker publishes only on loopback. Serve overwrites these identity headers.
    if request.headers.get("tailscale-user-login") != LOGIN:
        return JSONResponse(
            {"detail": "Connect to your Tailscale account to open Fitness HQ."}, 401
        )
    if request.method not in ("GET", "HEAD"):
        if (
            request.headers.get("origin") != ORIGIN
            or request.headers.get("x-hq-request") != "1"
        ):
            return JSONResponse({"detail": "Same-origin request required"}, 403)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid request size"}, 400)
        if size > 10_500_000:
            return JSONResponse({"detail": "Maximum upload is 10 MB"}, 413)
        if "content-length" not in request.headers:
            return JSONResponse({"detail": "Content length required"}, 411)
    response = await call_next(request)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        }
    )
    return response


@app.exception_handler(Exception)
async def safe_error(request, exc):
    # Exception type only: messages can contain query values or health data.
    # Numeric driver codes (for example MySQL 1045/2003) are safe to log.
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    logging.getLogger("fitness_hq").error(
        "request failed: %s %s -> %s %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        code,
    )
    return JSONResponse(
        {
            "detail": "Fitness data is temporarily unavailable. Your saved data has not been replaced."
        },
        503,
    )


def energy(store, day, tz, source, order, kind):
    a, b = bounds(day, tz)
    a, b = iso(a), iso(b)
    rows, chosen = read_selected(store, a, b, [kind], source=source, order=order)
    rows = sorted(rows, key=lambda r: r["start"])
    safe = (
        bool(rows)
        and all(a <= r["start"] and r["end"] <= b for r in rows)
        and not any(
            instant(x["end"]) > instant(y["start"]) for x, y in zip(rows, rows[1:])
        )
    )
    return {
        "kcal": round(sum(r["data"]["kcal"] for r in rows), 1) if safe else None,
        "source": chosen.get(kind),
        "records": len(rows),
        "coverage": "observed intervals only; daily completeness unverified"
        if safe
        else "missing, overlapping, or crossing day boundary",
    }


@app.get("/api/dashboard")
def dashboard(
    end_date: date | None = None,
    days: int = Query(default=14, ge=1, le=90),
    source: Literal["preferred", "garmin", "zepp"] = "preferred",
):
    end = end_date or datetime.now(ZoneInfo(TZ)).date()
    store = SensorStore()
    order = priorities()
    q = Queries(store, source, order)
    history = q.days(end.isoformat(), days, TZ)
    for d in history:
        d["energy"] = {
            k: energy(store, d["date"], TZ, source, order, k)
            for k in ("active_calories", "total_calories")
        }
        d["day_status"] = (
            "in_progress"
            if d["date"] >= datetime.now(ZoneInfo(TZ)).date().isoformat()
            else "completeness_unverified"
        )
    start = (end - timedelta(days=days - 1)).isoformat()
    entries = {
        table: sql(
            f"SELECT * FROM {table} WHERE day BETWEEN %s AND %s ORDER BY day DESC,created_utc DESC",
            (start, end.isoformat()),
            True,
        )
        for table in ("meals", "workouts", "measurements")
    }
    return {
        "days": history,
        "recovery": q.recovery((end - timedelta(days=1)).isoformat(), TZ),
        "activity": q.call(
            "get_activity_summary",
            {"end_date": end.isoformat(), "days": days, "timezone": TZ},
        ),
        "coverage": q.call(
            "get_source_coverage",
            {"end_date": end.isoformat(), "days": days, "timezone": TZ},
        ),
        "sync": sync_health(store),
        "logs": entries,
        "timezone": TZ,
        "source_policy": order,
        "notes": [
            "One source per metric/day; activity source selection is per workout. Garmin/Zepp are never added.",
            "Total calories already include active calories. Do not add them together.",
            "Historical days are not proven complete. Recent sync does not prove full wear or export.",
            "Recovery ends yesterday to exclude today. It remains an experimental rule; source changes or sparse history can prevent a result.",
            "Photo estimates are user-entered and unverified. Photos stay on this Mac. No cloud model is enabled.",
        ],
    }


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    day: date


class Meal(Entry):
    description: str = Field(min_length=1, max_length=500)
    calories: float | None = Field(default=None, ge=0, le=20000)
    protein: float | None = Field(default=None, ge=0, le=1000)
    photo_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class Workout(Entry):
    category: Literal["strength", "ski", "walk", "other"]
    exercise: str = Field(min_length=1, max_length=200)
    sets: int | None = Field(default=None, ge=1, le=100)
    reps: int | None = Field(default=None, ge=1, le=1000)
    load_kg: float | None = Field(default=None, ge=0, le=1000)
    minutes: float | None = Field(default=None, ge=0, le=1440)
    effort: int | None = Field(default=None, ge=1, le=10)
    notes: str = Field(default="", max_length=1000)


class Measurement(Entry):
    weight_kg: float | None = Field(default=None, gt=0, le=500)
    waist_cm: float | None = Field(default=None, gt=0, le=300)
    notes: str = Field(default="", max_length=500)


MODELS = {"meals": Meal, "workouts": Workout, "measurements": Measurement}


def save(table, entry, ident=None):
    values = entry.model_dump(mode="json")
    if (
        table == "measurements"
        and values["weight_kg"] is None
        and values["waist_cm"] is None
    ):
        raise HTTPException(422, "Enter weight or waist")
    photo = values.get("photo_id")
    if photo and not (STATE / "photos" / f"{photo}.jpg").is_file():
        raise HTTPException(422, "Photo not found")
    if ident:
        found = sql(f"SELECT id FROM {table} WHERE id=%s", (ident,), True)
        if not found:
            raise HTTPException(404, "Entry not found")
        sql(
            f"UPDATE {table} SET "
            + ",".join(f"{k}=%s" for k in values)
            + " WHERE id=%s",
            tuple(values.values()) + (ident,),
        )
    else:
        ident = uuid4().hex
        values = {
            "id": ident,
            **values,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        sql(
            f"INSERT INTO {table} ("
            + ",".join(values)
            + ") VALUES ("
            + ",".join(["%s"] * len(values))
            + ")",
            tuple(values.values()),
        )
    return {"id": ident}


@app.post("/api/meals")
def meal(entry: Meal):
    return save("meals", entry)


@app.put("/api/meals/{ident}")
def edit_meal(ident: str, entry: Meal):
    return save("meals", entry, ident)


@app.post("/api/workouts")
def workout(entry: Workout):
    return save("workouts", entry)


@app.put("/api/workouts/{ident}")
def edit_workout(ident: str, entry: Workout):
    return save("workouts", entry, ident)


@app.post("/api/measurements")
def measure(entry: Measurement):
    return save("measurements", entry)


@app.put("/api/measurements/{ident}")
def edit_measure(ident: str, entry: Measurement):
    return save("measurements", entry, ident)


@app.delete("/api/{table}/{ident}")
def delete(table: str, ident: str):
    if table not in MODELS:
        raise HTTPException(404)
    if not sql(f"DELETE FROM {table} WHERE id=%s", (ident,)):
        raise HTTPException(404)
    return {"deleted": True}


@app.post("/api/photos")
async def upload(file: UploadFile = File()):
    raw = await file.read(10_000_001)
    await file.close()
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Maximum photo size is 10 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(
                io.BytesIO(raw), formats=("JPEG", "PNG", "WEBP")
            ) as original:
                if original.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError()
                original.load()
                im = ImageOps.exif_transpose(original).convert("RGB")
                im.thumbnail((2048, 2048))
                # New pixels remove EXIF/GPS and embedded metadata.
                clean = Image.new("RGB", im.size)
                clean.paste(im)
                photo = uuid4().hex
                folder = STATE / "photos"
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = folder / f"{photo}.jpg"
                with path.open("xb") as out:
                    clean.save(out, format="JPEG", quality=88)
                path.chmod(0o600)
    except (
        ValueError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(422, "Use a valid JPEG, PNG, or WebP photo under 10 MB")
    return {
        "photo_id": photo,
        "estimation": "manual",
        "note": "Review portions and enter calorie/protein estimates. No automatic photo analysis is enabled.",
    }


@app.get("/api/photos/{ident}")
def photo(ident: str):
    import re

    if not re.fullmatch("[0-9a-f]{32}", ident):
        raise HTTPException(404)
    p = STATE / "photos" / f"{ident}.jpg"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static/index.html")
