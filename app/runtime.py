from __future__ import annotations

from app.config import Settings
from app.db.clickhouse import ClickHouseAnalyticsSink
from app.db.postgres import PostgresThreadRepository
from app.observability import get_tracer
from app.services.analytics import NoopAnalyticsSink
from app.services.langfuse import (
    configure_langfuse,
    create_langfuse_callback_handler,
    create_langfuse_client,
    shutdown_langfuse,
)
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
        self.langfuse = None
        self.langfuse_callback_handler = None
        self.model_client = None
        self.runner = None

    async def start(self) -> None:
        await self.store.connect()
        await self.store.init_schema()
        await self.analytics.connect()
        if self.settings.clickhouse_enabled:
            await self.analytics.init_schema()
        configure_langfuse(self.settings)
        self.langfuse = create_langfuse_client(self.settings)
        self.langfuse_callback_handler = create_langfuse_callback_handler(self.settings)
        self.model_client = LiteLLMModelClient(self.settings)
        self.runner = AgentRunner(
            store=self.store,
            analytics=self.analytics,
            model_client=self.model_client,
            settings=self.settings,
            tracer=get_tracer(),
            langfuse_enabled=self.langfuse is not None,
            langfuse_callback_handler=self.langfuse_callback_handler,
        )

    async def stop(self) -> None:
        shutdown_langfuse(self.langfuse)
        await self.analytics.close()
        await self.store.close()
