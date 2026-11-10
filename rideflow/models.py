"""Pydantic models for the Rideflow plan data model.

Mirrors the shape agreed in docs/spec.md (Plan / Stage), which came from the
#0007 prototype.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Point(BaseModel):
    name: str
    lon: float
    lat: float


class ParsedIntent(BaseModel):
    origin: str
    destination: str
    days: int
    target_daily_km: Optional[float] = None


class Intent(BaseModel):
    raw: str
    parsed: ParsedIntent


class Route(BaseModel):
    geometry: str
    distance_km: float
    climb_m: float
    descent_m: float
    surface_breakdown: dict


class Stage(BaseModel):
    day: int
    start: Point
    end: Point
    route: Route
    via: list[Point] = Field(default_factory=list)
    poi_refs: list[str] = Field(default_factory=list)
    notes: str = ""
    status: str = "draft"


class Metadata(BaseModel):
    model: str
    created_at: str
    version: int


class Plan(BaseModel):
    id: str
    intent: Intent
    stages: list[Stage]
    metadata: Metadata
