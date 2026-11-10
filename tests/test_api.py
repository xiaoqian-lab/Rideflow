from fastapi.testclient import TestClient

from rideflow.main import create_app


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "rideflow.db")))


def test_health(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_read_plan_roundtrip(tmp_path):
    client = make_client(tmp_path)
    plan = {
        "id": "plan-001",
        "intent": {
            "raw": "从美因茨骑到科隆，3 天，每天 70km",
            "parsed": {
                "origin": "美因茨",
                "destination": "科隆",
                "days": 3,
                "target_daily_km": 70.0,
            },
        },
        "stages": [
            {
                "day": 1,
                "start": {"name": "美因茨", "lon": 8.2736, "lat": 49.9994},
                "end": {"name": "科布伦茨", "lon": 7.5944, "lat": 50.3533},
                "route": {
                    "geometry": "encoded-polyline-1",
                    "distance_km": 96.4,
                    "climb_m": 320.0,
                    "descent_m": 310.0,
                    "surface_breakdown": {"paved": 0.95, "gravel": 0.05},
                },
                "via": [],
                "poi_refs": [],
                "notes": "沿莱茵河左岸",
                "status": "draft",
            }
        ],
        "metadata": {
            "model": "deepseek-flash",
            "created_at": "2026-11-10T00:00:00Z",
            "version": 1,
        },
    }

    resp = client.post("/plans", json=plan)
    assert resp.status_code == 201
    assert resp.json() == {"id": "plan-001"}

    got = client.get("/plans/plan-001")
    assert got.status_code == 200
    assert got.json() == plan


def test_get_missing_plan_returns_404(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/plans/does-not-exist").status_code == 404


def test_invalid_plan_is_rejected(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/plans", json={"id": "x"})
    assert resp.status_code == 422


def test_generate_plan_splits_into_days(tmp_path):
    client = make_client(tmp_path)
    request = {
        "origin": {"name": "美因茨", "lon": 8.2736, "lat": 49.9994},
        "destination": {"name": "科隆", "lon": 6.9603, "lat": 50.9375},
        "days": 3,
        "target_daily_km": 70.0,
    }
    resp = client.post("/plans/generate", json=request)
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["intent"]["parsed"]["days"] == 3
    assert len(plan["stages"]) == 3
    assert plan["stages"][0]["start"]["name"] == "美因茨"
    assert plan["stages"][-1]["end"]["name"] == "科隆"
    for i in range(2):
        assert plan["stages"][i]["end"] == plan["stages"][i + 1]["start"]
    for stage in plan["stages"]:
        assert stage["route"]["distance_km"] > 0
        assert stage["route"]["geometry"]
        # climb/descent now come from the routing engine: non-negative, and
        # zero only when the route falls back to a straight-line estimate.
        assert stage["route"]["climb_m"] >= 0
        assert stage["route"]["descent_m"] >= 0
