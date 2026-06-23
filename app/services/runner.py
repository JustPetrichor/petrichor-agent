from __future__ import annotations

from opentelemetry.trace import Status, StatusCode

from app.agent.graph import build_agent_graph
from app.config import Settings
from app.services.agui import EventPublisher
from app.types import AnalyticsSink, ModelClient, ThreadRepository


class AgentRunner:
    def __init__(
        self,
        *,
        store: ThreadRepository,
        analytics: AnalyticsSink,
        model_client: ModelClient,
        settings: Settings,
        tracer,
    ) -> None:
        self._store = store
        self._analytics = analytics
        self._graph = build_agent_graph(store=store, model_client=model_client, settings=settings)
        self._tracer = tracer

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
                final_state = await self._graph.ainvoke(
                    {
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "user_message": user_message,
                        "metadata": metadata,
                        "trace_id": trace_id,
                        "publisher": publisher,
                    }
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
