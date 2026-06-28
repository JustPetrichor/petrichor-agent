from __future__ import annotations

import json
from typing import Any

import litellm
from litellm import Router

from app.config import Settings
from app.prompts import build_summary_prompt_messages
from app.types import ConversationMessage, ModelChunk, ModelTurn, ToolCallRequest, UsageStats

litellm.drop_params = True
litellm.suppress_debug_info = True


class LiteLLMModelClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._router = Router(
            model_list=[
                {
                    "model_name": settings.model_alias,
                    "litellm_params": {
                        "model": f"openai/{settings.model_name}",
                        "api_base": settings.model_api_base,
                        "api_key": settings.model_api_key,
                        "timeout": settings.model_timeout_seconds,
                    },
                }
            ],
            timeout=settings.model_timeout_seconds,
            routing_strategy="simple-shuffle",
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ):
        response = await self._router.acompletion(
            model=self._settings.model_alias,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            metadata=metadata,
        )

        if hasattr(response, "__aiter__"):
            async for chunk in response:
                model_chunk = _chunk_from_stream(chunk)
                if model_chunk is not None:
                    yield model_chunk

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        metadata: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ModelTurn:
        response = await self._router.acompletion(
            model=self._settings.model_alias,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            metadata=metadata,
        )
        return ModelTurn(
            content=_extract_response_content(response).strip(),
            usage=_extract_usage(response),
            finish_reason=_extract_finish_reason(response),
            tool_calls=_extract_tool_calls(response),
        )

    async def summarize_context(
        self,
        existing_summary: str,
        messages: list[ConversationMessage],
    ) -> str:
        if not messages:
            return existing_summary

        prompt_messages = build_summary_prompt_messages(existing_summary, messages)

        response = await self._router.acompletion(
            model=self._settings.model_alias,
            messages=prompt_messages,
            max_tokens=180,
            metadata={"task": "rolling-summary", "message_count": len(messages)},
        )
        content = _extract_response_content(response).strip()
        return content or existing_summary


def _chunk_from_stream(chunk: Any) -> ModelChunk | None:
    delta = _extract_delta(chunk)
    usage = _extract_usage(chunk)
    finish_reason = _extract_finish_reason(chunk)
    if not delta and usage is None and finish_reason is None:
        return None
    return ModelChunk(delta=delta, usage=usage, finish_reason=finish_reason)


def _extract_delta(chunk: Any) -> str:
    choices = _field(chunk, "choices", [])
    if not choices:
        return ""
    first_choice = choices[0]
    delta = _field(first_choice, "delta", {})
    content = _field(delta, "content", "")
    return _normalize_content(content)


def _extract_usage(chunk: Any) -> UsageStats | None:
    usage = _field(chunk, "usage")
    if usage is None:
        return None
    return UsageStats(
        prompt_tokens=_field(usage, "prompt_tokens"),
        completion_tokens=_field(usage, "completion_tokens"),
        total_tokens=_field(usage, "total_tokens"),
    )


def _extract_finish_reason(chunk: Any) -> str | None:
    choices = _field(chunk, "choices", [])
    if not choices:
        return None
    return _field(choices[0], "finish_reason")


def _extract_tool_calls(response: Any) -> list[ToolCallRequest]:
    choices = _field(response, "choices", [])
    if not choices:
        return []
    message = _field(choices[0], "message", {})
    tool_calls = _field(message, "tool_calls", []) or []
    parsed: list[ToolCallRequest] = []
    for tool_call in tool_calls:
        function = _field(tool_call, "function", {})
        raw_arguments = _field(function, "arguments", "{}")
        try:
            if isinstance(raw_arguments, str):
                arguments = json.loads(raw_arguments)
            else:
                arguments = raw_arguments
        except Exception:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        parsed.append(
            ToolCallRequest(
                id=_field(tool_call, "id", ""),
                name=_field(function, "name", ""),
                arguments=arguments,
            )
        )
    return [item for item in parsed if item.id and item.name]


def _extract_response_content(response: Any) -> str:
    choices = _field(response, "choices", [])
    if not choices:
        return ""
    message = _field(choices[0], "message", {})
    content = _field(message, "content", "")
    return _normalize_content(content)


def _normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)
