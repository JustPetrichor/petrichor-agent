from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.observability import get_tracer
from app.services.runner import AgentRunner
from app.types import (
    AnalyticsEvent,
    ConversationMessage,
    ModelChunk,
    ThreadContext,
    ThreadRecord,
    UsageStats,
)


class InMemoryThreadStore:
    def __init__(self) -> None:
        self.threads: dict[str, ThreadRecord] = {}
        self.checkpoints: list[dict[str, Any]] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def init_schema(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> ThreadRecord:
        now = datetime.now(UTC)
        thread = ThreadRecord(
            id=str(uuid4()),
            summary="",
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
            messages=[],
        )
        self.threads[thread.id] = thread
        return thread

    async def get_thread(self, thread_id: str, limit: int = 50) -> ThreadRecord | None:
        thread = self.threads.get(thread_id)
        if thread is None:
            return None
        return ThreadRecord(
            id=thread.id,
            summary=thread.summary,
            metadata=dict(thread.metadata),
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            messages=list(thread.messages[-limit:]),
        )

    async def get_context(self, thread_id: str, limit: int) -> ThreadContext | None:
        thread = self.threads.get(thread_id)
        if thread is None:
            return None
        return ThreadContext(
            thread_id=thread.id,
            summary=thread.summary,
            recent_messages=list(thread.messages[-limit:]),
            message_count=len(thread.messages),
        )

    async def list_messages(self, thread_id: str) -> list[ConversationMessage]:
        thread = self.threads[thread_id]
        return list(thread.messages)

    async def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        thread = self.threads[thread_id]
        message = ConversationMessage(
            id=str(uuid4()),
            role=role,
            content=content,
            created_at=datetime.now(UTC),
            run_id=run_id,
            metadata=metadata or {},
        )
        thread.messages.append(message)
        thread.updated_at = datetime.now(UTC)
        return message

    async def update_summary(self, thread_id: str, summary: str) -> None:
        self.threads[thread_id].summary = summary
        self.threads[thread_id].updated_at = datetime.now(UTC)

    async def save_checkpoint(self, thread_id: str, run_id: str, state: dict[str, Any]) -> None:
        self.checkpoints.append({"thread_id": thread_id, "run_id": run_id, "state": state})


class InMemoryAnalytics:
    def __init__(self) -> None:
        self.events: list[AnalyticsEvent] = []

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def init_schema(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def write_event(self, event: AnalyticsEvent) -> None:
        self.events.append(event)


class FakeModelClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ):
        del metadata
        if self.fail:
            raise RuntimeError("model unavailable")

        user_messages = [message["content"] for message in messages if message["role"] == "user"]
        latest = user_messages[-1]
        previous = user_messages[-2] if len(user_messages) > 1 else "none"
        response = f"reply={latest}; previous={previous}"
        for part in response.split(" "):
            yield ModelChunk(delta=f"{part} ")
        yield ModelChunk(
            usage=UsageStats(prompt_tokens=12, completion_tokens=6, total_tokens=18),
            finish_reason="stop",
        )

    async def summarize_context(
        self,
        existing_summary: str,
        messages: list[ConversationMessage],
    ) -> str:
        del existing_summary
        joined = " | ".join(f"{message.role}:{message.content}" for message in messages)
        return f"summary: {joined}"


class FakeRuntime:
    def __init__(self, settings: Settings, model_client: FakeModelClient) -> None:
        self.settings = settings
        self.store = InMemoryThreadStore()
        self.analytics = InMemoryAnalytics()
        self.model_client = model_client
        self.runner = AgentRunner(
            store=self.store,
            analytics=self.analytics,
            model_client=self.model_client,
            settings=settings,
            tracer=get_tracer("tests"),
        )

    async def start(self) -> None:
        await self.store.connect()
        await self.analytics.connect()

    async def stop(self) -> None:
        await self.analytics.close()
        await self.store.close()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_enable_telemetry=False,
        summary_trigger_messages=2,
        thread_memory_window=4,
    )


async def _create_client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _collect_stream_events(client: httpx.AsyncClient, url: str, payload: dict[str, Any]):
    events = []
    async with client.stream("POST", url, json=payload) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


@pytest.mark.asyncio
async def test_stream_run_persists_memory_and_summary(test_settings: Settings) -> None:
    runtime = FakeRuntime(test_settings, FakeModelClient())
    app = create_app(runtime=runtime, settings=test_settings)

    async with await _create_client(app) as client:
        create_response = await client.post("/threads", json={"metadata": {"suite": "memory"}})
        assert create_response.status_code == 200
        thread_id = create_response.json()["thread_id"]

        first_run = await _collect_stream_events(
            client,
            f"/threads/{thread_id}/runs/stream",
            {"user_message": "hello memory", "metadata": {"turn": 1}},
        )
        second_run = await _collect_stream_events(
            client,
            f"/threads/{thread_id}/runs/stream",
            {"user_message": "follow up", "metadata": {"turn": 2}},
        )

        assert first_run[0]["type"] == "RUN_STARTED"
        assert first_run[-1]["type"] == "RUN_FINISHED"
        text = "".join(
            event["delta"] for event in second_run if event["type"] == "TEXT_MESSAGE_CONTENT"
        )
        assert "previous=hello memory" in text

        thread_response = await client.get(f"/threads/{thread_id}")
        body = thread_response.json()
        assert len(body["messages"]) == 4
        assert body["summary"].startswith("summary:")


@pytest.mark.asyncio
async def test_analytics_capture_usage_and_lifecycle(test_settings: Settings) -> None:
    runtime = FakeRuntime(test_settings, FakeModelClient())
    app = create_app(runtime=runtime, settings=test_settings)

    async with await _create_client(app) as client:
        thread = (await client.post("/threads")).json()
        await _collect_stream_events(
            client,
            f"/threads/{thread['thread_id']}/runs/stream",
            {"user_message": "inspect analytics", "metadata": {"suite": "analytics"}},
        )

    event_types = [event.event_type for event in runtime.analytics.events]
    assert "RUN_STARTED" in event_types
    assert "TEXT_MESSAGE_END" in event_types
    assert "RUN_FINISHED" in event_types

    text_end = next(
        event
        for event in runtime.analytics.events
        if event.event_type == "TEXT_MESSAGE_END"
    )
    assert text_end.usage is not None
    assert text_end.usage.total_tokens == 18


@pytest.mark.asyncio
async def test_failure_path_emits_run_error_and_closes_stream(test_settings: Settings) -> None:
    runtime = FakeRuntime(test_settings, FakeModelClient(fail=True))
    app = create_app(runtime=runtime, settings=test_settings)

    async with await _create_client(app) as client:
        thread = (await client.post("/threads")).json()
        events = await _collect_stream_events(
            client,
            f"/threads/{thread['thread_id']}/runs/stream",
            {"user_message": "trigger failure", "metadata": {"suite": "failure"}},
        )

        assert events[-1]["type"] == "RUN_ERROR"
        assert events[-1]["message"] == "model unavailable"


@pytest.mark.asyncio
async def test_healthz_reports_dependencies(test_settings: Settings) -> None:
    runtime = FakeRuntime(test_settings, FakeModelClient())
    app = create_app(runtime=runtime, settings=test_settings)

    async with await _create_client(app) as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["ok"] is True
