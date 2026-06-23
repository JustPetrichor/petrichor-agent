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

    prompt_system_message: str = (
        "You are a concise, helpful local agent harness running on a developer workstation."
    )
    thread_memory_window: int = 12
    summary_trigger_messages: int = 12
