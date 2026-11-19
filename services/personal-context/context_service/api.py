import hmac
import json
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError
from .storage import Conflict
from .tools import Service, definitions

logger = logging.getLogger("personal_context")


def create_app(service: Service, credentials):
    # Reject unsafe configuration before opening a listener. Token rotation requires
    # a service restart, so a truncated token file cannot weaken a running service.
    if (
        not isinstance(credentials, dict)
        or not credentials
        or set(credentials) - {"read", "write"}
    ):
        raise ValueError("Configure only read/write capability files")
    capabilities = {}
    for scope, path in credentials.items():
        token = Path(path).read_text().strip()
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError(
                "Capability tokens must be at least 32 non-whitespace ASCII characters"
            )
        value = ("Bearer " + token).encode("ascii")
        if value in capabilities.values():
            raise ValueError("Read and write capabilities must be distinct")
        capabilities[scope] = value
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request, call_next):
        if request.headers.get("origin") or request.headers.get("host", "").split(":")[
            0
        ] not in ["127.0.0.1", "localhost", "testserver"]:
            return JSONResponse({"error": "Untrusted origin or host"}, status_code=403)
        if request.url.path == "/health":
            return await call_next(request)
        bearer = request.headers.get("authorization", "").encode("utf-8")
        scope = None
        for candidate, expected in capabilities.items():
            if hmac.compare_digest(bearer, expected):
                scope = candidate
        if scope is None:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        request.state.scope = scope
        return await call_next(request)

    @app.get("/health")
    def health():
        try:
            status = service.store.status()
            return JSONResponse(
                {
                    "status": "ok" if status["integrity"] == "ok" else "unhealthy",
                    "schema_version": status["schema_version"],
                },
                status_code=200 if status["integrity"] == "ok" else 503,
            )
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/tools")
    def tools(request: Request):
        return {"tools": definitions(request.state.scope)}

    @app.post("/call")
    async def call(request: Request):
        length = 0
        chunks = []
        async for chunk in request.stream():
            length += len(chunk)
            if length > 29_000_000:
                return JSONResponse({"error": "Request too large"}, status_code=413)
            chunks.append(chunk)
        try:
            msg = json.loads(b"".join(chunks))
            if (
                not isinstance(msg, dict)
                or set(msg) != {"name", "arguments"}
                or not isinstance(msg["arguments"], dict)
            ):
                raise ValueError()
            result = await run_in_threadpool(
                service.call,
                msg["name"],
                msg["arguments"],
                request.state.scope,
                "capability:" + request.state.scope,
            )
            logger.info(
                json.dumps(
                    {
                        "event": "tool_call",
                        "tool": msg["name"],
                        "scope": request.state.scope,
                        "result": "ok",
                    }
                )
            )
            return JSONResponse({"result": result})
        except PermissionError:
            return JSONResponse({"error": "Write capability required"}, status_code=403)
        except Conflict as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except (ValueError, TypeError, KeyError, ValidationError):
            return JSONResponse(
                {
                    "error": "Invalid arguments, missing record, or inconsistent data; inspect tool schema and latest version"
                },
                status_code=422,
            )
        except Exception:
            logger.error(json.dumps({"event": "tool_call", "result": "unavailable"}))
            return JSONResponse(
                {"error": "Local service unavailable; no values inferred"},
                status_code=503,
            )

    return app
