"""Tests for the Valhalla routing adapter (ticket 03).

Unit tests cover request building and response parsing without any tile data.
The integration tests exercise a real route against the locally built Monaco
tiles and are skipped when no tile data is present.
"""

from pathlib import Path

import pytest

from rideflow.models import Point
from rideflow.planner import compute_route
from rideflow.routing import (
    RoutingUnavailableError,
    ValhallaRouter,
    build_route_request,
    climb_descent_from_heights,
    get_router,
    route_from_response,
)

# Monaco points: from the sea-level port up to the highest part of Monaco, so a
# real route carries real distance and climb.
MONACO_ORIGIN = Point(name="Port Hercule", lon=7.4246, lat=43.7309)
MONACO_DESTINATION = Point(name="Chemin des Revoires", lon=7.4130, lat=43.7326)

# Resolve the router once at collection time; integration tests need it.
_router = get_router()
needs_tiles = pytest.mark.skipif(
    _router is None, reason="Valhalla tiles not available (build them first)"
)


# --- pure helpers ---------------------------------------------------------


def test_build_route_request_shape():
    request = build_route_request(
        Point(name="A", lon=8.0, lat=49.0), Point(name="B", lon=9.0, lat=50.0)
    )

    assert request["locations"] == [
        {"lat": 49.0, "lon": 8.0, "type": "break"},
        {"lat": 50.0, "lon": 9.0, "type": "break"},
    ]
    assert request["costing"] == "bicycle"
    assert request["costing_options"]["bicycle"]["bicycle_type"] == "hybrid"
    assert request["directions_options"]["units"] == "kilometers"
    assert request["elevation_interval"] == 30.0


def test_climb_descent_from_heights():
    climb, descent = climb_descent_from_heights([10.0, 12.0, 11.5, 14.0])
    assert climb == pytest.approx(2.0 + 2.5)  # +2 then +2.5
    assert descent == pytest.approx(0.5)  # -0.5


def test_climb_descent_skips_no_data_sentinel():
    assert climb_descent_from_heights([-500.0, -500.0, -500.0]) == (0.0, 0.0)
    assert climb_descent_from_heights([10.0, -500.0, 12.0]) == (0.0, 0.0)


def test_route_from_response_parses_trip():
    response = {
        "trip": {
            "summary": {"length": 2.843, "time": 590.645},
            "legs": [
                {
                    "shape": "encoded-polyline",
                    "elevation": [49.4, 51.8, 54.5, 53.0],
                    "maneuvers": [{"length": 0.1}],
                }
            ],
        }
    }

    route = route_from_response(response)

    assert route.distance_km == pytest.approx(2.843)
    assert route.geometry == "encoded-polyline"
    assert route.climb_m == pytest.approx(2.4 + 2.7)
    assert route.descent_m == pytest.approx(1.5)
    # Valhalla's route action does not report per-edge surfaces.
    assert route.surface_breakdown == {}


def test_route_from_response_without_elevation_zeroes_climb():
    response = {"trip": {"summary": {"length": 1.0}, "legs": [{"shape": "x"}]}}
    route = route_from_response(response)
    assert route.climb_m == 0.0
    assert route.descent_m == 0.0
    assert route.distance_km == pytest.approx(1.0)


def test_router_requires_existing_tile_dir():
    with pytest.raises(RoutingUnavailableError):
        ValhallaRouter(Path("/definitely/not/a/real/tile/dir"))


def test_compute_route_falls_back_to_straight_line_when_unroutable():
    # Ocean points can never route; the planner must fall back to the explicit
    # straight-line estimate instead of raising.
    route = compute_route(
        Point(name="ocean-1", lon=0.0, lat=0.0),
        Point(name="ocean-2", lon=2.0, lat=0.0),
    )
    assert route.distance_km > 0
    assert route.climb_m == 0.0
    assert route.descent_m == 0.0
    # Fallback geometry is the ";lon,lat" straight-line format, not a Valhalla
    # encoded polyline.
    assert ";" in route.geometry


# --- integration (require built tiles) ------------------------------------


def _raw_valhalla_response(origin: Point, destination: Point) -> dict:
    import valhalla

    from rideflow.routing import default_tiles_dir

    config = valhalla.get_config(tile_extract="", tile_dir=str(default_tiles_dir()))
    actor = valhalla.Actor(config)
    return actor.route(build_route_request(origin, destination))


@needs_tiles
def test_real_route_matches_raw_valhalla_numbers():
    raw = _raw_valhalla_response(MONACO_ORIGIN, MONACO_DESTINATION)
    trip = raw["trip"]
    leg = trip["legs"][0]

    route = ValhallaRouter().route(MONACO_ORIGIN, MONACO_DESTINATION)

    # Distance and geometry are passed through untouched.
    assert route.distance_km == pytest.approx(trip["summary"]["length"], rel=1e-6)
    assert route.geometry == leg["shape"]

    # Climb/descent are recomputed independently here and must match.
    heights = [h for h in leg.get("elevation", []) if h > -400]
    expected_climb = 0.0
    expected_descent = 0.0
    previous = None
    for height in heights:
        if previous is not None:
            delta = height - previous
            if delta > 0:
                expected_climb += delta
            else:
                expected_descent += -delta
        previous = height
    assert route.climb_m == pytest.approx(expected_climb, abs=1e-3)
    assert route.descent_m == pytest.approx(expected_descent, abs=1e-3)


@needs_tiles
def test_compute_route_uses_real_valhalla_when_tiles_present():
    route = compute_route(MONACO_ORIGIN, MONACO_DESTINATION)

    assert route.distance_km > 0
    # Real Valhalla geometry is an encoded polyline (no fallback ";" separator).
    assert route.geometry and ";" not in route.geometry
    # Monaco is hilly and the tiles were built with elevation data.
    assert route.climb_m > 0
    assert route.descent_m >= 0


@needs_tiles
def test_real_route_flows_through_plan_trip():
    from rideflow.planner import plan_trip

    plan = plan_trip(MONACO_ORIGIN, MONACO_DESTINATION, days=3, target_daily_km=10.0)

    assert len(plan.stages) == 3
    assert plan.stages[0].start == MONACO_ORIGIN
    assert plan.stages[-1].end == MONACO_DESTINATION
    for i in range(2):
        assert plan.stages[i].end == plan.stages[i + 1].start

    total_km = sum(s.route.distance_km for s in plan.stages)
    assert total_km > 0
    # Real climb flows through into the stages.
    assert plan.stages[0].route.climb_m > 0
