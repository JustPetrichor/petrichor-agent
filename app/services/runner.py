from __future__ import annotations

from contextlib import nullcontext

from langfuse import propagate_attributes
from opentelemetry.trace import Status, StatusCode

from app.agent.graph import build_agent_graph
from app.config import Settings
from app.services.agui import EventPublisher
from app.types import AnalyticsSink, ModelClient, ThreadRepository, ToolRegistry


class AgentRunner:
    def __init__(
        self,
        *,
        store: ThreadRepository,
        analytics: AnalyticsSink,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        settings: Settings,
        tracer,
        langfuse_enabled: bool = False,
        langfuse_callback_handler=None,
    ) -> None:
        self._store = store
        self._analytics = analytics
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._settings = settings
        self._tracer = tracer
        self._langfuse_enabled = langfuse_enabled
        self._langfuse_callback_handler = langfuse_callback_handler

    async def run(
        self,
        *,
        thread_id: str,
        run_id: str,
        user_message: str,
        metadata: dict,
        trace_id: str,
        publisher: EventPublisher,
    ) -> dict:
        with self._langfuse_attributes(thread_id=thread_id, run_id=run_id, metadata=metadata):
            with self._tracer.start_as_current_span(
                "agent.run",
                attributes={"thread.id": thread_id, "run.id": run_id},
            ) as span:
                await publisher.run_started(
                    {
                        "threadId": thread_id,
                        "runId": run_id,
                        "userMessage": user_message,
                        "metadata": metadata,
                    }
                )
                await self._store.add_message(
                    thread_id,
                    "user",
                    user_message,
                    run_id=run_id,
                    metadata=metadata,
                )
                try:
                    graph = build_agent_graph(
                        store=self._store,
                        model_client=self._model_client,
                        tool_registry=self._tool_registry,
                        settings=self._settings,
                        publisher=publisher,
                    )
                    final_state = await graph.ainvoke(
                        {
                            "thread_id": thread_id,
                            "run_id": run_id,
                            "user_message": user_message,
                            "metadata": metadata,
                            "trace_id": trace_id,
                        },
                        config=self._langgraph_config(
                            thread_id=thread_id,
                            run_id=run_id,
                            metadata=metadata,
                        ),
                    )
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    await publisher.run_error(str(exc), code=exc.__class__.__name__)
                    raise

                await publisher.run_finished(
                    {
                        "messageId": final_state.get("assistant_message_id"),
                        "usage": final_state.get("usage", {}),
                    }
                )
                return final_state

    def _langfuse_attributes(self, *, thread_id: str, run_id: str, metadata: dict):
        if not self._langfuse_enabled:
            return nullcontext()

        return propagate_attributes(
            session_id=thread_id,
            trace_name=f"{self._settings.app_name} agent run",
            metadata={"thread_id": thread_id, "run_id": run_id, **metadata},
            tags=["langgraph", "litellm", "ag-ui"],
        )

    def _langgraph_config(self, *, thread_id: str, run_id: str, metadata: dict) -> dict:
        config: dict = {
            "run_name": "agent-run",
            "metadata": {
                "thread_id": thread_id,
                "run_id": run_id,
                **metadata,
            },
        }
        if self._langfuse_callback_handler is not None:
            config["callbacks"] = [self._langfuse_callback_handler]
        return config
