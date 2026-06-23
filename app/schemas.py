from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateThreadRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamRunRequest(BaseModel):
    user_message: str = Field(min_length=1)
    client_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadResponse(BaseModel):
    thread_id: str
    summary: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    messages: list[ThreadMessageResponse] = Field(default_factory=list)


class DependencyHealth(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    ok: bool
    postgres: DependencyHealth
    clickhouse: DependencyHealth
