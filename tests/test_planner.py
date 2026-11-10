import pytest

from rideflow.models import Point
from rideflow.planner import compute_route, materialize, segment_route


def test_segment_route_splits_into_chained_equal_stages():
    origin = Point(name="A", lon=0.0, lat=0.0)
    destination = Point(name="B", lon=2.0, lat=0.0)
    route = compute_route(origin, destination)

    stages = segment_route(route, origin, destination, days=4)

    assert [s.day for s in stages] == [1, 2, 3, 4]
    assert stages[0].start == origin
    assert stages[-1].end == destination
    for i in range(3):
        assert stages[i].end == stages[i + 1].start

    # numbers come from the route, split evenly — not recomputed
    assert sum(s.route.distance_km for s in stages) == pytest.approx(
        route.distance_km, rel=1e-3
    )
    for s in stages:
        assert s.route.distance_km == pytest.approx(route.distance_km / 4, rel=1e-3)
        assert s.route.climb_m == route.climb_m


def test_materialize_preserves_tool_numbers():
    origin = Point(name="A", lon=0.0, lat=0.0)
    destination = Point(name="B", lon=1.0, lat=0.0)
    route = compute_route(origin, destination)
    stages = segment_route(route, origin, destination, days=2)

    plan = materialize(origin, destination, 2, 50.0, stages)

    # numbers are exactly the tool's, never recomputed or fabricated
    assert sum(s.route.distance_km for s in plan.stages) == pytest.approx(
        route.distance_km, rel=1e-3
    )
    assert all(s.route.climb_m == route.climb_m for s in plan.stages)

    # intent carries the request through
    assert plan.intent.parsed.origin == "A"
    assert plan.intent.parsed.destination == "B"
    assert plan.intent.parsed.days == 2
    assert plan.intent.parsed.target_daily_km == 50.0
