import statistics
import json
import os
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from .store import instant
from .sources import SOURCES, UNITS, priorities, read_selected

ORIGIN = "com.garmin.android.apps.connectmobile"
TOOLS = [
    "get_daily_metrics",
    "get_sleep_history",
    "get_heart_rate_trends",
    "get_activity_summary",
    "get_recovery_summary",
    "get_weekly_fitness_report",
    "get_source_coverage",
    "compare_sources",
]


def bounds(day, tz):
    d = date.fromisoformat(day)
    z = ZoneInfo(tz)
    return datetime.combine(d, time(), z), datetime.combine(
        d + timedelta(days=1), time(), z
    )


def iso(d):
    return d.astimezone(timezone.utc).isoformat()


def mean(xs):
    return round(statistics.mean(xs), 2) if xs else None


def seconds(a, b, lo, hi):
    return max(0, (min(instant(b), hi) - max(instant(a), lo)).total_seconds())


class Queries:
    def __init__(self, store, source="preferred", source_priorities=None):
        self.store = store
        self.source = source
        self.source_priorities = source_priorities or priorities()

    def daily(self, day, tz):
        a, b = bounds(day, tz)
        au, bu = a.astimezone(timezone.utc), b.astimezone(timezone.utc)

        def eligible(r):
            if r["kind"] == "sleep":
                return au <= instant(r["end"]) < bu
            if r["kind"] == "steps":
                return au <= instant(r["start"]) and instant(r["end"]) <= bu
            if r["kind"] == "heart_rate":
                return any(au <= instant(s["time"]) < bu for s in r["data"]["samples"])
            if r["start"] == r["end"]:
                return au <= instant(r["start"]) < bu
            return True

        selection = {}
        rows, selected = read_selected(
            self.store,
            iso(a),
            iso(b),
            source=self.source,
            order=self.source_priorities,
            eligible=eligible,
            details=selection,
        )
        hr = []
        sleep = []
        step_rows = []
        for r in rows:
            if r["kind"] == "heart_rate":
                hr += [
                    s["bpm"]
                    for s in r["data"]["samples"]
                    if au <= instant(s["time"]) < bu
                ]
            if r["kind"] == "sleep" and au <= instant(r["end"]) < bu:
                stages = r["data"]["stages"]
                asleep = sum(
                    seconds(
                        s["start"], s["end"], instant(r["start"]), instant(r["end"])
                    )
                    for s in stages
                    if s["stage"] in ["sleeping", "light", "deep", "rem"]
                )
                sleep.append(
                    {
                        "origin": r["origin"],
                        "record_id": r["record_id"],
                        "provenance": r["data"].get("_provenance"),
                        "start": r["start"],
                        "end": r["end"],
                        "asleep_hours": round(asleep / 3600, 3)
                        if stages
                        and all(s["stage"] != "unknown" for s in stages)
                        and sum(
                            (instant(s["end"]) - instant(s["start"])).total_seconds()
                            for s in stages
                        )
                        == (instant(r["end"]) - instant(r["start"])).total_seconds()
                        else None,
                        "session_hours": round(
                            (instant(r["end"]) - instant(r["start"])).total_seconds()
                            / 3600,
                            3,
                        ),
                        "stages": stages,
                    }
                )
            if r["kind"] == "steps":
                step_rows.append(r)
        # Never prorate interval totals or silently add overlapping sources/records.
        contained = [
            r
            for r in step_rows
            if au <= instant(r["start"]) and instant(r["end"]) <= bu
        ]
        overlap = any(
            instant(x["end"]) > instant(y["start"])
            for x, y in zip(contained, contained[1:])
        )
        # Intervals from the selected (or only observed) step source that cross a
        # day boundary are excluded from the total; say so instead of implying
        # the contained sum is the whole day.
        step_source = selected.get("steps") or (
            self.source if self.source in SOURCES else None
        )
        step_origins = [SOURCES[step_source]] if step_source else list(SOURCES.values())
        crossing = [
            r
            for origin in step_origins
            for r in self.store.read(iso(a), iso(b), ["steps"], origin=origin)
            if instant(r["end"]) > au
            and instant(r["start"]) < bu
            and not (au <= instant(r["start"]) and instant(r["end"]) <= bu)
        ]

        def point(kind, key):
            return [
                r["data"][key]
                for r in rows
                if r["kind"] == kind and au <= instant(r["start"]) < bu
            ]

        missing = []

        def val(kind, key):
            xs = point(kind, key)
            if not xs:
                missing.append(kind)
            return mean(xs)

        rhr = val("resting_heart_rate", "bpm")
        hrv = val("hrv_rmssd", "ms")
        ordered = sorted(sleep, key=lambda s: s["start"])
        if any(x["end"] > y["start"] for x, y in zip(ordered, ordered[1:])):
            for session in sleep:
                session["asleep_hours"] = None
        if not sleep:
            missing.append("sleep")
        if not hr:
            missing.append("heart_rate")
        if not contained:
            missing.append("steps")
        return {
            "date": day,
            "timezone": tz,
            "source": SOURCES[self.source]
            if self.source in SOURCES
            else SOURCES.get(next(iter(set(selected.values()))))
            if len(set(selected.values())) == 1
            else "metric_priority",
            "selected_sources": selected,
            "resting_heart_rate_bpm": rhr,
            "hrv_rmssd_ms": hrv,
            "heart_rate": {
                "sample_count": len(hr),
                "sample_mean_bpm": mean(hr),
                "min_bpm": min(hr) if hr else None,
                "max_bpm": max(hr) if hr else None,
            },
            "sleep": sleep,
            "sleep_hours": round(
                sum(x["asleep_hours"] for x in sleep if x["asleep_hours"] is not None),
                3,
            )
            if sleep and all(x["asleep_hours"] is not None for x in sleep)
            else None,
            "additional_metrics": {
                kind: {
                    "unit": UNITS[kind],
                    "values": [r["data"] for r in rows if r["kind"] == kind],
                    "source": selected.get(kind),
                }
                for kind in UNITS
                if kind
                not in {
                    "heart_rate",
                    "resting_heart_rate",
                    "hrv_rmssd",
                    "sleep",
                    "steps",
                    "activity",
                    "weight",
                    "body_fat",
                }
            },
            "steps": None
            if overlap or not contained
            else sum(r["data"]["count"] for r in contained),
            "steps_partial": bool(crossing) and bool(contained) and not overlap,
            # No amount of record coverage proves that a watch was worn or that
            # upstream Health Connect exports were exhaustive for this day.
            "steps_completeness": "unverified",
            "steps_observed_covered_fraction": selection.get("steps", {}).get(
                "selected_covered_fraction"
            ),
            "steps_excluded_boundary_intervals": len(crossing),
            "source_selection": selection,
            "weight_kg": point("weight", "kg"),
            "body_fat_percent": point("body_fat", "percent"),
            "missing_metrics": missing,
            "quality_notes": [
                "Sleep assigned to local wake date; duration excludes known awake stages; missing stages mean unknown sleep duration.",
                "Heart rate mean is sample weighted, not resting HR or time weighted.",
                "Step totals include only fully contained intervals; crossing-midnight intervals are excluded and flagged by steps_partial. Overlapping intervals yield unknown.",
                "Additive interval totals select the source with greatest observed record coverage; non-additive interval metrics retain a relative-coverage priority threshold; see source_selection.",
                "Observed record coverage never proves wear time or completeness; steps_completeness remains unverified.",
                "No device wear-time or completeness guarantee; absent data is not zero.",
            ],
            "record_count": len(rows),
        }

    def days(self, day, count, tz):
        d = date.fromisoformat(day)
        return [
            self.daily((d - timedelta(days=i)).isoformat(), tz)
            for i in reversed(range(count))
        ]

    def recovery(self, day, tz):
        days = self.days(day, 24, tz)
        baseline = days[:21]
        recent = days[21:]
        signals = []
        coverage = {}
        for key, direction, threshold in [
            ("sleep_hours", -1, 1.0),
            ("resting_heart_rate_bpm", 1, 5.0),
            ("hrv_rmssd_ms", -1, 0.2),
        ]:
            old = [d[key] for d in baseline if d[key] is not None]
            new = [d[key] for d in recent if d[key] is not None]
            coverage[key] = {"baseline_days": len(old), "recent_days": len(new)}
            kind = {
                "sleep_hours": "sleep",
                "resting_heart_rate_bpm": "resting_heart_rate",
                "hrv_rmssd_ms": "hrv_rmssd",
            }[key]
            used = {d["selected_sources"].get(kind) for d in days if d[key] is not None}
            coverage[key]["source_changed"] = len(used) > 1
            if len(old) < 10 or len(new) < 3 or len(used) > 1:
                continue
            base = statistics.median(old)
            current = statistics.median(new)
            change = current - base
            adverse = change * direction >= (
                base * threshold if key == "hrv_rmssd_ms" else threshold
            )
            signals.append(
                {
                    "metric": key,
                    "baseline_median": base,
                    "recent_median": current,
                    "adverse": adverse,
                }
            )
        bad = sum(s["adverse"] for s in signals)
        status = (
            "multiple_adverse_signals"
            if bad >= 2
            else "insufficient_data"
            if len(signals) < 2
            else "no_multiple_signal_flag"
        )
        advice = "Review observed coverage and personal context before interpreting these experimental signals."
        if bad >= 2:
            advice = "Multiple experimental signals were flagged; no automatic action is taken."
        return {
            "date": day,
            "status": status,
            "signals": signals,
            "coverage": coverage,
            "recommendation": advice,
            "limitations": [
                "Experimental transparent rules, not a validated readiness model or medical advice.",
                "Requires 10 baseline days and all 3 recent days per signal; never acts on one reading.",
                "No HRV or resting HR is inferred from ordinary heart rate.",
                "Sleep alone cannot trigger a recovery adjustment.",
            ],
        }

    def call(self, name, args):
        if name not in TOOLS:
            raise ValueError("unknown tool")
        if not isinstance(args, dict) or set(args) - {
            "end_date",
            "days",
            "timezone",
            "source",
            "metric",
        }:
            raise ValueError("unknown arguments")
        source = args.get("source", self.source)
        if source not in {"preferred", *SOURCES}:
            raise ValueError("Unknown source")
        if source != self.source:
            return Queries(self.store, source, self.source_priorities).call(
                name, {k: v for k, v in args.items() if k != "source"}
            )
        tz = args.get("timezone", os.environ.get("FITNESS_TIMEZONE", "UTC"))
        ZoneInfo(tz)
        day = args.get("end_date", datetime.now(ZoneInfo(tz)).date().isoformat())
        date.fromisoformat(day)
        n = args.get("days", 7)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 90:
            raise ValueError("days must be between 1 and 90")
        if name in ["get_source_coverage", "compare_sources"]:
            from .source_queries import source_coverage, compare_sources

            metric = args.get("metric")
            if metric is not None and metric not in UNITS:
                raise ValueError("Unknown metric")
            return (
                source_coverage if name == "get_source_coverage" else compare_sources
            )(self, day, n, tz, metric)
        if "metric" in args:
            raise ValueError("Metric filter is only available for source tools")
        if name == "get_daily_metrics":
            return self.daily(day, tz)
        if name == "get_recovery_summary":
            return self.recovery(day, tz)
        if name == "get_weekly_fitness_report":
            days = self.days(day, 7, tz)
            report = {
                "end_date": day,
                "days": days,
                "recovery": self.recovery(day, tz),
                "training_context": {},
            }
            # Opt-in local context for authorized fitness clients.
            # Explicit missing/corrupt profiles fail visibly rather than inventing details.
            profile = os.environ.get("FITNESS_PROFILE_FILE")
            if profile:
                context = json.loads(Path(profile).read_text())
                if not isinstance(context, dict):
                    raise ValueError("Invalid fitness profile")
                report["training_context"]["user_profile"] = context
            return report
        if name == "get_heart_rate_trends":
            return [
                {
                    "date": d["date"],
                    **d["heart_rate"],
                    "resting_heart_rate_bpm": d["resting_heart_rate_bpm"],
                }
                for d in self.days(day, n, tz)
            ]
        if name == "get_sleep_history":
            return [
                {
                    "date": d["date"],
                    "sleep_hours": d["sleep_hours"],
                    "sessions": d["sleep"],
                }
                for d in self.days(day, n, tz)
            ]
        a, _ = bounds((date.fromisoformat(day) - timedelta(days=n - 1)).isoformat(), tz)
        _, b = bounds(day, tz)
        # Select activity sources per workout, not once for the whole date window.
        names = (
            [self.source]
            if self.source != "preferred"
            else self.source_priorities["activity"]
        )
        rows = [
            r
            for name in names
            for r in self.store.read(iso(a), iso(b), ["activity"], origin=SOURCES[name])
        ]
        rank = {SOURCES[name]: i for i, name in enumerate(names)}
        activities = []
        excluded = []
        accepted = []
        duplicates = {}
        # Stable tie-breaking: source priority first, newest revision within a source.
        ordered = sorted(
            rows, key=lambda r: (r["modified"], r["record_id"]), reverse=True
        )
        ordered.sort(key=lambda r: rank[r["origin"]])
        for r in ordered:
            match = next(
                (
                    x
                    for x in accepted
                    if instant(r["start"]) < instant(x["end"])
                    and instant(x["start"]) < instant(r["end"])
                    and (
                        r["origin"] == x["origin"]
                        or (
                            min(instant(r["end"]), instant(x["end"]))
                            - max(instant(r["start"]), instant(x["start"]))
                        ).total_seconds()
                        >= 0.8
                        * max(
                            (instant(r["end"]) - instant(r["start"])).total_seconds(),
                            (instant(x["end"]) - instant(x["start"])).total_seconds(),
                        )
                    )
                ),
                None,
            )
            if match is not None:
                excluded.append(r["record_id"])
                duplicates.setdefault((match["origin"], match["record_id"]), []).append(
                    {
                        "origin": r["origin"],
                        "record_id": r["record_id"],
                        "start": r["start"],
                        "end": r["end"],
                        "exercise_type": r["data"]["exercise_type"],
                        "provenance": r["data"].get("_provenance"),
                    }
                )
            else:
                accepted.append(r)
        rows = sorted(accepted, key=lambda r: r["start"])
        used = [
            name for name in names if any(r["origin"] == SOURCES[name] for r in rows)
        ]
        selected = {"activity": used[0] if len(used) == 1 else "mixed"} if used else {}
        for r in rows:
            hr = (
                self.store.read(
                    r["start"], r["end"], ["heart_rate"], origin=r["origin"]
                )
                if r["start"] < r["end"]
                else []
            )
            samples = [
                s["bpm"]
                for x in hr
                for s in x["data"]["samples"]
                if r["start"] <= s["time"] < r["end"]
            ]
            activities.append(
                {
                    "origin": r["origin"],
                    "record_id": r["record_id"],
                    "provenance": r["data"].get("_provenance"),
                    "start": r["start"],
                    "end": r["end"],
                    "exercise_type": r["data"]["exercise_type"],
                    "duration_minutes": round(
                        (instant(r["end"]) - instant(r["start"])).total_seconds() / 60,
                        2,
                    ),
                    "overlapping_originals": duplicates.get(
                        (r["origin"], r["record_id"]), []
                    ),
                    "sample_mean_bpm": mean(samples),
                    "sample_count": len(samples),
                }
            )
        return {
            "activities": activities,
            "selected_sources": selected,
            "excluded_overlapping_record_ids": excluded,
            "coverage_note": "Activity source priority applies per workout. Cross-source recordings overlapping at least 80% of the longer recording count once; same-source overlaps retain the newest record. Originals remain stored and overlapping originals are listed. Workout HR uses only the selected source app.",
        }
