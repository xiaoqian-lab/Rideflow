"""LangGraph agent (ticket 04): natural-language trip intent -> day-by-day Plan.

Boundary (from docs/wayfinder/tickets/0006-agent-toolset.md): the LLM only
*decides* — it extracts the intent fields and picks when planning is complete —
while a deterministic materializer hydrates every number (distance / climb /
geometry) from the routing tools. The LLM never fabricates a number.

The LLM's single tool is `submit_intent` (a function-type tool). Once all four
MVP fields (origin / destination / days / target_daily_km) are present, the
deterministic `build_plan` node calls `geocode` -> `compute_route` ->
`segment_route` -> `materialize` and stores the resulting `Plan`. Missing fields
trigger a deterministic clarifying question that lists *only* the missing items.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI

from rideflow.models import Plan, Point, Route, Stage
from rideflow.planner import (
    compute_route as _compute_route,
    materialize as _materialize,
    segment_route as _segment_route,
)

INTENT_FIELDS = ("origin", "destination", "days", "target_daily_km")

_FIELD_LABELS = {
    "origin": "起点",
    "destination": "终点",
    "days": "骑行天数",
    "target_daily_km": "日均里程 (km)",
}

SYSTEM_PROMPT = """你是 Rideflow 的骑行规划助手，只做决策、绝不编造数字。

你的职责：
1. 从整段对话历史里汇总行程意图字段：起点(origin)、终点(destination)、
   骑行天数(days)、目标日均里程(target_daily_km)。
2. 调用 submit_intent 工具，传入你当前能确定的所有字段（包括之前轮次已给出的）。
   无法确定的字段一律不要传。
3. 不要自己计算任何距离、爬升或几何数字——这些由系统用确定性工具计算。
4. 信息不全时不要自己追问，调用 submit_intent 后系统会自动只追问缺失项。
5. 不要编造、复述或猜测任何数字。"""

# DeepSeek-friendly function-type tool schema. All properties are optional; the
# model omits the fields it cannot determine instead of passing null.
SUBMIT_INTENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_intent",
        "description": (
            "记录骑行意图中已确定的字段。只传入能确定的字段，无法确定的字段完全省略。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "起点地名"},
                "destination": {"type": "string", "description": "终点地名"},
                "days": {"type": "integer", "description": "骑行天数"},
                "target_daily_km": {
                    "type": "number",
                    "description": "目标日均里程，单位 km",
                },
            },
        },
    },
}


def geocode(name: str) -> Point:
    """Resolve a place name to a Point via Nominatim (deterministic, external).

    Inject a fake in tests so agent tests never hit the network.
    """
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(
        {"q": name, "format": "json", "limit": 1}
    )
    request = Request(
        url, headers={"User-Agent": "rideflow/0.1 (personal local cycling planner)"}
    )
    with urlopen(request, timeout=10) as response:
        results = json.loads(response.read().decode("utf-8"))
    if not results:
        raise ValueError(f"无法定位地点: {name}")
    return Point(name=name, lon=float(results[0]["lon"]), lat=float(results[0]["lat"]))


@dataclass
class Toolset:
    """Deterministic tools the agent orchestrates. All are injectable in tests."""

    geocode: Callable[[str], Point] = geocode
    compute_route: Callable[[Point, Point], Route] = _compute_route
    segment_route: Callable[[Route, Point, Point, int], list[Stage]] = _segment_route
    materialize: Callable[..., Plan] = _materialize


def _coerce(field: str, value: Any) -> Any:
    if field == "days":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field == "target_daily_km":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def reconstruct_intent(messages: list[AnyMessage]) -> dict[str, Any]:
    """Deterministically rebuild the intent from every submit_intent tool call.

    Later calls win, so a turn that re-states the full intent is idempotent.
    """
    intent: dict[str, Any] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if call.get("name") != "submit_intent":
                continue
            args = call.get("args") or {}
            for field in INTENT_FIELDS:
                if field in args and args[field] is not None:
                    intent[field] = _coerce(field, args[field])
    return intent


def intent_complete(intent: dict[str, Any]) -> bool:
    return all(intent.get(field) for field in INTENT_FIELDS)


def missing_question(intent: dict[str, Any]) -> str:
    missing = [_FIELD_LABELS[f] for f in INTENT_FIELDS if not intent.get(f)]
    if len(missing) == 1:
        return f"还差一个信息：{missing[0]}。"
    return "还想确认：" + "、".join(missing) + "。"


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intent: dict[str, Any]
    plan: dict[str, Any] | None
    question: str | None
    status: str


def initial_state(messages: list[AnyMessage]) -> dict[str, Any]:
    return {
        "messages": list(messages),
        "intent": {},
        "plan": None,
        "question": None,
        "status": "开始",
    }


def build_agent(llm: BaseChatModel, toolset: Toolset | None = None):
    """Compile the LangGraph agent. `llm` must accept `bind(tools=[...])`."""
    ts = toolset or Toolset()
    llm_with_tools = llm.bind(tools=[SUBMIT_INTENT_TOOL])

    def agent_node(state: AgentState) -> dict[str, Any]:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(
            state.get("messages", [])
        )
        response = llm_with_tools.invoke(messages)
        return {"messages": [response], "status": "正在理解意图…"}

    def tools_node(state: AgentState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        new_messages: list[ToolMessage] = []
        last = messages[-1]
        calls = last.tool_calls if isinstance(last, AIMessage) else []
        for call in calls:
            args = call.get("args") or {}
            recorded = {k: args[k] for k in INTENT_FIELDS if args.get(k) is not None}
            content = json.dumps({"recorded": recorded}, ensure_ascii=False)
            new_messages.append(
                ToolMessage(content=content, tool_call_id=call.get("id", ""))
            )
        intent = reconstruct_intent(messages + new_messages)
        return {
            "messages": new_messages,
            "intent": intent,
            "status": "正在整理信息…",
        }

    def build_plan_node(state: AgentState) -> dict[str, Any]:
        intent = state["intent"]
        origin = ts.geocode(intent["origin"])
        destination = ts.geocode(intent["destination"])
        route = ts.compute_route(origin, destination)
        stages = ts.segment_route(route, origin, destination, int(intent["days"]))
        plan = ts.materialize(
            origin,
            destination,
            int(intent["days"]),
            float(intent["target_daily_km"]),
            stages,
        )
        summary = f"已生成 {len(plan.stages)} 天的骑行计划。"
        return {
            "plan": plan.model_dump(mode="json"),
            "question": None,
            "messages": [AIMessage(content=summary)],
            "status": "计划已生成",
        }

    def ask_node(state: AgentState) -> dict[str, Any]:
        question = missing_question(state["intent"])
        return {
            "messages": [AIMessage(content=question)],
            "question": question,
            "status": "需要补充信息…",
        }

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "end"

    def route_after_tools(state: AgentState) -> str:
        if intent_complete(state.get("intent", {})):
            return "build_plan"
        return "ask"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("build_plan", build_plan_node)
    graph.add_node("ask", ask_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", route_after_agent, {"tools": "tools", "end": END}
    )
    graph.add_conditional_edges(
        "tools", route_after_tools, {"build_plan": "build_plan", "ask": "ask"}
    )
    graph.add_edge("build_plan", END)
    graph.add_edge("ask", END)
    return graph.compile()


def run_turn(agent, messages: list[AnyMessage]) -> dict[str, Any]:
    """Run one conversation turn and return the final graph state."""
    return agent.invoke(initial_state(messages))


def serialize_messages(messages: list[AnyMessage]) -> list[dict]:
    return messages_to_dict(messages)


def deserialize_messages(payload: list[dict]) -> list[AnyMessage]:
    return messages_from_dict(payload)


def build_chat_response(state: dict[str, Any]) -> dict[str, Any]:
    reply = ""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and message.content:
            reply = message.content
            break
    plan = state.get("plan")
    return {
        "reply": reply,
        "plan": plan,
        "question": state.get("question"),
        "done": plan is not None,
        "messages": serialize_messages(state.get("messages", [])),
    }


def load_env(path: str | Path = ".env") -> None:
    """Load a .env file into os.environ without overriding existing values."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_llm_api_key() -> str | None:
    load_env()
    return os.environ.get("LLM_API_KEY")


class DeepSeekChatOpenAI(ChatOpenAI):
    """ChatOpenAI tuned for DeepSeek thinking-mode tool calling.

    DeepSeek requires that every assistant message's `reasoning_content` be
    echoed back on subsequent requests whenever `tools` are present (otherwise
    the API returns 400). The base langchain-openai class drops that field, so
    we capture it on responses and re-attach it on requests.
    """

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        if isinstance(response, dict):
            response_dict = response
        else:
            response_dict = response.model_dump(warnings=False)
        choices = response_dict.get("choices") or []
        for gen, choice in zip(result.generations, choices):
            if not isinstance(choice, dict):
                continue
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None and isinstance(gen.message, AIMessage):
                gen.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload_messages = payload.get("messages")
        if not isinstance(payload_messages, list):
            return payload
        source_messages = self._convert_input(input_).to_messages()
        for i, message_dict in enumerate(payload_messages):
            if i >= len(source_messages):
                break
            source = source_messages[i]
            if (
                isinstance(source, AIMessage)
                and message_dict.get("role") == "assistant"
            ):
                reasoning = source.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    message_dict["reasoning_content"] = reasoning
        return payload


def create_deepseek_llm(api_key: str | None = None) -> DeepSeekChatOpenAI:
    key = api_key or get_llm_api_key()
    if not key:
        raise ValueError(
            "LLM_API_KEY is not set. Set it in the environment or a .env file."
        )
    return DeepSeekChatOpenAI(
        model=os.environ.get("LLM_MODEL_NAME", "deepseek-flash"),
        api_key=key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        # Thinking mode stays on (DeepSeek default). Never set tool_choice to
        # "required" or a named tool — thinking mode only supports auto/none.
        extra_body={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "user_id": "rideflow-single-user",
        },
    )
