# Petrichor Agent

Minimal local-agent harness built with:

- `FastAPI` for the API surface
- `LangGraph` for orchestration
- `LiteLLM` for local OpenAI-compatible model routing
- `Langfuse` for optional LLM/agent observability
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

## MCP Web Browsing

This repo now includes a workspace MCP config at [.mcp.json](/Users/sungjae/Documents/petrichor-agent/.mcp.json) for the official MCP `fetch` server, which lets an agent retrieve and read web page content.

It uses the standard `fetch` setup:

```json
{
  "mcpServers": {
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    }
  }
}
```

This server fetches a URL and converts page content into markdown for easier LLM consumption. The configuration is based on the official MCP reference server docs: [modelcontextprotocol/servers fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch).

Security note: the official fetch server warns that it can access local or internal IPs, so treat it as a trusted local tool and be careful about what URLs you allow it to fetch.

## Local Model Endpoint

The harness now defaults to an `Ollama` server running locally on `http://127.0.0.1:11434/v1`.

Configure these values in `.env` if you want to change the target:

- `MODEL_API_BASE`, for example `http://127.0.0.1:11434/v1`
- `MODEL_NAME=qwen3.6:35b-mlx`
- `MODEL_API_KEY=ollama`
- `CLICKHOUSE_USERNAME=petrichor`
- `CLICKHOUSE_PASSWORD=petrichor`

LiteLLM routes calls through the logical model alias `agent.default`, so the rest of the app stays provider-agnostic.

## Langfuse

Langfuse is optional and disabled by default.

For a self-hosted local Langfuse stack, start it with:

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

Then open:

```text
http://127.0.0.1:3000
```

The compose file pre-seeds a local development setup with:

- org id: `petrichor`
- org: `Petrichor`
- project id: `petrichor-agent`
- project: `petrichor-agent`
- public key: `pk-lf-petrichor-agent-dev`
- secret key: `sk-lf-petrichor-agent-dev`
- login: `admin@example.com`
- password: `changeme123!`

To enable Langfuse in the app, set these values in `.env`:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-petrichor-agent-dev
LANGFUSE_SECRET_KEY=sk-lf-petrichor-agent-dev
LANGFUSE_BASE_URL=http://127.0.0.1:3000
```

When enabled, the app records:

- LangGraph run and node traces via the Langfuse LangChain callback handler
- LiteLLM model-call telemetry via LiteLLM's `langfuse_otel` callback
- shared thread/run metadata propagated onto the Langfuse trace

The existing OpenTelemetry service tracing stays in place alongside Langfuse.

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
- v1 includes MCP-backed tool use for simple web fetching, but does not include semantic retrieval or authentication.
- ClickHouse stores structured analytics separately from conversation memory.
- For native macOS development without Docker, the recommended shortcut is Postgres via Homebrew plus `CLICKHOUSE_ENABLED=false`.
