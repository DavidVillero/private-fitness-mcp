"""Read-only workout views over a separate direct-Garmin cache.

Never merged into Health Connect records or daily calorie totals. Raw Garmin
payloads are retained locally to make every normalization auditable.
"""

import json
import os
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WORKOUT_TOOLS = {
    "get_workout_details": {
        "description": "Direct Garmin completed workout details, exercise sets, weights with source units, rest, laps, HR timeline and calories. Cache only; never adds to Health Connect totals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "pattern": "^[0-9]{1,20}$"}
            },
            "required": ["activity_id"],
            "additionalProperties": False,
        },
    },
    "get_recent_workouts": {
        "description": "Direct Garmin completed workouts and original activity IDs, with sync freshness. Does not combine Garmin and Zepp.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7}
            },
            "additionalProperties": False,
        },
    },
    "get_exercise_history": {
        "description": "Case-insensitive exact exercise name history from direct Garmin; sets, reps, explicit weights and known-unit volume. Missing weights/names remain unknown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exercise_name": {"type": "string", "minLength": 1, "maxLength": 160},
                "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 90},
            },
            "required": ["exercise_name"],
            "additionalProperties": False,
        },
    },
}

# Endpoint convention used by the adapter; explicit units take precedence.
# Retain raw values so this assumption can be reviewed against vendor changes.
WEIGHT_CONVENTION = (
    "exerciseSets grams; adapter convention when explicit units are absent"
)


def number(value):
    return (
        value
        if isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def activity_id(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]{1,20}", value)
        or int(value) <= 0
    ):
        raise ValueError("Invalid Garmin activity ID")
    return str(int(value))


def utc_start(summary):
    value = summary.get("startTimeGMT")
    if not value:
        return None
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        value.replace(tzinfo=value.tzinfo or timezone.utc)
        .astimezone(timezone.utc)
        .isoformat()
    )


def normalize(ident, payloads, endpoints, fetched_at):
    full = payloads.get("activity") or {}
    summary = full.get("summaryDTO") or full or payloads.get("listing") or {}
    listing = payloads.get("listing") or {}
    merged = {**listing, **summary}
    sets_payload = payloads.get("exercise_sets") or {}
    sets = (
        (sets_payload.get("exerciseSets") or [])
        if isinstance(sets_payload, dict)
        else []
    )
    exercises = []
    for order, item in enumerate(sets, 1):
        names = item.get("exercises") or []
        names = [
            {
                "name": e.get("exerciseName") or e.get("name"),
                "category": e.get("category"),
                "source": e,
            }
            for e in names
            if isinstance(e, dict)
        ]
        # Keep Garmin's names and enum spelling rather than guessing an exercise.
        exact = item.get("exerciseName") or (names[0]["name"] if names else None)
        category = names[0]["category"] if names else None
        name = exact or (category if category not in (None, "UNKNOWN") else None)
        weight = number(item.get("weight"))
        unit = item.get("weightUnit")
        unit_name = (
            (unit.get("unitKey") or unit.get("unitName"))
            if isinstance(unit, dict)
            else unit
        )
        kg = None
        if weight is not None:
            factor = (
                0.001
                if unit is None
                else {
                    "kg": 1,
                    "kilogram": 1,
                    "kilograms": 1,
                    "g": 0.001,
                    "gram": 0.001,
                    "grams": 0.001,
                    "lb": 0.45359237,
                    "lbs": 0.45359237,
                    "pound": 0.45359237,
                    "pounds": 0.45359237,
                }.get(str(unit_name).lower())
            )
            if factor is not None:
                kg = weight * factor
        reps = number(item.get("repetitionCount"))
        kind = item.get("setType")
        volume = (
            kg * reps
            if kg is not None and reps is not None and kind == "ACTIVE"
            else None
        )
        exercises.append(
            {
                "order": order,
                "exercise_name": name,
                "exercise_name_specificity": "exercise"
                if exact
                else "category"
                if name
                else "unknown",
                "exercise_candidates": names,
                "set_type": kind,
                "repetitions": reps,
                "weight_original": weight,
                "weight_unit_original": unit,
                "weight_kg": kg,
                "weight_interpretation": WEIGHT_CONVENTION
                if unit is None and weight is not None
                else "explicit_unit"
                if unit
                else None,
                "volume_kg_repetitions": volume,
                "duration_seconds": number(item.get("duration")),
                "start_time": item.get("startTime"),
                "source_set": item,
            }
        )
    details = payloads.get("details") or {}
    descriptors = details.get("metricDescriptors") or []
    indices = {d.get("key"): d.get("metricsIndex") for d in descriptors}
    hr_index = indices.get("directHeartRate")
    time_index = indices.get("directTimestamp")
    samples = []
    if isinstance(hr_index, int):
        for sample in details.get("activityDetailMetrics") or []:
            values = sample.get("metrics") or []
            bpm = number(values[hr_index]) if hr_index < len(values) else None
            stamp = (
                number(values[time_index])
                if isinstance(time_index, int) and time_index < len(values)
                else None
            )
            if bpm is not None and bpm > 0:
                samples.append({"timestamp_garmin": stamp, "bpm": bpm})
    total = number(merged.get("calories"))
    active = number(merged.get("activeKilocalories"))
    bmr = number(merged.get("bmrCalories"))
    active_method = "reported" if active is not None else "unavailable"
    if active is None and total is not None and bmr is not None and total >= bmr:
        active = total - bmr
        active_method = "derived_total_minus_reported_bmr"
    return {
        "activity_id": activity_id(str(ident)),
        "source": "garmin_connect_direct",
        "fetched_at": fetched_at,
        "name": full.get("activityName") or listing.get("activityName"),
        "activity_type": full.get("activityTypeDTO") or listing.get("activityType"),
        "start_utc": utc_start(merged),
        "start_local_garmin": merged.get("startTimeLocal"),
        "duration_seconds": number(merged.get("duration")),
        "average_heart_rate_bpm": number(merged.get("averageHR")),
        "max_heart_rate_bpm": number(merged.get("maxHR")),
        "calories": {
            "total_kcal": total,
            "active_kcal": active,
            "resting_kcal": bmr,
            "active_method": active_method,
        },
        "sets": exercises,
        "heart_rate": {
            "samples": samples,
            "sample_count": len(samples),
            "metric_descriptors": descriptors,
            "sampling_note": "Garmin chart endpoint requested up to 20000 points; may be downsampled. Original timestamps and descriptor units retained.",
        },
        "laps": payloads.get("splits"),
        "heart_rate_zones": payloads.get("hr_zones"),
        "training_volume": {
            "known_kg_repetitions": sum(
                x["volume_kg_repetitions"]
                for x in exercises
                if x["volume_kg_repetitions"] is not None
            )
            if any(x["volume_kg_repetitions"] is not None for x in exercises)
            else None,
            "sets_with_known_volume": sum(
                x["volume_kg_repetitions"] is not None for x in exercises
            ),
            "active_sets": sum(x["set_type"] == "ACTIVE" for x in exercises),
            "note": "Partial recorded external-load volume only for ACTIVE sets with supported units or adapter exerciseSets gram convention and repetitions; unknown is not zero. Bodyweight sets contribute zero external load, not zero effort.",
        },
        "endpoint_status": endpoints,
        "quality_notes": [
            "Separate direct Garmin detail cache; do not add these activities/calories to Health Connect summaries.",
            "Device-detected exercise names and reps may need correction in Garmin. No exercise names or weights are inferred.",
            "HRV and day completeness are not inferred from workout HR. Missing endpoints are explicit.",
        ],
    }


def status(store):
    with store.connect(True) as c:
        row = c.execute("SELECT data FROM garmin_sync_state WHERE id=1").fetchone()
    state = json.loads(row["data"]) if row else {"status": "not_synced"}
    last = state.get("last_success_utc")
    state["hours_since_success"] = (
        round(
            (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            / 3600,
            2,
        )
        if last
        else None
    )
    state["stale"] = (
        state["hours_since_success"] is None or state["hours_since_success"] > 1.5
    )
    state["completeness_note"] = (
        "Cache freshness is not proof of complete device wear or completed phone-to-Garmin sync. Today may be incomplete."
    )
    return state


def call(store, name, args):
    if not isinstance(args, dict) or set(args) - set(
        WORKOUT_TOOLS[name]["inputSchema"]["properties"]
    ):
        raise ValueError("Invalid workout arguments")
    if name == "get_workout_details":
        ident = activity_id(args.get("activity_id"))
        with store.connect(True) as c:
            row = c.execute(
                "SELECT data FROM garmin_workouts WHERE activity_id=?", (ident,)
            ).fetchone()
        return {
            "sync": status(store),
            "workout": json.loads(row["data"]) if row else None,
            "missing_note": None
            if row
            else "Not in direct Garmin cache. Check authentication and sync status; absent does not mean no workout.",
        }
    days = args.get("days", 90 if name == "get_exercise_history" else 7)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("Invalid days")
    exercise = args.get("exercise_name")
    if name == "get_exercise_history" and (
        not isinstance(exercise, str) or not 1 <= len(exercise.strip()) <= 160
    ):
        raise ValueError("Invalid exercise name")
    now = datetime.now(timezone.utc)
    # Inclusive local calendar days, consistent with existing fitness tools.
    lower = (
        (
            now.astimezone(ZoneInfo(os.environ.get("FITNESS_TIMEZONE", "UTC"))).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            - timedelta(days=days - 1)
        )
        .astimezone(timezone.utc)
        .isoformat()
    )
    with store.connect(True) as c:
        rows = c.execute(
            "SELECT data FROM garmin_workouts WHERE start_utc>=? AND start_utc<=? ORDER BY start_utc DESC LIMIT 1001",
            (lower, now.isoformat()),
        ).fetchall()
    truncated = len(rows) > 1000
    workouts = [json.loads(r["data"]) for r in rows[:1000]]
    if name == "get_recent_workouts":
        results = [
            {
                k: v
                for k, v in w.items()
                if k not in {"sets", "heart_rate", "laps", "heart_rate_zones"}
            }
            for w in workouts
        ]
    else:
        results = []
        for w in workouts:
            sets = [
                s
                for s in w["sets"]
                if isinstance(s.get("exercise_name"), str)
                and s["exercise_name"].casefold() == exercise.strip().casefold()
                and s["set_type"] == "ACTIVE"
            ]
            if sets:
                values = [
                    s["volume_kg_repetitions"]
                    for s in sets
                    if s["volume_kg_repetitions"] is not None
                ]
                results.append(
                    {
                        "activity_id": w["activity_id"],
                        "start_utc": w["start_utc"],
                        "sets": sets,
                        "known_volume_kg_repetitions": sum(values) if values else None,
                        "volume_complete": len(values) == len(sets),
                    }
                )
    return {
        "sync": status(store),
        "days": days,
        "timezone": os.environ.get("FITNESS_TIMEZONE", "UTC"),
        "truncated": truncated,
        "workouts": results,
        "note": "Direct Garmin only; historical comparison is based on recorded exercise names and explicit loads. Unknown names/loads cannot support complete volume comparisons.",
    }
