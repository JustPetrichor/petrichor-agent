from __future__ import annotations

import json
import uuid
from time import perf_counter

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState, serialize_checkpoint
from app.config import Settings
from app.services.agui import EventPublisher
from app.types import (
    ModelClient,
    ThreadRepository,
    ToolCallRequest,
    ToolRegistry,
    UsageStats,
)


def build_agent_graph(
    *,
    store: ThreadRepository,
    model_client: ModelClient,
    tool_registry: ToolRegistry,
    settings: Settings,
    publisher: EventPublisher,
):
    graph = StateGraph(AgentState)

    async def stream_assistant_response(
        state: AgentState,
        prompt_messages: list[dict[str, object]],
    ) -> AgentState:
        assistant_message_id = str(uuid.uuid4())
        await publisher.text_message_start(assistant_message_id)

        start = perf_counter()
        usage = UsageStats()
        response_parts: list[str] = []
        async for chunk in model_client.stream_chat(
            prompt_messages,
            metadata={
                "thread_id": state["thread_id"],
                "run_id": state["run_id"],
                "trace_id": state["trace_id"],
            },
        ):
            if chunk.delta:
                response_parts.append(chunk.delta)
                await publisher.text_message_content(assistant_message_id, chunk.delta)
            if chunk.usage is not None:
                usage = chunk.usage

        latency_ms = (perf_counter() - start) * 1000
        await publisher.text_message_end(
            assistant_message_id,
            usage=usage,
            latency_ms=latency_ms,
        )
        return {
            "assistant_message_id": assistant_message_id,
            "assistant_response": "".join(response_parts).strip(),
            "usage": usage.as_dict(),
            "model_latency_ms": latency_ms,
            "prompt_messages": prompt_messages,
            "pending_tool_calls": [],
        }

    async def publish_final_response(
        content: str,
        usage: UsageStats,
        latency_ms: float,
    ) -> AgentState:
        assistant_message_id = str(uuid.uuid4())
        await publisher.text_message_start(assistant_message_id)
        if content:
            await publisher.text_message_content(assistant_message_id, content)
        await publisher.text_message_end(
            assistant_message_id,
            usage=usage,
            latency_ms=latency_ms,
        )
        return {
            "assistant_message_id": assistant_message_id,
            "assistant_response": content.strip(),
            "usage": usage.as_dict(),
            "model_latency_ms": latency_ms,
        }

    async def load_context(state: AgentState) -> AgentState:
        await publisher.step_started("load_context")
        context = await store.get_context(state["thread_id"], settings.thread_memory_window)
        if context is None:
            raise ValueError(f"Unknown thread_id: {state['thread_id']}")
        await publisher.step_finished("load_context")
        return {
            "summary": context.summary,
            "recent_messages": [
                {"role": message.role, "content": message.content}
                for message in context.recent_messages
            ],
            "message_count": context.message_count,
            "tool_roundtrip_count": 0,
            "pending_tool_calls": [],
        }

    async def build_prompt(state: AgentState) -> AgentState:
        await publisher.step_started("build_prompt")
        prompt_messages: list[dict[str, object]] = [
            {"role": "system", "content": settings.prompt_system_message}
        ]
        if state.get("summary"):
            prompt_messages.append(
                {
                    "role": "system",
                    "content": f"Conversation summary:\n{state['summary']}",
                }
            )
        prompt_messages.extend(state.get("recent_messages", []))
        await publisher.step_finished("build_prompt")
        return {"prompt_messages": prompt_messages}

    async def call_model(state: AgentState) -> AgentState:
        prompt_messages = list(state["prompt_messages"])
        tool_schemas = tool_registry.get_tool_schemas()

        if not (settings.model_tool_calling_enabled and tool_schemas):
            await publisher.step_started("call_model")
            result = await stream_assistant_response(state, prompt_messages)
            await publisher.step_finished("call_model")
            return result

        await publisher.step_started("call_model")
        start = perf_counter()
        turn = await model_client.complete_chat(
            prompt_messages,
            metadata={
                "thread_id": state["thread_id"],
                "run_id": state["run_id"],
                "trace_id": state["trace_id"],
            },
            tools=tool_schemas,
            tool_choice="auto",
        )
        latency_ms = (perf_counter() - start) * 1000
        total_usage = _sum_usage(state.get("usage"), turn.usage)
        prompt_messages.append(_assistant_message_from_turn(turn))

        if turn.tool_calls:
            await publisher.step_finished("call_model")
            return {
                "prompt_messages": prompt_messages,
                "pending_tool_calls": [_serialize_tool_call(item) for item in turn.tool_calls],
                "usage": total_usage.as_dict(),
                "model_latency_ms": state.get("model_latency_ms", 0.0) + latency_ms,
            }

        result = await publish_final_response(
            turn.content,
            total_usage,
            state.get("model_latency_ms", 0.0) + latency_ms,
        )
        result["prompt_messages"] = prompt_messages
        result["pending_tool_calls"] = []
        await publisher.step_finished("call_model")
        return result

    async def execute_tools(state: AgentState) -> AgentState:
        pending = [_deserialize_tool_call(item) for item in state.get("pending_tool_calls", [])]
        if not pending:
            return {}

        roundtrip_count = state.get("tool_roundtrip_count", 0) + 1
        if roundtrip_count > settings.mcp_max_tool_roundtrips:
            raise RuntimeError("Maximum MCP tool roundtrips exceeded.")

        await publisher.step_started("execute_tools")
        prompt_messages = list(state["prompt_messages"])
        for tool_call in pending:
            result = await tool_registry.call_tool(tool_call.name, tool_call.arguments)
            prompt_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": result.content,
                }
            )
        await publisher.step_finished("execute_tools")
        return {
            "prompt_messages": prompt_messages,
            "pending_tool_calls": [],
            "tool_roundtrip_count": roundtrip_count,
        }

    async def persist_state(state: AgentState) -> AgentState:
        await publisher.step_started("persist_state")

        await store.add_message(
            state["thread_id"],
            "assistant",
            state.get("assistant_response", ""),
            run_id=state["run_id"],
            metadata={"message_id": state["assistant_message_id"]},
        )

        updated_summary = state.get("summary", "")
        total_messages = state.get("message_count", 0) + 1
        all_messages = await store.list_messages(state["thread_id"])
        if total_messages >= settings.summary_trigger_messages:
            messages_for_summary = all_messages[: -settings.thread_memory_window] or all_messages
            if messages_for_summary:
                updated_summary = await model_client.summarize_context(
                    state.get("summary", ""),
                    messages_for_summary,
                )
                await store.update_summary(state["thread_id"], updated_summary)

        checkpoint_state = dict(state)
        checkpoint_state["summary"] = updated_summary
        checkpoint_state["message_count"] = len(all_messages)
        await store.save_checkpoint(
            state["thread_id"],
            state["run_id"],
            serialize_checkpoint(checkpoint_state),
        )

        await publisher.step_finished("persist_state")
        return {"summary": updated_summary, "message_count": len(all_messages)}

    graph.add_node("load_context", load_context)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("persist_state", persist_state)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "build_prompt")
    graph.add_edge("build_prompt", "call_model")
    graph.add_conditional_edges(
        "call_model",
        lambda state: "execute_tools" if state.get("pending_tool_calls") else "persist_state",
        {
            "execute_tools": "execute_tools",
            "persist_state": "persist_state",
        },
    )
    graph.add_edge("execute_tools", "call_model")
    graph.add_edge("persist_state", END)

    return graph.compile()


def _assistant_message_from_turn(turn) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": turn.content or ""}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": item.id,
                "type": "function",
                "function": {
                    "name": item.name,
                    "arguments": json.dumps(item.arguments, ensure_ascii=True),
                },
            }
            for item in turn.tool_calls
        ]
    return message


def _serialize_tool_call(tool_call: ToolCallRequest) -> dict[str, object]:
    return {
        "id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


def _deserialize_tool_call(payload: dict[str, object]) -> ToolCallRequest:
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    return ToolCallRequest(
        id=str(payload["id"]),
        name=str(payload["name"]),
        arguments=arguments,
    )


def _sum_usage(
    existing: dict[str, int | None] | None,
    new_usage: UsageStats | None,
) -> UsageStats:
    prior = UsageStats(
        prompt_tokens=(existing or {}).get("prompt_tokens"),
        completion_tokens=(existing or {}).get("completion_tokens"),
        total_tokens=(existing or {}).get("total_tokens"),
    )
    if new_usage is None:
        return prior

    return UsageStats(
        prompt_tokens=(prior.prompt_tokens or 0) + (new_usage.prompt_tokens or 0),
        completion_tokens=(prior.completion_tokens or 0) + (new_usage.completion_tokens or 0),
        total_tokens=(prior.total_tokens or 0) + (new_usage.total_tokens or 0),
    )
