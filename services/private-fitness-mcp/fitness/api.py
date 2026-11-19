"""Authenticated ingestion only. Never starts a listener on import."""

import hmac
import json
import sqlite3
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from starlette.concurrency import run_in_threadpool
from .database import open_store, DatabaseUnavailable

MAX_BODY = 2_000_000


def production_app():
    return create_app(
        None, Path(__file__).resolve().parent.parent / "secrets/phone-token"
    )


def create_app(db_path, token_path):
    token = Path(token_path).read_text().strip()
    if len(token) < 32:
        raise ValueError("ingestion token must contain at least 32 characters")
    store = open_store(db_path)
    store.initialize()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/ingest")
    async def ingest(request: Request):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "unauthorized")
        size = 0
        parts = []
        async for part in request.stream():
            size += len(part)
            if size > MAX_BODY:
                raise HTTPException(413, "batch too large")
            parts.append(part)
        try:
            batch = json.loads(b"".join(parts))
            result = await run_in_threadpool(store.ingest, batch)
            return {**result, "batch_id": batch["batch_id"]}
        except (ValueError, TypeError, KeyError, OverflowError):
            # Never echo measurement payloads or validation inputs to logs/clients.
            raise HTTPException(422, "invalid batch") from None
        except (sqlite3.OperationalError, DatabaseUnavailable):
            raise HTTPException(
                503, "temporarily unavailable", headers={"Retry-After": "30"}
            ) from None

    return app
