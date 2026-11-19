"""Bounded MCP stdio JSON-RPC implementation; no network listener or writer."""

import os
import json
import sys
from .queries import Queries, TOOLS
from .database import open_store
from .sources import UNITS
from .garmin_workouts import WORKOUT_TOOLS, call as workout_call

VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SCHEMA = {
    "type": "object",
    "properties": {
        "end_date": {
            "type": "string",
            "description": "Inclusive ISO local date YYYY-MM-DD",
        },
        "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7},
        "timezone": {
            "type": "string",
            "default": os.environ.get("FITNESS_TIMEZONE", "UTC"),
        },
    },
    "additionalProperties": False,
}
SCHEMA["properties"]["source"] = {
    "type": "string",
    "enum": ["preferred", "garmin", "zepp"],
    "default": "preferred",
}
SOURCE_SCHEMA = {
    **SCHEMA,
    "properties": {
        **SCHEMA["properties"],
        "metric": {"type": "string", "enum": sorted(UNITS)},
    },
}


def handle(message, queries):
    ident = message.get("id")
    method = message.get("method")
    params = message.get("params", {})
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    if "id" not in message:
        return None
    try:
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {
                "protocolVersion": requested if requested in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "private-fitness", "version": "0.2.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            annotations = {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            }
            result = {
                "tools": [
                    {
                        "name": n,
                        "description": n.replace("_", " ")
                        + ". Garmin and Zepp Health Connect data; configurable source priorities, no cross-source addition. Missing data remains unknown.",
                        "inputSchema": SOURCE_SCHEMA
                        if n in ["compare_sources", "get_source_coverage"]
                        else SCHEMA,
                        "annotations": annotations,
                    }
                    for n in TOOLS
                ]
                + [
                    {"name": n, **definition, "annotations": annotations}
                    for n, definition in WORKOUT_TOOLS.items()
                ]
            }
        elif method == "tools/call":
            try:
                name = params["name"]
                arguments = params.get("arguments", {})
                value = (
                    workout_call(queries.store, name, arguments)
                    if name in WORKOUT_TOOLS
                    else queries.call(name, arguments)
                )
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(value, allow_nan=False)}
                    ],
                    "isError": False,
                }
            except (ValueError, TypeError, KeyError):
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": "Invalid tool name, arguments, timezone, or date.",
                        }
                    ],
                    "isError": True,
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    except Exception:
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {
                "code": -32603,
                "message": "Local query unavailable; check database initialization.",
            },
        }


def serve(db):
    queries = Queries(open_store(db, readonly=True))
    while True:
        line = sys.stdin.buffer.readline(1_000_001)
        if not line:
            break
        if len(line) > 1_000_000:
            raise SystemExit("MCP request exceeds limit")
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict):
                raise ValueError()
            response = handle(msg, queries)
        except (ValueError, UnicodeError):
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if response is not None:
            print(json.dumps(response, allow_nan=False), flush=True)
