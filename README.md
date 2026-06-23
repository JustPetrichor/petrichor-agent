# Petrichor Agent

Minimal local-agent harness built with:

- `FastAPI` for the API surface
- `LangGraph` for orchestration
- `LiteLLM` for local OpenAI-compatible model routing
- `Postgres` for thread memory and checkpoints
- `ClickHouse` for immutable run analytics
- `OpenTelemetry` for traces and correlated logs
- AG-UI-compatible SSE events for the streaming protocol

## What You Get

- `POST /threads` to create a new thread
- `GET /threads/{thread_id}` to inspect recent thread state
- `POST /threads/{thread_id}/runs/stream` to stream AG-UI events over SSE
- `GET /healthz` to verify the app and its backing services
- `/` serving a tiny demo client for manual end-to-end testing

## Quickstart

1. Copy the example env file and adjust the local model endpoint:

```bash
cp .env.example .env
```

2. Start backing services with Docker if it is available:

```bash
docker compose up -d
```

If Docker is not available on your Mac, use the native fallback instead:

```bash
chmod +x scripts/setup_macos_postgres.sh
./scripts/setup_macos_postgres.sh
```

Then set these local-only overrides before running the app:

```bash
export POSTGRES_DSN="postgresql://$(whoami)@127.0.0.1:5432/petrichor"
export CLICKHOUSE_ENABLED=false
export APP_ENABLE_TELEMETRY=false
```

3. Install Python and dependencies with `uv`:

```bash
uv python install 3.12
uv sync --extra dev
```

4. Run the app:

```bash
uv run uvicorn app.main:app --reload
```

5. Open the demo client:

```text
http://127.0.0.1:8000
```

## Local Model Endpoint

The harness now defaults to an `Ollama` server running locally on `http://127.0.0.1:11434/v1`.

Configure these values in `.env` if you want to change the target:

- `MODEL_API_BASE`, for example `http://127.0.0.1:11434/v1`
- `MODEL_NAME=qwen3.6:35b-mlx`
- `MODEL_API_KEY=ollama`
- `CLICKHOUSE_USERNAME=petrichor`
- `CLICKHOUSE_PASSWORD=petrichor`

LiteLLM routes calls through the logical model alias `agent.default`, so the rest of the app stays provider-agnostic.

## Running Tests

```bash
uv run pytest
```

## Event Flow

Each streamed run emits AG-UI-compatible events with uppercase `type` names:

- `RUN_STARTED`
- `STEP_STARTED`
- `STEP_FINISHED`
- `TEXT_MESSAGE_START`
- `TEXT_MESSAGE_CONTENT`
- `TEXT_MESSAGE_END`
- `RUN_FINISHED`
- `RUN_ERROR`

## Notes

- v1 keeps durable thread history plus a rolling summary only.
- v1 does not include tools, semantic retrieval, or authentication.
- ClickHouse stores structured analytics separately from conversation memory.
- For native macOS development without Docker, the recommended shortcut is Postgres via Homebrew plus `CLICKHOUSE_ENABLED=false`.
