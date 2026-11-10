"""FastAPI application factory."""

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from rideflow.agent import (
    build_agent,
    build_chat_response,
    create_deepseek_llm,
    deserialize_messages,
    initial_state,
)
from rideflow.db import Database
from rideflow.models import Plan
from rideflow.planner import PlanningRequest, plan_trip

_UNSET = object()


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)
    stream: bool = False


def create_app(db_path: str = "rideflow.db", agent=_UNSET) -> FastAPI:
    db = Database(db_path)

    if agent is _UNSET:
        try:
            agent = build_agent(create_deepseek_llm())
        except ValueError:
            # LLM_API_KEY not configured yet; /chat reports 503.
            agent = None

    app = FastAPI(title="Rideflow")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/plans", status_code=201)
    def create_plan(plan: Plan):
        db.put(plan.model_dump(mode="json"))
        return {"id": plan.id}

    @app.post("/plans/generate")
    def generate_plan(request: PlanningRequest):
        plan = plan_trip(
            request.origin, request.destination, request.days, request.target_daily_km
        )
        return plan.model_dump(mode="json")

    @app.get("/plans/{plan_id}")
    def get_plan(plan_id: str):
        data = db.get(plan_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        return data

    @app.post("/chat")
    def chat(request: ChatRequest):
        if agent is None:
            raise HTTPException(
                status_code=503,
                detail="LLM API key not configured (set LLM_API_KEY or a .env file)",
            )
        try:
            history = deserialize_messages(request.history)
        except Exception as exc:  # noqa: BLE001 - malformed client history
            raise HTTPException(status_code=422, detail=f"Invalid history: {exc}") from exc
        messages = history + [HumanMessage(content=request.message)]

        if request.stream:
            return StreamingResponse(
                _sse_progress(agent, messages), media_type="text/event-stream"
            )

        state = agent.invoke(initial_state(messages))
        return build_chat_response(state)

    return app


def _sse_progress(agent, messages):
    last_status = None
    final_state = None
    for state in agent.stream(initial_state(messages), stream_mode="values"):
        final_state = state
        status = state.get("status")
        if status and status != last_status:
            last_status = status
            yield f"data: {json.dumps({'event': 'progress', 'message': status}, ensure_ascii=False)}\n\n"
    if final_state is None:
        yield f"data: {json.dumps({'event': 'error', 'message': 'no result'}, ensure_ascii=False)}\n\n"
        return
    done = {"event": "done", **build_chat_response(final_state)}
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"


app = create_app()
