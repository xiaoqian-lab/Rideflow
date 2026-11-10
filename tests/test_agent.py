"""Tests for the LangGraph agent (ticket 04).

The LLM is a deterministic fake that returns scripted tool calls; the routing
tools are fakes too, so these tests never touch DeepSeek, Nominatim, or
Valhalla. They pin the two invariants from the ticket:

1. The agent asks only for missing intent fields (never re-asks given ones).
2. Every number in the final Plan comes from the deterministic tools, not the
   LLM.
"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from rideflow.agent import Toolset, build_agent, run_turn
from rideflow.main import create_app
from rideflow.models import Point, Route, Stage

ORIGIN = Point(name="美因茨", lon=8.2736, lat=49.9994)
DESTINATION = Point(name="科隆", lon=6.9603, lat=50.9375)


def _tool_call(args: dict, call_id: str = "call_1") -> dict:
    return {"name": "submit_intent", "args": args, "id": call_id, "type": "tool_call"}


def _fake_toolset():
    route = Route(
        geometry="stub",
        distance_km=123.456,
        climb_m=55.5,
        descent_m=10.0,
        surface_breakdown={"paved": 1.0, "gravel": 0.0},
    )

    def fake_geocode(name: str) -> Point:
        return {"美因茨": ORIGIN, "科隆": DESTINATION}[name]

    def fake_compute_route(origin: Point, destination: Point) -> Route:
        assert origin == ORIGIN
        assert destination == DESTINATION
        return route

    def fake_segment_route(
        r: Route, origin: Point, destination: Point, days: int
    ) -> list[Stage]:
        per_day = r.distance_km / days
        return [
            Stage(
                day=i + 1,
                start=origin,
                end=destination,
                route=Route(
                    geometry="seg",
                    distance_km=per_day,
                    climb_m=r.climb_m,
                    descent_m=r.descent_m,
                    surface_breakdown=r.surface_breakdown,
                ),
            )
            for i in range(days)
        ]

    return Toolset(
        geocode=fake_geocode,
        compute_route=fake_compute_route,
        segment_route=fake_segment_route,
    )


def _full_llm() -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        {
                            "origin": "美因茨",
                            "destination": "科隆",
                            "days": 3,
                            "target_daily_km": 70.0,
                        }
                    )
                ],
            )
        ]
    )


def test_agent_asks_only_for_missing_fields_and_not_given_ones():
    llm = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call({"origin": "美因茨", "destination": "科隆"})
                ],
            )
        ]
    )
    agent = build_agent(llm, _fake_toolset())

    state = run_turn(agent, [HumanMessage(content="从美因茨骑到科隆")])

    question = state["question"]
    assert question is not None
    # asks for the two missing fields...
    assert "骑行天数" in question
    assert "日均里程" in question
    # ...and never re-asks the fields the user already gave
    assert "起点" not in question
    assert "终点" not in question
    # no plan yet
    assert state["plan"] is None


def test_agent_plan_numbers_come_from_tools_not_the_llm():
    agent = build_agent(_full_llm(), _fake_toolset())

    state = run_turn(
        agent, [HumanMessage(content="从美因茨骑到科隆，3 天，每天 70km")]
    )

    plan = state["plan"]
    assert plan is not None

    # intent carries the LLM's *decisions* through
    assert plan["intent"]["parsed"] == {
        "origin": "美因茨",
        "destination": "科隆",
        "days": 3,
        "target_daily_km": 70.0,
    }

    # every number is the fake tool's output, not something the LLM made up
    assert len(plan["stages"]) == 3
    assert sum(s["route"]["distance_km"] for s in plan["stages"]) == pytest.approx(
        123.456
    )
    assert all(s["route"]["climb_m"] == 55.5 for s in plan["stages"])


def test_agent_completes_across_two_turns():
    llm = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call({"origin": "美因茨", "destination": "科隆"})
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        {
                            "origin": "美因茨",
                            "destination": "科隆",
                            "days": 3,
                            "target_daily_km": 70.0,
                        }
                    )
                ],
            ),
        ]
    )
    agent = build_agent(llm, _fake_toolset())

    first = run_turn(agent, [HumanMessage(content="从美因茨骑到科隆")])
    assert first["plan"] is None
    assert first["question"] is not None

    second = run_turn(
        agent, first["messages"] + [HumanMessage(content="3 天，每天 70km")]
    )
    assert second["plan"] is not None
    assert second["plan"]["intent"]["parsed"]["days"] == 3


def test_chat_endpoint_returns_plan(tmp_path):
    client = TestClient(create_app(str(tmp_path / "rideflow.db"), agent=build_agent(_full_llm(), _fake_toolset())))

    resp = client.post("/chat", json={"message": "从美因茨骑到科隆，3 天，每天 70km"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] is True
    assert body["plan"]["intent"]["parsed"]["days"] == 3
    assert len(body["plan"]["stages"]) == 3
    # reply is a human-readable summary
    assert body["reply"]


def test_chat_endpoint_asks_for_missing_fields(tmp_path):
    llm = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[_tool_call({"origin": "美因茨", "destination": "科隆"})],
            )
        ]
    )
    client = TestClient(create_app(str(tmp_path / "rideflow.db"), agent=build_agent(llm, _fake_toolset())))

    resp = client.post("/chat", json={"message": "从美因茨骑到科隆"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] is False
    assert body["plan"] is None
    assert "骑行天数" in body["reply"]
    assert "起点" not in body["reply"]


def test_chat_endpoint_streams_progress(tmp_path):
    client = TestClient(create_app(str(tmp_path / "rideflow.db"), agent=build_agent(_full_llm(), _fake_toolset())))

    resp = client.post(
        "/chat",
        json={"message": "从美因茨骑到科隆，3 天，每天 70km", "stream": True},
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "progress" in body
    assert "done" in body


def test_chat_without_api_key_returns_503(tmp_path):
    # Inject agent=None to exercise the "no agent configured" path explicitly,
    # independent of whether a real key happens to be present in .env.
    client = TestClient(create_app(str(tmp_path / "rideflow.db"), agent=None))

    resp = client.post("/chat", json={"message": "你好"})

    assert resp.status_code == 503
