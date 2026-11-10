"""Valhalla routing adapter (ticket 03).

Wraps pyvalhalla's ``Actor`` so the rest of the app talks in Rideflow's own
``Point``/``Route`` shapes. The adapter is a thin seam: it turns two points into
a Valhalla route request and turns the response trip back into a ``Route``
without reinterpreting the numbers.

Tile data is read from the directory given by the ``RIDEflow_TILES_DIR``
environment variable, or from ``<repo>/data/valhalla_tiles`` by default. When
no tile data is present the adapter raises :class:`RoutingUnavailableError` and
the caller (:func:`rideflow.planner.compute_route`) falls back to an explicit,
straight-line estimate — never a silently fabricated route.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from rideflow.models import Point, Route

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import-time check only
    import valhalla
except ImportError:  # pragma: no cover
    valhalla = None


class RoutingUnavailableError(RuntimeError):
    """Valhalla cannot produce a route (missing tiles or no route found)."""


# Valhalla uses -500 as the "no elevation data" sentinel in the elevation array.
_SENTINEL_ELEVATION = -400.0


def default_tiles_dir() -> Path:
    """Directory that holds built Valhalla tiles.

    Overridable with the ``RIDEflow_TILES_DIR`` env var; defaults to
    ``<repo>/data/valhalla_tiles``.
    """
    env = os.environ.get("RIDEflow_TILES_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data" / "valhalla_tiles"


def build_route_request(origin: Point, destination: Point) -> dict:
    """Build a Valhalla ``route`` request for a single origin -> destination.

    The costing is a fixed, sensible bicycle default (mixed-surface "hybrid",
    moderate hill sensitivity). The ``compute_route`` signature carries no
    preference arguments, so preferences are pinned here for now.
    """
    return {
        "locations": [
            {"lat": origin.lat, "lon": origin.lon, "type": "break"},
            {"lat": destination.lat, "lon": destination.lon, "type": "break"},
        ],
        "costing": "bicycle",
        "costing_options": {
            "bicycle": {
                "bicycle_type": "hybrid",
                "use_hills": 0.5,
                "avoid_bad_surfaces": 0.5,
            }
        },
        "directions_options": {"units": "kilometers"},
        "elevation_interval": 30.0,
    }


def climb_descent_from_heights(heights: list[float]) -> tuple[float, float]:
    """Cumulative climb/descent (metres) from an ordered list of heights.

    ``heights`` are elevation samples along the route. The Valhalla "no data"
    sentinel values are skipped. Returns ``(climb_m, descent_m)`` where climb is
    the sum of all upward deltas and descent is the absolute sum of all
    downward deltas.
    """
    climb = 0.0
    descent = 0.0
    previous: Optional[float] = None
    for height in heights:
        if height <= _SENTINEL_ELEVATION:
            # Missing sample: reset so we never bridge an unknown gap.
            previous = None
            continue
        if previous is not None:
            delta = height - previous
            if delta > 0:
                climb += delta
            else:
                descent += -delta
        previous = height
    return round(climb, 3), round(descent, 3)


def _leg_heights(leg: dict) -> list[float]:
    """Extract the ordered elevation samples from a route leg, if present."""
    raw = leg.get("elevation")
    if not raw:
        return []
    return [float(h) for h in raw if isinstance(h, (int, float))]


def route_from_response(response: dict) -> Route:
    """Turn a Valhalla ``route`` response into a :class:`Route`.

    Distance and geometry come straight from the trip; climb/descent are
    derived from the elevation samples Valhalla returns (0.0 when the graph was
    built without elevation data).

    ``surface_breakdown`` is left empty: Valhalla's ``route`` action does not
    report a per-edge surface breakdown (that would require the separate
    ``trace_attributes`` action), so an empty dict honestly signals "unknown"
    rather than invented numbers.
    """
    trip = response["trip"]
    legs = trip.get("legs", [])

    summary = trip.get("summary", {})
    distance_km = round(float(summary.get("length", 0.0)), 3)

    # Single origin->destination route: one leg. Fall back to the trip shape.
    geometry = ""
    if legs:
        geometry = legs[0].get("shape", "") or trip.get("shape", "")

    heights: list[float] = []
    for leg in legs:
        heights.extend(_leg_heights(leg))
    climb_m, descent_m = climb_descent_from_heights(heights)

    return Route(
        geometry=geometry,
        distance_km=distance_km,
        climb_m=climb_m,
        descent_m=descent_m,
        surface_breakdown={},
    )


class ValhallaRouter:
    """Thin wrapper around ``valhalla.Actor`` for origin -> destination routes."""

    def __init__(self, tiles_dir: Optional[Path] = None):
        if valhalla is None:  # pragma: no cover - only when pyvalhalla absent
            raise RoutingUnavailableError("pyvalhalla is not installed")
        self.tiles_dir = Path(tiles_dir) if tiles_dir else default_tiles_dir()
        if not self.tiles_dir.is_dir():
            raise RoutingUnavailableError(
                f"Valhalla tile dir not found: {self.tiles_dir}"
            )
        config = valhalla.get_config(tile_extract="", tile_dir=str(self.tiles_dir))
        self._actor = valhalla.Actor(config)

    def route(self, origin: Point, destination: Point) -> Route:
        request = build_route_request(origin, destination)
        try:
            response = self._actor.route(request)
        except Exception as exc:  # noqa: BLE001 - surface C++ errors uniformly
            raise RoutingUnavailableError(str(exc)) from exc
        return route_from_response(response)


_router: Optional[ValhallaRouter] = None
_router_resolved = False


def get_router() -> Optional[ValhallaRouter]:
    """Return a lazily-built router, or ``None`` when tile data is unavailable.

    The result is memoized so callers can cheaply check availability without
    re-loading the graph on every request.
    """
    global _router, _router_resolved
    if not _router_resolved:
        _router_resolved = True
        try:
            _router = ValhallaRouter()
        except Exception as exc:  # noqa: BLE001 - any load failure => unavailable
            logger.warning("Valhalla routing unavailable: %s", exc)
            _router = None
    return _router
