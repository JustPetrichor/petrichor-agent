from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import clickhouse_connect

from app.config import Settings
from app.types import AnalyticsEvent

CLICKHOUSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_events (
    timestamp DateTime64(3),
    event_id String,
    run_id String,
    thread_id String,
    trace_id String,
    event_type LowCardinality(String),
    step_name Nullable(String),
    message_id Nullable(String),
    payload String,
    latency_ms Nullable(Float64),
    prompt_tokens Nullable(Int64),
    completion_tokens Nullable(Int64),
    total_tokens Nullable(Int64),
    error_code Nullable(String)
) ENGINE = MergeTree
ORDER BY (timestamp, run_id, event_type);
"""


class ClickHouseAnalyticsSink:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = await asyncio.to_thread(
            clickhouse_connect.get_client,
            host=self._settings.clickhouse_host,
            port=self._settings.clickhouse_port,
            username=self._settings.clickhouse_username,
            password=self._settings.clickhouse_password,
            database=self._settings.clickhouse_database,
        )

    async def close(self) -> None:
        if self._client is None:
            return
        await asyncio.to_thread(self._client.close)
        self._client = None

    async def init_schema(self) -> None:
        client = self._require_client()
        await asyncio.to_thread(client.command, CLICKHOUSE_SCHEMA)

    async def ping(self) -> bool:
        client = self._require_client()
        result = await asyncio.to_thread(client.command, "SELECT 1")
        return str(result).strip() == "1"

    async def write_event(self, event: AnalyticsEvent) -> None:
        client = self._require_client()
        usage = event.usage or None
        row = [
            datetime.now(UTC),
            f"{event.run_id}:{event.event_type}:{event.payload.get('timestamp')}",
            event.run_id,
            event.thread_id,
            event.trace_id,
            event.event_type,
            event.step_name,
            event.message_id,
            json.dumps(event.payload, default=str),
            event.latency_ms,
            None if usage is None else usage.prompt_tokens,
            None if usage is None else usage.completion_tokens,
            None if usage is None else usage.total_tokens,
            event.error_code,
        ]
        await asyncio.to_thread(
            client.insert,
            "run_events",
            [row],
            column_names=[
                "timestamp",
                "event_id",
                "run_id",
                "thread_id",
                "trace_id",
                "event_type",
                "step_name",
                "message_id",
                "payload",
                "latency_ms",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "error_code",
            ],
        )

    def _require_client(self):
        if self._client is None:
            raise RuntimeError("ClickHouse client has not been initialized.")
        return self._client
