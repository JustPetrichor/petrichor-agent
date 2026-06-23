from __future__ import annotations

from app.config import Settings
from app.db.clickhouse import ClickHouseAnalyticsSink
from app.db.postgres import PostgresThreadRepository
from app.observability import get_tracer
from app.services.analytics import NoopAnalyticsSink
from app.services.model import LiteLLMModelClient
from app.services.runner import AgentRunner


class AppRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = PostgresThreadRepository(settings)
        self.analytics = (
            ClickHouseAnalyticsSink(settings)
            if settings.clickhouse_enabled
            else NoopAnalyticsSink()
        )
        self.model_client = LiteLLMModelClient(settings)
        self.runner = AgentRunner(
            store=self.store,
            analytics=self.analytics,
            model_client=self.model_client,
            settings=settings,
            tracer=get_tracer(),
        )

    async def start(self) -> None:
        await self.store.connect()
        await self.store.init_schema()
        await self.analytics.connect()
        if self.settings.clickhouse_enabled:
            await self.analytics.init_schema()

    async def stop(self) -> None:
        await self.analytics.close()
        await self.store.close()
