# All fixtures below are artificial unit-test inputs, not exported measurements.
import json
from datetime import datetime, timezone
import pytest
from fitness.store import Store
from fitness.garmin_workouts import normalize, call, WORKOUT_TOOLS
from fitness.mcp_server import handle
from fitness.queries import Queries


def payload():
    return {
        "activity": {
            "activityName": "Strength",
            "summaryDTO": {
                "startTimeGMT": "2000-01-19 12:00:00",
                "duration": 600,
                "averageHR": 100,
                "calories": 100,
                "bmrCalories": 20,
            },
        },
        "exercise_sets": {
            "exerciseSets": [
                {
                    "setType": "ACTIVE",
                    "repetitionCount": 8,
                    "weight": 20,
                    "weightUnit": {"unitKey": "kg"},
                    "duration": 35,
                    "exercises": [{"exerciseName": "BENCH_PRESS"}],
                },
                {"setType": "REST", "duration": 90},
                {
                    "setType": "ACTIVE",
                    "repetitionCount": 8,
                    "weight": 20000,
                    "weightUnit": "unsupported",
                    "exercises": [],
                },
            ]
        },
        "details": {
            "metricDescriptors": [
                {"key": "directTimestamp", "metricsIndex": 0, "unit": {"key": "ms"}},
                {"key": "directHeartRate", "metricsIndex": 1},
            ],
            "activityDetailMetrics": [
                {"metrics": [946728000000, 100]},
                {"metrics": [946728001000, None]},
            ],
        },
    }


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite")
    s.initialize()
    with s.connect() as c:
        c.execute(
            "CREATE TABLE garmin_workouts (activity_id TEXT PRIMARY KEY,start_utc TEXT,synced_at TEXT,data TEXT,raw_payloads TEXT)"
        )
        c.execute("CREATE TABLE garmin_sync_state (id INTEGER PRIMARY KEY,data TEXT)")
        w = normalize("101", payload(), {}, "2000-01-19T21:00:00+00:00")
        c.execute(
            "INSERT INTO garmin_workouts VALUES (?,?,?,?,?)",
            (
                w["activity_id"],
                w["start_utc"],
                w["fetched_at"],
                json.dumps(w),
                json.dumps(payload()),
            ),
        )
    return s


def test_normalization_provenance_and_unknowns():
    w = normalize("101", payload(), {}, "now")
    assert w["calories"] == {
        "total_kcal": 100,
        "active_kcal": 80,
        "resting_kcal": 20,
        "active_method": "derived_total_minus_reported_bmr",
    }
    assert w["sets"][0]["volume_kg_repetitions"] == 160
    assert w["sets"][2]["weight_kg"] is None and w["sets"][2]["exercise_name"] is None
    assert w["sets"][1]["duration_seconds"] == 90
    assert w["heart_rate"]["sample_count"] == 1
    assert w["start_utc"] == "2000-01-19T12:00:00+00:00"
    empty = normalize("1", {}, {}, "now")
    assert empty["calories"]["total_kcal"] is None and empty["sets"] == []


def test_mcp_details_strict_arguments_readonly(store):
    q = Queries(store)
    reply = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_workout_details",
                "arguments": {"activity_id": "101"},
            },
        },
        q,
    )
    assert (
        json.loads(reply["result"]["content"][0]["text"])["workout"]["sets"][0][
            "repetitions"
        ]
        == 8
    )
    for args in [
        {"activity_id": "1 OR 1=1"},
        {"activity_id": "-1"},
        {"activity_id": "1", "source": "garmin"},
        {},
    ]:
        with pytest.raises(ValueError):
            call(store, "get_workout_details", args)
    with store.connect(True) as c:
        with pytest.raises(Exception):
            c.execute("DELETE FROM garmin_workouts")
    names = {
        t["name"]
        for t in handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, q)[
            "result"
        ]["tools"]
    }
    assert set(WORKOUT_TOOLS) <= names and "get_daily_metrics" in names


def test_history_unknown_volume_and_parameterization(store):
    # Move the test fixture into the current time window independently of test date.
    current = datetime.now(timezone.utc).isoformat()
    with store.connect() as c:
        c.execute("UPDATE garmin_workouts SET start_utc=?", (current,))
    history = call(store, "get_exercise_history", {"exercise_name": "bench_press"})
    assert history["workouts"][0]["known_volume_kg_repetitions"] == 160
    assert (
        call(store, "get_exercise_history", {"exercise_name": "' OR 1=1 --"})[
            "workouts"
        ]
        == []
    )
    for bad in [True, 0, 91, "7"]:
        with pytest.raises(ValueError):
            call(store, "get_recent_workouts", {"days": bad})


class Client:
    def get_activity(self, ident):
        return payload()["activity"]

    def get_activity_exercise_sets(self, ident):
        return payload()["exercise_sets"]

    def get_activity_details(self, ident, **kwargs):
        return payload()["details"]

    def get_activity_splits(self, ident):
        return {"lapDTOs": []}

    def get_activity_hr_in_timezones(self, ident):
        return []


def test_garmin_endpoint_weight_convention_and_null_sets():
    p = payload()
    p["exercise_sets"]["exerciseSets"][0]["weight"] = 10000
    del p["exercise_sets"]["exerciseSets"][0]["weightUnit"]
    w = normalize("1", p, {}, "now")
    assert w["sets"][0]["weight_kg"] == 10
    p["exercise_sets"] = {"exerciseSets": None}
    assert normalize("1", p, {}, "now")["sets"] == []
