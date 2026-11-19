"""Observed coverage and explicitly unpaired source comparisons; never infer export support."""

from datetime import date, timedelta
from .sources import SOURCES, UNITS


def window(day, count, tz):
    from .queries import bounds, iso

    a, _ = bounds((date.fromisoformat(day) - timedelta(days=count - 1)).isoformat(), tz)
    _, b = bounds(day, tz)
    return iso(a), iso(b)


def source_coverage(query, day, count, tz, metric=None):
    start, end = window(day, count, tz)
    sources = {}
    for name, origin in SOURCES.items():
        rows = query.store.read(start, end, [metric] if metric else None, origin=origin)
        metrics = {}
        for kind in [metric] if metric else UNITS:
            found = [r for r in rows if r["kind"] == kind]
            metrics[kind] = {
                "status": "observed" if found else "no_records_observed",
                "record_count": len(found),
                "unit": UNITS[kind],
                "earliest_start": min((r["start"] for r in found), default=None),
                "latest_end": max((r["end"] for r in found), default=None),
                "records_with_device_metadata": sum(
                    bool(r["data"].get("_provenance", {}).get("device")) for r in found
                ),
                "records_with_device_identifier": sum(
                    bool(
                        (r["data"].get("_provenance", {}).get("device") or {}).get(
                            "identifier"
                        )
                    )
                    for r in found
                ),
            }
        sources[name] = {"source_app": origin, "metrics": metrics}
    return {
        "start": start,
        "end": end,
        "timezone": tz,
        "sources": sources,
        "source_priorities": query.source_priorities,
        "limitations": [
            "Observed rows establish availability only for this installation and time window.",
            "No rows can mean no permission, export disabled, no wear, sync delay, or unsupported export.",
            "Historical records without provenance have unknown device metadata; no serial is invented.",
        ],
    }


def scalar(day, kind):
    from .queries import mean

    keys = {
        "resting_heart_rate": "resting_heart_rate_bpm",
        "hrv_rmssd": "hrv_rmssd_ms",
        "sleep": "sleep_hours",
        "steps": "steps",
    }
    if kind == "heart_rate":
        return day["heart_rate"]["sample_mean_bpm"]
    if kind in keys:
        return day[keys[kind]]
    if kind == "weight":
        return mean(day["weight_kg"])
    if kind == "body_fat":
        return mean(day["body_fat_percent"])
    field = {
        "oxygen_saturation": "percent",
        "respiratory_rate": "breaths_per_minute",
        "height": "cm",
        "lean_body_mass": "kg",
        "bone_mass": "kg",
        "body_water_mass": "kg",
        "distance": "meters",
        "active_calories": "kcal",
        "total_calories": "kcal",
    }.get(kind)
    values = [
        r[field]
        for r in day["additional_metrics"].get(kind, {}).get("values", [])
        if field in r
    ]
    # Interval totals must never be summed without overlap handling. Expose records/coverage instead.
    return (
        None
        if kind in {"distance", "active_calories", "total_calories", "activity"}
        else mean(values)
    )


def compare_sources(query, day, count, tz, metric=None):
    from .queries import Queries

    metrics = [metric] if metric else list(UNITS)
    values = {
        name: Queries(query.store, name, query.source_priorities).days(day, count, tz)
        for name in SOURCES
    }
    compared = []
    for i in range(count):
        measurements = {}
        for kind in metrics:
            a = scalar(values["garmin"][i], kind)
            b = scalar(values["zepp"][i], kind)
            measurements[kind] = {
                "garmin": a,
                "zepp": b,
                "zepp_minus_garmin": round(b - a, 3)
                if a is not None and b is not None
                else None,
                "unit": "hours" if kind == "sleep" else UNITS[kind],
            }
        compared.append({"date": values["garmin"][i]["date"], "metrics": measurements})
    return {
        "days": compared,
        "comparison_basis": "Unpaired daily summaries; same local calendar/wake date, not matched sensor samples.",
        "limitations": [
            "Differences may reflect wear time, sample cadence, sleep segmentation or devices, not accuracy.",
            "No combined total is formed from both sources. Interval metrics without a safe total remain unknown.",
            "View get_source_coverage and per-source activity/sleep tools before interpreting differences.",
        ],
    }
