from __future__ import annotations

import logging
import os
from typing import Any

import litellm

from app.config import Settings

logger = logging.getLogger(__name__)

try:
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler
except ImportError:  # pragma: no cover - dependency is installed in normal runtime
    CallbackHandler = None  # type: ignore[assignment]
    get_client = None  # type: ignore[assignment]


def configure_langfuse(settings: Settings) -> None:
    if not settings.langfuse_enabled:
        return

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse is enabled but credentials are missing; skipping setup.")
        return

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_base_url
    os.environ["LANGFUSE_OTEL_HOST"] = settings.langfuse_base_url.rstrip("/")
    os.environ["LANGFUSE_HOST"] = settings.langfuse_base_url.rstrip("/")

    callbacks = list(getattr(litellm, "callbacks", []))
    if "langfuse_otel" not in callbacks:
        callbacks.append("langfuse_otel")
        litellm.callbacks = callbacks

    success_callbacks = list(getattr(litellm, "success_callback", []))
    if "langfuse_otel" not in success_callbacks:
        success_callbacks.append("langfuse_otel")
        litellm.success_callback = success_callbacks

    failure_callbacks = list(getattr(litellm, "failure_callback", []))
    if "langfuse_otel" not in failure_callbacks:
        failure_callbacks.append("langfuse_otel")
        litellm.failure_callback = failure_callbacks


def create_langfuse_client(settings: Settings):
    if not settings.langfuse_enabled:
        return None

    if get_client is None:
        logger.warning("Langfuse is enabled but the package is not installed.")
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse is enabled but credentials are missing; skipping client setup.")
        return None

    return get_client()


def create_langfuse_callback_handler(settings: Settings):
    if not settings.langfuse_enabled:
        return None

    if CallbackHandler is None:
        logger.warning("Langfuse callback handler is unavailable because langchain is missing.")
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse callback handler is skipped because credentials are missing.")
        return None

    return CallbackHandler()


def shutdown_langfuse(client: Any) -> None:
    if client is None:
        return
    client.flush()
    client.shutdown()
