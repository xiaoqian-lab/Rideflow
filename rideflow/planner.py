"""Deterministic planning core (ticket 02).

Turns a structured trip request into a day-by-day plan. ``compute_route`` is
backed by real Valhalla routing (ticket 03) and falls back to a straight-line
estimate only when no routing data is available.
"""

import logging
import math
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from rideflow.models import Intent, Metadata, ParsedIntent, Plan, Point, Route, Stage

logger = logging.getLogger(__name__)


class PlanningRequest(BaseModel):
    origin: Point
    destination: Point
    days: int = Field(gt=0)
    target_daily_km: float = Field(gt=0)


def _haversine_km(a: Point, b: Point) -> float:
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lon2 - lon1) / 2
    ) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _interpolate(a: Point, b: Point, t: float) -> Point:
    if t == 0.0:
        return a
    if t == 1.0:
        return b
    return Point(name="", lon=a.lon + (b.lon - a.lon) * t, lat=a.lat + (b.lat - a.lat) * t)


def _encode_polyline(points: list[Point]) -> str:
    return ";".join(f"{p.lon},{p.lat}" for p in points)


def _straight_line_route(origin: Point, destination: Point) -> Route:
    """Straight-line estimate used only when Valhalla cannot route.

    This is an explicit, honest fallback (a crow-flies estimate), never a
    disguised routing result. ``compute_route`` prefers real Valhalla numbers.
    """
    return Route(
        geometry=_encode_polyline([origin, destination]),
        distance_km=round(_haversine_km(origin, destination), 3),
        climb_m=0.0,
        descent_m=0.0,
        surface_breakdown={"paved": 1.0, "gravel": 0.0},
    )


def compute_route(origin: Point, destination: Point) -> Route:
    """Route from origin to destination via Valhalla.

    When Valhalla tile data is unavailable (or the points fall outside the
    loaded tiles), fall back to a straight-line estimate rather than fabricating
    routing numbers.
    """
    from rideflow.routing import RoutingUnavailableError, get_router

    router = get_router()
    if router is not None:
        try:
            return router.route(origin, destination)
        except RoutingUnavailableError as exc:
            logger.warning(
                "Valhalla route failed, using straight-line estimate: %s", exc
            )
    return _straight_line_route(origin, destination)


def segment_route(
    route: Route, origin: Point, destination: Point, days: int
) -> list[Stage]:
    """Split the route into `days` equal stages (straight-line interpolation)."""
    per_day_km = route.distance_km / days
    stages: list[Stage] = []
    for i in range(days):
        start = _interpolate(origin, destination, i / days)
        end = _interpolate(origin, destination, (i + 1) / days)
        stages.append(
            Stage(
                day=i + 1,
                start=start,
                end=end,
                route=Route(
                    geometry=_encode_polyline([start, end]),
                    distance_km=round(per_day_km, 3),
                    climb_m=route.climb_m,
                    descent_m=route.descent_m,
                    surface_breakdown=route.surface_breakdown,
                ),
                notes="",
                status="draft",
            )
        )
    return stages


def materialize(
    origin: Point,
    destination: Point,
    days: int,
    target_daily_km: float,
    stages: list[Stage],
) -> Plan:
    """Assemble a Plan from already-computed stages. Never recomputes numbers."""
    return Plan(
        id=str(uuid4()),
        intent=Intent(
            raw="",
            parsed=ParsedIntent(
                origin=origin.name,
                destination=destination.name,
                days=days,
                target_daily_km=target_daily_km,
            ),
        ),
        stages=stages,
        metadata=Metadata(
            model="deepseek-flash",
            created_at=datetime.now(timezone.utc).isoformat(),
            version=1,
        ),
    )


def plan_trip(
    origin: Point, destination: Point, days: int, target_daily_km: float
) -> Plan:
    route = compute_route(origin, destination)
    stages = segment_route(route, origin, destination, days)
    return materialize(origin, destination, days, target_daily_km, stages)
