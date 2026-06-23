from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    thread_id: str
    run_id: str
    user_message: str
    metadata: dict[str, Any]
    summary: str
    recent_messages: list[dict[str, str]]
    message_count: int
    prompt_messages: list[dict[str, str]]
    assistant_message_id: str
    assistant_response: str
    usage: dict[str, int | None]
    model_latency_ms: float
    trace_id: str
    publisher: Any


def serialize_checkpoint(state: AgentState) -> dict[str, Any]:
    return {
        "thread_id": state["thread_id"],
        "run_id": state["run_id"],
        "summary": state.get("summary", ""),
        "message_count": state.get("message_count", 0),
        "prompt_messages": state.get("prompt_messages", []),
        "assistant_message_id": state.get("assistant_message_id"),
        "assistant_response": state.get("assistant_response", ""),
        "usage": state.get("usage", {}),
        "model_latency_ms": state.get("model_latency_ms"),
        "trace_id": state.get("trace_id"),
    }
