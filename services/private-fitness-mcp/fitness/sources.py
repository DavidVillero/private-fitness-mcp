"""Source identities and conservative per-metric source selection."""

import json
import os
from pathlib import Path

GARMIN = "com.garmin.android.apps.connectmobile"
ZEPP = "com.huami.watch.hmwatchmanager"
SOURCES = {"garmin": GARMIN, "zepp": ZEPP}
UNITS = {
    "heart_rate": "bpm",
    "resting_heart_rate": "bpm",
    "hrv_rmssd": "ms",
    "sleep": "seconds",
    "steps": "count",
    "activity": "seconds",
    "weight": "kg",
    "body_fat": "percent",
    "oxygen_saturation": "percent",
    "respiratory_rate": "breaths/min",
    "height": "cm",
    "lean_body_mass": "kg",
    "bone_mass": "kg",
    "body_water_mass": "kg",
    "distance": "m",
    "active_calories": "kcal",
    "total_calories": "kcal",
}


def priorities(path=None):
    path = Path(
        path
        or os.environ.get(
            "FITNESS_SOURCE_PRIORITIES",
            Path(__file__).resolve().parent.parent / "config/source-priorities.json",
        )
    )
    config = json.loads(path.read_text()) if path.exists() else {}
    if set(config) - set(UNITS) - {"default"}:
        raise ValueError("Unknown metric in source priorities")
    for order in config.values():
        if (
            not isinstance(order, list)
            or not order
            or len(order) != len(set(order))
            or any(x not in SOURCES for x in order)
        ):
            raise ValueError("Invalid source priority")
    return {
        kind: config.get(kind, config.get("default", ["garmin", "zepp"]))
        for kind in UNITS
    }


# A lower-priority source wins only when the preferred source covers less than
# this share of the best-covered source's observed time in the window. Presence
# alone (one stray record) must never suppress a substantially complete source.
COVERAGE_RATIO = 0.5
# Interval totals must not prefer a sparse source merely because it is first.
# Observed record duration is not equivalent to device wear or export completeness.
INTERVAL_TOTAL_KINDS = frozenset(
    {"steps", "distance", "active_calories", "total_calories"}
)


def covered_seconds(rows, start, end):
    """Union of record intervals clipped to [start, end); point records add 0."""
    from .store import instant

    lo, hi = instant(start), instant(end)
    spans = sorted(
        (max(instant(r["start"]), lo), min(instant(r["end"]), hi)) for r in rows
    )
    total = 0.0
    cursor = None
    for a, b in spans:
        if b <= a:
            continue
        if cursor is not None and a < cursor:
            a = cursor
        if b > a:
            total += (b - a).total_seconds()
            cursor = b if cursor is None else max(cursor, b)
    return total


def read_selected(
    store,
    start,
    end,
    kinds=None,
    source="preferred",
    order=None,
    eligible=None,
    details=None,
):
    """Select one source per metric for the window.

    With source="preferred", priority applies among sources whose observed
    coverage is at least COVERAGE_RATIO of the best-covered source, while
    additive interval totals select greatest observed coverage. Point
    metrics (no duration) fall back to presence-based priority. When `details`
    is a dict it receives, per metric, each candidate's covered seconds and
    record count, the chosen source and the selection basis.
    """
    from .store import instant

    if source not in {"preferred", *SOURCES}:
        raise ValueError("Unknown source")
    order = order or priorities()
    wanted = kinds or list(UNITS)
    available = {
        name: store.read(start, end, wanted, origin=origin)
        for name, origin in SOURCES.items()
    }
    selected = []
    chosen = {}
    for kind in wanted:
        names = [source] if source != "preferred" else order[kind]
        candidates = {}
        for name in names:
            rows = [
                r
                for r in available[name]
                if r["kind"] == kind and (eligible is None or eligible(r))
            ]
            if rows:
                candidates[name] = rows
        if not candidates:
            continue
        coverage = {
            n: covered_seconds(rows, start, end) for n, rows in candidates.items()
        }
        best = max(coverage.values())
        if best > 0 and kind in INTERVAL_TOTAL_KINDS:
            # For additive totals, greater observed duration wins. Equal coverage
            # still respects the configured source priority.
            pick = next(n for n in names if coverage.get(n, 0) == best)
            basis = "greatest_observed_interval_coverage"
        elif best > 0:
            pick = next(n for n in names if coverage.get(n, 0) >= COVERAGE_RATIO * best)
            basis = "priority_among_sufficient_coverage"
        else:
            pick = next(n for n in names if n in candidates)
            basis = "priority_by_presence_point_metric"
        if pick != next(n for n in names if n in candidates):
            basis += "_overrode_priority"
        selected.extend(candidates[pick])
        chosen[kind] = pick
        if details is not None:
            window_seconds = max(0.0, (instant(end) - instant(start)).total_seconds())
            details[kind] = {
                "selected": pick,
                "basis": basis,
                "observed_coverage_is_completeness": False,
                "selected_covered_fraction": round(coverage[pick] / window_seconds, 4)
                if window_seconds
                else None,
                "candidates": {
                    n: {
                        "records": len(candidates[n]),
                        "covered_seconds": round(coverage[n], 1),
                        "observed_covered_fraction": round(
                            coverage[n] / window_seconds, 4
                        )
                        if window_seconds
                        else None,
                    }
                    for n in candidates
                },
            }
    return sorted(selected, key=lambda r: (r["start"], r["record_id"])), chosen
