from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class ConversationMessage:
    id: str
    role: Role
    content: str
    created_at: datetime | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadContext:
    thread_id: str
    summary: str
    recent_messages: list[ConversationMessage]
    message_count: int


@dataclass(slots=True)
class ThreadRecord:
    id: str
    summary: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    messages: list[ConversationMessage] = field(default_factory=list)


@dataclass(slots=True)
class UsageStats:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class ModelChunk:
    delta: str = ""
    usage: UsageStats | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class AnalyticsEvent:
    event_type: str
    thread_id: str
    run_id: str
    trace_id: str
    payload: dict[str, Any]
    step_name: str | None = None
    message_id: str | None = None
    latency_ms: float | None = None
    usage: UsageStats | None = None
    error_code: str | None = None


class ThreadRepository(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def init_schema(self) -> None: ...

    async def ping(self) -> bool: ...

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> ThreadRecord: ...

    async def get_thread(self, thread_id: str, limit: int = 50) -> ThreadRecord | None: ...

    async def get_context(self, thread_id: str, limit: int) -> ThreadContext | None: ...

    async def list_messages(self, thread_id: str) -> list[ConversationMessage]: ...

    async def add_message(
        self,
        thread_id: str,
        role: Role,
        content: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage: ...

    async def update_summary(self, thread_id: str, summary: str) -> None: ...

    async def save_checkpoint(self, thread_id: str, run_id: str, state: dict[str, Any]) -> None: ...


class AnalyticsSink(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def init_schema(self) -> None: ...

    async def ping(self) -> bool: ...

    async def write_event(self, event: AnalyticsEvent) -> None: ...


class ModelClient(Protocol):
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ): ...

    async def summarize_context(
        self,
        existing_summary: str,
        messages: list[ConversationMessage],
    ) -> str: ...
