import json
import pytest
from fitness.store import Store, validate
from fitness.queries import Queries
from fitness.sources import GARMIN, ZEPP, priorities


def record(
    origin=GARMIN,
    kind="heart_rate",
    ident="same",
    data=None,
    start="2020-10-18T12:00:00Z",
    end="2020-10-18T12:01:00Z",
):
    return {
        "origin": origin,
        "record_id": ident,
        "kind": kind,
        "start": start,
        "end": end,
        "modified": "2020-10-19T00:00:00Z",
        "data": data
        or {"samples": [{"time": start, "bpm": 60 if origin == GARMIN else 66}]},
    }


def batch(*rows, ident="batch", deletions=()):
    return {
        "schema_version": 1,
        "batch_id": ident,
        "records": list(rows),
        "deletions": list(deletions),
    }


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "sources.sqlite")
    s.initialize()
    return s


def test_same_ids_separate_sources_and_tombstones(store):
    b = batch(record(), record(ZEPP))
    store.ingest(b)
    assert store.ingest(b)["duplicate_batch"]
    store.ingest(
        batch(
            ident="deleted",
            deletions=[
                {
                    "origin": GARMIN,
                    "record_id": "same",
                    "modified": "2020-10-20T00:00:00Z",
                }
            ],
        )
    )
    store.ingest(batch(record(), ident="stale"))
    assert not store.read("2020-10-18T00:00:00Z", "2020-10-19T00:00:00Z", origin=GARMIN)
    assert (
        len(store.read("2020-10-18T00:00:00Z", "2020-10-19T00:00:00Z", origin=ZEPP))
        == 1
    )


def test_priorities_do_not_add_sources_and_comparison_is_unpaired(store):
    store.ingest(
        batch(
            record(),
            record(ZEPP),
            record(GARMIN, "steps", "steps", {"count": 100}),
            record(ZEPP, "steps", "steps", {"count": 200}),
        )
    )
    q = Queries(store)
    d = q.call("get_daily_metrics", {"end_date": "2020-10-18"})
    assert d["steps"] == 100 and d["heart_rate"]["sample_count"] == 1
    assert d["selected_sources"]["steps"] == "garmin"
    z = q.call("get_daily_metrics", {"end_date": "2020-10-18", "source": "zepp"})
    assert z["steps"] == 200
    comparison = q.call(
        "compare_sources", {"end_date": "2020-10-18", "days": 1, "metric": "heart_rate"}
    )
    assert comparison["days"][0]["metrics"]["heart_rate"]["zepp_minus_garmin"] == 6
    assert "Unpaired" in comparison["comparison_basis"]


def test_new_metrics_units_metadata_and_source_coverage(store):
    r = record(ZEPP, "oxygen_saturation", data={"percent": 97})
    r["data"]["_provenance"] = {
        "source_app": ZEPP,
        "unit": "percent",
        "device": None,
        "original_start": "2020-10-18T07:00:00-05:00",
        "original_end": "2020-10-18T07:01:00-05:00",
        "client_record_id": "source-record",
        "zone_offset": "-05:00",
    }
    store.ingest(
        batch(
            r, record(ZEPP, "respiratory_rate", "breathing", {"breaths_per_minute": 14})
        )
    )
    rows = store.read("2020-10-18T00:00:00Z", "2020-10-19T00:00:00Z", origin=ZEPP)
    assert (
        next(x for x in rows if x["kind"] == "oxygen_saturation")["data"]["_provenance"]
        == r["data"]["_provenance"]
    )
    q = Queries(store)
    d = q.call("get_daily_metrics", {"end_date": "2020-10-18"})
    assert d["additional_metrics"]["oxygen_saturation"]["source"] == "zepp"
    c = q.call("get_source_coverage", {"end_date": "2020-10-18", "days": 1})
    assert c["sources"]["zepp"]["metrics"]["oxygen_saturation"]["status"] == "observed"
    assert (
        c["sources"]["zepp"]["metrics"]["hrv_rmssd"]["status"] == "no_records_observed"
    )
    assert (
        c["sources"]["zepp"]["metrics"]["oxygen_saturation"][
            "records_with_device_identifier"
        ]
        == 0
    )
    bad = json.loads(json.dumps(r))
    bad["data"]["_provenance"]["unit"] = "fraction"
    with pytest.raises(ValueError):
        validate(bad)
    bad = json.loads(json.dumps(r))
    bad["data"]["percent"] = 101
    with pytest.raises(ValueError):
        validate(bad)


def test_sleep_and_activity_are_never_added_across_sources(store):
    start = "2020-10-18T04:00:00Z"
    end = "2020-10-18T12:00:00Z"
    sleep = {"stages": [{"start": start, "end": end, "stage": "sleeping"}]}
    store.ingest(
        batch(
            *[
                record(origin, kind, kind, data, start, end)
                for origin in (GARMIN, ZEPP)
                for kind, data in [
                    ("sleep", sleep),
                    ("activity", {"exercise_type": 70}),
                ]
            ]
        )
    )
    q = Queries(store)
    assert q.call("get_daily_metrics", {"end_date": "2020-10-18"})["sleep_hours"] == 8
    a = q.call("get_activity_summary", {"end_date": "2020-10-18", "days": 1})
    assert len(a["activities"]) == 1 and a["activities"][0]["origin"] == GARMIN


def test_priority_config_and_nonpreferred_overlap(store, tmp_path):
    p = tmp_path / "priority.json"
    p.write_text(
        json.dumps({"default": ["garmin", "zepp"], "heart_rate": ["zepp", "garmin"]})
    )
    store.ingest(batch(record(), record(ZEPP)))
    q = Queries(store, source_priorities=priorities(p))
    assert (
        q.daily("2020-10-18", "America/Chicago")["heart_rate"]["sample_mean_bpm"] == 66
    )
    p.write_text(json.dumps({"default": ["unknown"]}))
    with pytest.raises(ValueError):
        priorities(p)


def test_recovery_does_not_mix_device_sources(store):
    from datetime import date, timedelta

    rows = []
    for i in range(24):
        day = date(2020, 9, 25) + timedelta(days=i)
        origin = GARMIN if i < 21 else ZEPP
        rows.append(
            record(
                origin,
                "resting_heart_rate",
                str(i),
                {"bpm": 55 if i < 21 else 70},
                f"{day}T12:00:00Z",
                f"{day}T12:00:00Z",
            )
        )
    store.ingest(batch(*rows))
    r = Queries(store).recovery("2020-10-18", "America/Chicago")
    assert r["coverage"]["resting_heart_rate_bpm"]["source_changed"]
    assert r["status"] == "insufficient_data" and not r["signals"]


def test_activity_priority_per_workout_retains_originals(store):
    morning = record(
        ZEPP,
        "activity",
        "morning",
        {"exercise_type": 0},
        "2020-10-19T14:00:00Z",
        "2020-10-19T14:05:00Z",
    )
    garmin = record(
        GARMIN,
        "activity",
        "strength",
        {"exercise_type": 70},
        "2020-10-19T18:00:00Z",
        "2020-10-19T19:00:00Z",
    )
    zepp = record(
        ZEPP,
        "activity",
        "workout",
        {"exercise_type": 0},
        "2020-10-19T18:00:00Z",
        "2020-10-19T19:02:00Z",
    )
    zepp["modified"] = "2020-10-19T20:00:00Z"
    store.ingest(batch(morning, garmin, zepp))
    q = Queries(store)
    args = {"end_date": "2020-10-19", "days": 1}
    result = q.call("get_activity_summary", args)
    assert [r["record_id"] for r in result["activities"]] == ["morning", "strength"]
    assert result["excluded_overlapping_record_ids"] == ["workout"]
    assert result["activities"][1]["overlapping_originals"][0]["record_id"] == "workout"
    assert (
        len(q.call("get_activity_summary", {**args, "source": "zepp"})["activities"])
        == 2
    )
    assert (
        sum(
            len(
                store.read(
                    "2020-10-19T05:00:00Z",
                    "2020-10-20T05:00:00Z",
                    ["activity"],
                    origin=o,
                )
            )
            for o in (GARMIN, ZEPP)
        )
        == 3
    )


def test_activity_small_cross_source_overlap_is_distinct(store):
    store.ingest(
        batch(
            record(
                GARMIN,
                "activity",
                "a",
                {"exercise_type": 70},
                "2020-10-19T18:00:00Z",
                "2020-10-19T19:00:00Z",
            ),
            record(
                ZEPP,
                "activity",
                "b",
                {"exercise_type": 0},
                "2020-10-19T18:55:00Z",
                "2020-10-19T19:30:00Z",
            ),
        )
    )
    result = Queries(store).call(
        "get_activity_summary", {"end_date": "2020-10-19", "days": 1}
    )
    assert len(result["activities"]) == 2
    assert not result["excluded_overlapping_record_ids"]


def hourly_steps(origin, day="2020-10-18", count=500, hours=range(24), prefix="h"):
    return [
        record(
            origin,
            "steps",
            f"{prefix}{h}",
            {"count": count},
            f"{day}T{h:02d}:00:00Z",
            f"{day}T{h:02d}:59:00Z",
        )
        for h in hours
    ]


def test_sparse_preferred_source_does_not_suppress_complete_source(store):
    # Regression: one stray Garmin minute used to win over a full Zepp day.
    store.ingest(
        batch(
            *hourly_steps(ZEPP),
            record(
                GARMIN,
                "steps",
                "stray",
                {"count": 40},
                "2020-10-18T12:00:00Z",
                "2020-10-18T12:01:00Z",
            ),
        )
    )
    d = Queries(store).call(
        "get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"}
    )
    assert d["steps"] == 12000
    assert d["selected_sources"]["steps"] == "zepp"
    detail = d["source_selection"]["steps"]
    assert detail["basis"] == "greatest_observed_interval_coverage_overrode_priority"
    assert detail["candidates"]["garmin"]["records"] == 1


def test_interval_total_selects_best_observed_coverage(store):
    store.ingest(
        batch(
            *hourly_steps(GARMIN, count=400, hours=range(14), prefix="g"),
            *hourly_steps(ZEPP, hours=range(24), prefix="z"),
        )
    )
    d = Queries(store).call(
        "get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"}
    )
    # Even though Garmin passes the old 50% threshold, this additive total
    # comes from the source with the most observed intervals.
    assert d["selected_sources"]["steps"] == "zepp"
    assert d["steps"] == 12000
    assert d["source_selection"]["steps"]["basis"] == (
        "greatest_observed_interval_coverage_overrode_priority"
    )
    assert d["steps_completeness"] == "unverified"
    assert d["steps_observed_covered_fraction"] > 0.9


def test_point_metrics_keep_presence_priority(store):
    store.ingest(
        batch(
            record(
                GARMIN,
                "resting_heart_rate",
                "g",
                {"bpm": 50},
                "2020-10-18T07:00:00Z",
                "2020-10-18T07:00:00Z",
            ),
            record(
                ZEPP,
                "resting_heart_rate",
                "z",
                {"bpm": 55},
                "2020-10-18T07:00:00Z",
                "2020-10-18T07:00:00Z",
            ),
        )
    )
    d = Queries(store).call(
        "get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"}
    )
    assert d["resting_heart_rate_bpm"] == 50
    assert d["source_selection"]["resting_heart_rate"]["basis"] == (
        "priority_by_presence_point_metric"
    )


def test_boundary_crossing_steps_are_flagged_partial(store):
    store.ingest(
        batch(
            record(
                GARMIN,
                "steps",
                "inside",
                {"count": 1000},
                "2020-10-18T10:00:00Z",
                "2020-10-18T11:00:00Z",
            ),
            record(
                GARMIN,
                "steps",
                "crossing",
                {"count": 3000},
                "2020-10-18T23:30:00Z",
                "2020-10-19T00:30:00Z",
            ),
        )
    )
    q = Queries(store)
    d = q.call("get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"})
    assert d["steps"] == 1000
    assert d["steps_partial"] is True
    assert d["steps_excluded_boundary_intervals"] == 1
    nxt = q.call("get_daily_metrics", {"end_date": "2020-10-19", "timezone": "UTC"})
    assert nxt["steps"] is None and "steps" in nxt["missing_metrics"]
    assert nxt["steps_partial"] is False
    assert nxt["steps_excluded_boundary_intervals"] == 1


def test_contained_steps_are_not_partial(store):
    store.ingest(batch(*hourly_steps(GARMIN)))
    d = Queries(store).call(
        "get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"}
    )
    assert d["steps"] == 12000 and d["steps_partial"] is False


def test_equal_interval_coverage_preserves_preference(store):
    store.ingest(
        batch(
            *hourly_steps(GARMIN, count=400, hours=range(14), prefix="g"),
            *hourly_steps(ZEPP, count=500, hours=range(14), prefix="z"),
        )
    )
    d = Queries(store).call(
        "get_daily_metrics", {"end_date": "2020-10-18", "timezone": "UTC"}
    )
    assert d["selected_sources"]["steps"] == "garmin"
    assert d["steps"] == 5600
    assert d["steps_completeness"] == "unverified"
    assert (
        d["source_selection"]["steps"]["candidates"]["zepp"][
            "observed_covered_fraction"
        ]
        < 1
    )
