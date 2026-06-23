from __future__ import annotations

import json
import time
from typing import Any

from app.types import AnalyticsEvent, AnalyticsSink, UsageStats


def encode_sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, default=str, separators=(",", ":"), ensure_ascii=True)
    return f"event: {event['type']}\ndata: {payload}\n\n"


class EventPublisher:
    def __init__(
        self,
        *,
        queue,
        thread_id: str,
        run_id: str,
        trace_id: str,
        analytics: AnalyticsSink,
    ) -> None:
        self._queue = queue
        self._thread_id = thread_id
        self._run_id = run_id
        self._trace_id = trace_id
        self._analytics = analytics

    async def close(self) -> None:
        await self._queue.put(None)

    async def run_started(self, input_payload: dict[str, Any]) -> None:
        event = {
            "type": "RUN_STARTED",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "input": input_payload,
            "traceId": self._trace_id,
        }
        await self._emit(event, persist=True)

    async def step_started(self, step_name: str) -> None:
        event = {
            "type": "STEP_STARTED",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "stepName": step_name,
            "traceId": self._trace_id,
        }
        await self._emit(event, persist=True, step_name=step_name)

    async def step_finished(self, step_name: str) -> None:
        event = {
            "type": "STEP_FINISHED",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "stepName": step_name,
            "traceId": self._trace_id,
        }
        await self._emit(event, persist=True, step_name=step_name)

    async def text_message_start(self, message_id: str) -> None:
        event = {
            "type": "TEXT_MESSAGE_START",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "messageId": message_id,
            "role": "assistant",
            "traceId": self._trace_id,
        }
        await self._emit(event, persist=False)

    async def text_message_content(self, message_id: str, delta: str) -> None:
        if not delta:
            return
        event = {
            "type": "TEXT_MESSAGE_CONTENT",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "messageId": message_id,
            "delta": delta,
            "traceId": self._trace_id,
        }
        await self._emit(event, persist=False)

    async def text_message_end(
        self,
        message_id: str,
        *,
        usage: UsageStats | None = None,
        latency_ms: float | None = None,
    ) -> None:
        event = {
            "type": "TEXT_MESSAGE_END",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "messageId": message_id,
            "traceId": self._trace_id,
        }
        if usage is not None:
            event["usage"] = usage.as_dict()
        await self._emit(
            event,
            persist=True,
            message_id=message_id,
            latency_ms=latency_ms,
            usage=usage,
        )

    async def run_finished(self, result: dict[str, Any] | None = None) -> None:
        event = {
            "type": "RUN_FINISHED",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "outcome": {"type": "success"},
            "traceId": self._trace_id,
        }
        if result is not None:
            event["result"] = result
        await self._emit(event, persist=True)

    async def run_error(self, message: str, code: str | None = None) -> None:
        event = {
            "type": "RUN_ERROR",
            "threadId": self._thread_id,
            "runId": self._run_id,
            "timestamp": _timestamp_ms(),
            "message": message,
            "traceId": self._trace_id,
        }
        if code:
            event["code"] = code
        await self._emit(event, persist=True, error_code=code)

    async def _emit(
        self,
        event: dict[str, Any],
        *,
        persist: bool,
        step_name: str | None = None,
        message_id: str | None = None,
        latency_ms: float | None = None,
        usage: UsageStats | None = None,
        error_code: str | None = None,
    ) -> None:
        await self._queue.put(event)
        if not persist:
            return
        await self._analytics.write_event(
            AnalyticsEvent(
                event_type=event["type"],
                thread_id=self._thread_id,
                run_id=self._run_id,
                trace_id=self._trace_id,
                payload=event,
                step_name=step_name,
                message_id=message_id,
                latency_ms=latency_ms,
                usage=usage,
                error_code=error_code,
            )
        )


def _timestamp_ms() -> int:
    return int(time.time() * 1000)
