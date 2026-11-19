import os
from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=200000)]
Name = Annotated[str, Field(min_length=1, max_length=500)]
Amount = Annotated[float, Field(ge=0, le=1000000, allow_inf_nan=False)]
Ident = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Provenance(Strict):
    kind: Literal[
        "user_provided",
        "wearable_measurement",
        "ai_estimate",
        "confirmed_fact",
        "unverified_inference",
        "historical_source",
    ]
    source: Name
    original_reference: str | None = Field(default=None, max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=10000)


class BaseRecord(Strict):
    title: Name
    content: str = Field(default="", max_length=200000)
    effective_date: str | None = None
    tags: list[Name] = Field(default_factory=list, max_length=100)
    related_entities: list[Ident] = Field(default_factory=list, max_length=100)
    provenance: Provenance

    @field_validator("effective_date")
    @classmethod
    def day(cls, v):
        if v is not None and date.fromisoformat(v).isoformat() != v:
            raise ValueError("ISO date required")
        return v


class Note(BaseRecord):
    category: Literal[
        "fitness",
        "nutrition",
        "daily_summary",
        "project",
        "travel",
        "preference",
        "decision",
        "conversation",
        "note",
    ] = "note"


class Set(Strict):
    repetitions: int | None = Field(default=None, ge=0, le=10000)
    repetition_range: str | None = Field(default=None, max_length=100)
    weight: Amount | None = None
    weight_unit: Literal["kg", "lb", "bodyweight"] | None = None
    duration_seconds: Amount | None = None
    rest_seconds: Amount | None = None

    @model_validator(mode="after")
    def units(self):
        if self.weight is not None and self.weight_unit is None:
            raise ValueError("Weight requires unit")
        return self


class Exercise(Strict):
    exercise_id: Ident
    name: Name
    sets: list[Set] = Field(min_length=1, max_length=100)
    instructions: str | None = Field(default=None, max_length=10000)
    injury_modifications: str | None = Field(default=None, max_length=10000)


class Plan(BaseRecord):
    effective_date: str
    timezone: str = os.environ.get("FITNESS_TIMEZONE", "UTC")
    objective: Name
    exercises: list[Exercise] = Field(min_length=1, max_length=100)
    completion_status: Literal["planned", "completed", "cancelled"] = "planned"

    @field_validator("timezone")
    @classmethod
    def tz(cls, v):
        ZoneInfo(v)
        return v

    @model_validator(mode="after")
    def unique(self):
        if len({e.exercise_id for e in self.exercises}) != len(self.exercises):
            raise ValueError("Duplicate exercise IDs")
        return self


class Food(Strict):
    name: Name
    quantity: Amount | None = None
    serving_unit: str | None = Field(default=None, max_length=100)
    calories_kcal: Amount | None = None
    protein_g: Amount | None = None
    carbohydrates_g: Amount | None = None
    fat_g: Amount | None = None
    provenance: Provenance


class Meal(BaseRecord):
    consumed_at: str
    timezone: str = os.environ.get("FITNESS_TIMEZONE", "UTC")
    meal_category: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    foods: list[Food] = Field(min_length=1, max_length=100)
    calories_kcal: Amount | None = None
    protein_g: Amount | None = None
    carbohydrates_g: Amount | None = None
    fat_g: Amount | None = None
    source_file_ids: list[Ident] = Field(default_factory=list, max_length=20)
    assumptions: list[Name] = Field(default_factory=list, max_length=100)
    user_confirmed_values: bool = False
    correction_notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def local_day(self):
        t = datetime.fromisoformat(self.consumed_at.replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError("Timestamp requires UTC offset")
        local = t.astimezone(ZoneInfo(self.timezone))
        if t.utcoffset() != local.utcoffset():
            raise ValueError("Timestamp offset must agree with timezone")
        day = local.date().isoformat()
        if self.effective_date and self.effective_date != day:
            raise ValueError("Effective date disagrees with meal time")
        self.effective_date = day
        return self


class Project(BaseRecord):
    description: Text
    objectives: list[Name] = Field(default_factory=list, max_length=100)
    status: Name
    open_questions: list[Name] = Field(default_factory=list, max_length=100)
    next_actions: list[Name] = Field(default_factory=list, max_length=100)
    source_references: list[Name] = Field(default_factory=list, max_length=100)


class Decision(BaseRecord):
    project_id: Ident | None = None
    decision: Text
    rationale: str | None = Field(default=None, max_length=20000)
    supersedes_id: Ident | None = None


class FileRecord(BaseRecord):
    original_filename: Name
    mime_type: Name
    reference: str | None = Field(default=None, max_length=4000)
    content_base64: str | None = Field(default=None, max_length=28000000)
    description: str | None = Field(default=None, max_length=20000)
    description_explicitly_generated: bool = False

    @model_validator(mode="after")
    def description_source(self):
        if not self.reference and not self.content_base64:
            raise ValueError("Bytes or reference required")
        if self.description and not self.description_explicitly_generated:
            raise ValueError("Description provenance must be explicit")
        return self


class Mapping(Strict):
    exercise_id: Ident
    garmin_set_orders: list[Annotated[int, Field(ge=1)]] = Field(
        min_length=1, max_length=100
    )


class WorkoutLink(BaseRecord):
    plan_id: Ident
    activity_id: Annotated[str, Field(pattern=r"^[0-9]{1,30}$")]
    association_confirmed: Literal[True]
    exercise_mappings: list[Mapping] = Field(default_factory=list, max_length=100)
    corrected_sets: list[Set] | None = Field(default=None, max_length=100)
    correction_notes: str | None = Field(default=None, max_length=20000)
