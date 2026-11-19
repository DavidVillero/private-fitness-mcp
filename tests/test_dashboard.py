import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hq_dashboard", ROOT / "services/chatgpt-mcp/dashboard.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def msg(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


class Original:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def handle(self, message):
        self.calls.append(copy.deepcopy(message))
        method = message.get("method")
        p = message.get("params", {})
        name = p.get("name")
        if method == "initialize":
            value = {"capabilities": {"tools": {}}, "serverInfo": {"name": "original"}}
        elif method == "tools/list":
            value = {
                "tools": [{"name": "original_write", "inputSchema": {"type": "object"}}]
            }
        elif method == "tools/call":
            if name in self.fail:
                return {"error": {"message": "private exception"}}
            if name == "get_daily_context":
                data = {
                    "nutrition": {
                        "recorded_consumed_totals": {"calories_kcal": None},
                        "daily_log_may_be_incomplete": True,
                    },
                    "records": [],
                    "garmin_candidates": {"available": True, "data": []},
                }
            elif name == "search_personal_context":
                data = {"results": []}
            elif name in ["get_sleep_history", "get_heart_rate_trends"]:
                data = []
            else:
                data = {}
            value = {"content": [{"type": "text", "text": json.dumps(data)}]}
        else:
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32601, "message": "original"},
            }
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": value}


def test_exact_legacy_passthrough_and_catalog():
    original = Original()
    overlay = m.Dashboard(original)
    call = msg(
        "tools/call",
        {"name": "original_write", "arguments": {"authorization": "user_requested"}},
    )
    assert overlay.handle(call) == original.handle(call)
    assert original.calls[0] == call
    tools = overlay.handle(msg("tools/list"))["result"]["tools"]
    assert tools[0] == {"name": "original_write", "inputSchema": {"type": "object"}}
    assert len(tools) == 3
    assert all(t["annotations"]["readOnlyHint"] for t in tools[1:])
    assert "resources" in overlay.handle(msg("initialize"))["result"]["capabilities"]


def test_resource_static_and_bounded():
    overlay = m.Dashboard(Original())
    resource = overlay.handle(msg("resources/read", {"uri": m.URI}))["result"][
        "contents"
    ][0]
    assert resource["mimeType"] == m.MIME
    html = resource["text"]
    assert "/* SCRIPT */" not in html and "/* STYLE */" not in html
    for forbidden in [
        "/Users/",
        "/tmp/",
        "2400",
        "180 g",
        "private-activity-id",
        "fetch(",
        "localStorage",
        "innerHTML",
        "eval(",
    ]:
        assert forbidden not in html
    assert resource["_meta"]["ui"]["csp"] == {
        "connectDomains": [],
        "resourceDomains": [],
    }
    assert "error" in overlay.handle(
        msg("resources/read", {"uri": "file:///etc/passwd"})
    )


def test_missing_is_unknown_and_no_writes():
    original = Original()
    d = m.Dashboard(original).snapshot({"date": "2020-10-19", "days": 7})
    assert d["nutrition"]["recorded_consumed_totals"]["calories_kcal"] is None
    assert all(x is None for x in d["targets"]["values"].values())
    assert d["correction_missing"] is True
    assert d["errors"] == []
    assert all(
        c["params"]["name"].startswith(("get_", "search_")) for c in original.calls
    )


def test_partial_failure_and_secret_redaction():
    original = Original()
    original.fail = {"get_daily_metrics", "get_recovery_summary"}
    d = m.Dashboard(original).snapshot({"date": "2020-10-19"})
    assert d["today"] is None and set(d["errors"]) == {"today", "recovery"}
    assert m.public(
        {
            "local_storage_path": "/tmp/private",
            "token": "bad",
            "content": "Evidence /tmp/private/file.txt remains",
            "samples": [1],
        }
    ) == {"content": "Evidence [local reference] remains"}


@pytest.mark.parametrize(
    "args",
    [
        {"days": True},
        {"days": 91},
        {"source": "unknown"},
        {"date": "bad"},
        {"date": 1},
        {"days": 7, "write": True},
    ],
)
def test_invalid_arguments(args):
    original = Original()
    r = m.Dashboard(original).handle(
        msg("tools/call", {"name": "open_fitness_hq", "arguments": args})
    )
    assert r["result"]["isError"]
    assert original.calls == []


def test_effective_target_selection_no_numeric_defaults():
    record = {
        "title": "Daily calorie and macro targets",
        "effective_date": "2020-10-19",
        "content": "energy 2100 kcal; protein 150 g; total carbohydrates 210 g; total fat 70 g.",
    }
    future = {**record, "effective_date": "2020-10-20", "content": "energy 9999 kcal"}
    r = m.goal_record([future, record], "2020-10-19")
    assert r["values"] == {
        "calories_kcal": 2100.0,
        "protein_g": 150.0,
        "carbohydrates_g": 210.0,
        "fat_g": 70.0,
    }
    assert m.goal_record([record], "2020-10-18")["values"]["calories_kcal"] is None
    record["content"] = "energy 2100 kcal; energy 2200 kcal"
    assert m.goal_record([record], "2020-10-19")["values"]["calories_kcal"] is None
