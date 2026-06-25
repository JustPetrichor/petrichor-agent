from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "petrichor-agent"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    app_base_url: str = "http://127.0.0.1:8000"
    app_enable_telemetry: bool = True

    model_alias: str = "agent.default"
    model_name: str = "qwen3.6:35b-mlx"
    model_api_base: str = "http://127.0.0.1:11434/v1"
    model_api_key: str = "ollama"
    model_timeout_seconds: int = 120
    model_tool_calling_enabled: bool = True

    postgres_dsn: str = "postgresql://postgres:postgres@127.0.0.1:5432/petrichor"
    postgres_min_pool_size: int = 1
    postgres_max_pool_size: int = 10

    clickhouse_enabled: bool = True
    clickhouse_host: str = "127.0.0.1"
    clickhouse_port: int = 8123
    clickhouse_username: str = "petrichor"
    clickhouse_password: str = "petrichor"
    clickhouse_database: str = "petrichor"

    otel_service_name: str = "petrichor-agent"
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4317"

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "http://127.0.0.1:3000"
    langfuse_tracing_environment: str | None = None
    langfuse_tracing_release: str | None = None

    mcp_enabled: bool = True
    mcp_config_path: str = ".mcp.json"
    mcp_tool_call_timeout_seconds: int = 30
    mcp_max_tool_roundtrips: int = 6

    prompt_system_message: str = (
        "You are a concise, helpful local agent harness running on a developer workstation. "
        "When the user asks about a specific URL, web page, website, or other live online content, "
        "you should use the available web-fetching tool instead of claiming you cannot browse. "
        "If a message includes an http:// or https:// URL, fetch it before answering unless the "
        "user explicitly asks you not to. Prefer tool-based retrieval for current online "
        "information."
    )
    thread_memory_window: int = 12
    summary_trigger_messages: int = 12
