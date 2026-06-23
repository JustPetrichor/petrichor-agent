from __future__ import annotations

import uuid
from time import perf_counter

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState, serialize_checkpoint
from app.config import Settings
from app.types import ModelClient, ThreadRepository, UsageStats


def build_agent_graph(
    *,
    store: ThreadRepository,
    model_client: ModelClient,
    settings: Settings,
):
    graph = StateGraph(AgentState)

    async def load_context(state: AgentState) -> AgentState:
        publisher = state["publisher"]
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
        }

    async def build_prompt(state: AgentState) -> AgentState:
        publisher = state["publisher"]
        await publisher.step_started("build_prompt")
        prompt_messages: list[dict[str, str]] = [
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
        publisher = state["publisher"]
        assistant_message_id = str(uuid.uuid4())
        await publisher.step_started("call_model")
        await publisher.text_message_start(assistant_message_id)

        start = perf_counter()
        usage = UsageStats()
        response_parts: list[str] = []
        async for chunk in model_client.stream_chat(
            state["prompt_messages"],
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
        await publisher.step_finished("call_model")
        return {
            "assistant_message_id": assistant_message_id,
            "assistant_response": "".join(response_parts).strip(),
            "usage": usage.as_dict(),
            "model_latency_ms": latency_ms,
        }

    async def persist_state(state: AgentState) -> AgentState:
        publisher = state["publisher"]
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
            messages_for_summary = all_messages[:-settings.thread_memory_window] or all_messages
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
    graph.add_node("persist_state", persist_state)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "build_prompt")
    graph.add_edge("build_prompt", "call_model")
    graph.add_edge("call_model", "persist_state")
    graph.add_edge("persist_state", END)

    return graph.compile()
