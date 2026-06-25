from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.config import Settings
from app.observability import current_trace_id
from app.runtime import AppRuntime
from app.schemas import CreateThreadRequest, HealthResponse, StreamRunRequest, ThreadResponse
from app.services.agui import EventPublisher, encode_sse

logger = logging.getLogger(__name__)


def create_app(runtime: AppRuntime | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    runtime = runtime or AppRuntime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.runtime.start()
        yield
        await app.state.runtime.stop()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.runtime = runtime

    @app.get("/", include_in_schema=False)
    async def demo_client() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.post("/threads", response_model=ThreadResponse)
    async def create_thread(payload: CreateThreadRequest | None = None) -> ThreadResponse:
        metadata = (payload or CreateThreadRequest()).metadata
        thread = await app.state.runtime.store.create_thread(metadata)
        return _serialize_thread(thread)

    @app.get("/threads/{thread_id}", response_model=ThreadResponse)
    async def get_thread(thread_id: str) -> ThreadResponse:
        thread = await app.state.runtime.store.get_thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found.")
        return _serialize_thread(thread)

    @app.post("/threads/{thread_id}/runs/stream")
    async def stream_run(thread_id: str, payload: StreamRunRequest, request: Request):
        thread = await app.state.runtime.store.get_thread(thread_id, limit=1)
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found.")

        run_id = payload.client_run_id or str(uuid.uuid4())
        trace_id = current_trace_id()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        publisher = EventPublisher(
            queue=queue,
            thread_id=thread_id,
            run_id=run_id,
            trace_id=trace_id,
            analytics=app.state.runtime.analytics,
        )

        async def run_agent() -> None:
            try:
                await app.state.runtime.runner.run(
                    thread_id=thread_id,
                    run_id=run_id,
                    user_message=payload.user_message,
                    metadata=payload.metadata,
                    trace_id=trace_id,
                    publisher=publisher,
                )
            except Exception:
                logger.exception(
                    "Agent run failed.",
                    extra={"thread_id": thread_id, "run_id": run_id},
                )
            finally:
                await publisher.close()

        task = asyncio.create_task(run_agent())

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    event = await queue.get()
                    if event is None:
                        break
                    yield encode_sse(event)
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        postgres_ok = await app.state.runtime.store.ping()
        clickhouse_ok = True
        if app.state.runtime.settings.clickhouse_enabled:
            clickhouse_ok = await app.state.runtime.analytics.ping()
        return HealthResponse(
            ok=postgres_ok and clickhouse_ok,
            postgres={"ok": postgres_ok},
            clickhouse={"ok": clickhouse_ok},
        )

    return app


def _serialize_thread(thread) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread.id,
        summary=thread.summary,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        metadata=thread.metadata,
        messages=[
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "run_id": message.run_id,
                "metadata": message.metadata,
            }
            for message in thread.messages
        ],
    )


app = create_app()
