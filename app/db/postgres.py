from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from app.config import Settings
from app.types import ConversationMessage, ThreadContext, ThreadRecord

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    run_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_created_at
    ON messages (thread_id, created_at);

CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresThreadRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self._settings.postgres_dsn,
            min_size=self._settings.postgres_min_pool_size,
            max_size=self._settings.postgres_max_pool_size,
        )

    async def close(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def init_schema(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(POSTGRES_SCHEMA)

    async def ping(self) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return (await connection.fetchval("SELECT 1")) == 1

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> ThreadRecord:
        pool = self._require_pool()
        thread_id = str(uuid.uuid4())
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO threads (id, metadata)
                VALUES ($1, $2::jsonb)
                RETURNING id, summary, metadata, created_at, updated_at
                """,
                thread_id,
                json.dumps(metadata or {}),
            )
        return ThreadRecord(
            id=row["id"],
            summary=row["summary"],
            metadata=_json_value(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=[],
        )

    async def get_thread(self, thread_id: str, limit: int = 50) -> ThreadRecord | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            thread_row = await connection.fetchrow(
                """
                SELECT id, summary, metadata, created_at, updated_at
                FROM threads
                WHERE id = $1
                """,
                thread_id,
            )
            if thread_row is None:
                return None
            message_rows = await connection.fetch(
                """
                SELECT id, role, content, run_id, metadata, created_at
                FROM messages
                WHERE thread_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                thread_id,
                limit,
            )
        messages = [_message_from_row(row) for row in reversed(message_rows)]
        return ThreadRecord(
            id=thread_row["id"],
            summary=thread_row["summary"],
            metadata=_json_value(thread_row["metadata"]),
            created_at=thread_row["created_at"],
            updated_at=thread_row["updated_at"],
            messages=messages,
        )

    async def get_context(self, thread_id: str, limit: int) -> ThreadContext | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            thread_row = await connection.fetchrow(
                """
                SELECT id, summary
                FROM threads
                WHERE id = $1
                """,
                thread_id,
            )
            if thread_row is None:
                return None
            message_rows = await connection.fetch(
                """
                SELECT id, role, content, run_id, metadata, created_at
                FROM messages
                WHERE thread_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                thread_id,
                limit,
            )
            message_count = await connection.fetchval(
                "SELECT COUNT(*) FROM messages WHERE thread_id = $1",
                thread_id,
            )
        return ThreadContext(
            thread_id=thread_row["id"],
            summary=thread_row["summary"],
            recent_messages=[_message_from_row(row) for row in reversed(message_rows)],
            message_count=int(message_count or 0),
        )

    async def list_messages(self, thread_id: str) -> list[ConversationMessage]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, role, content, run_id, metadata, created_at
                FROM messages
                WHERE thread_id = $1
                ORDER BY created_at ASC
                """,
                thread_id,
            )
        return [_message_from_row(row) for row in rows]

    async def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        pool = self._require_pool()
        message_id = str(uuid.uuid4())
        async with pool.acquire() as connection:
            exists = await connection.fetchval("SELECT 1 FROM threads WHERE id = $1", thread_id)
            if exists is None:
                raise ValueError(f"Unknown thread_id: {thread_id}")
            row = await connection.fetchrow(
                """
                INSERT INTO messages (id, thread_id, role, content, run_id, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING id, role, content, run_id, metadata, created_at
                """,
                message_id,
                thread_id,
                role,
                content,
                run_id,
                json.dumps(metadata or {}),
            )
            await connection.execute(
                "UPDATE threads SET updated_at = NOW() WHERE id = $1",
                thread_id,
            )
        return _message_from_row(row)

    async def update_summary(self, thread_id: str, summary: str) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE threads
                SET summary = $2, updated_at = NOW()
                WHERE id = $1
                """,
                thread_id,
                summary,
            )

    async def save_checkpoint(self, thread_id: str, run_id: str, state: dict[str, Any]) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO graph_checkpoints (thread_id, run_id, state)
                VALUES ($1, $2, $3::jsonb)
                """,
                thread_id,
                run_id,
                json.dumps(state),
            )

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Postgres connection pool has not been initialized.")
        return self._pool


def _message_from_row(row: asyncpg.Record) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        run_id=row["run_id"],
        metadata=_json_value(row["metadata"]),
        created_at=row["created_at"],
    )


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}
