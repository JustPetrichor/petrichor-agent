from __future__ import annotations

from app.types import AnalyticsEvent


class NoopAnalyticsSink:
    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def init_schema(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def write_event(self, event: AnalyticsEvent) -> None:
        del event
        return None
