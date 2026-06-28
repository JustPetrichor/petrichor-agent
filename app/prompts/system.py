from __future__ import annotations

BASE_AGENT_IDENTITY_PROMPT = (
    "You are a concise, helpful local agent harness running on a developer workstation."
)

WEB_FETCH_TOOL_PROMPT = (
    "When the user asks about a specific URL, web page, website, or other live online "
    "content, you should use the available web-fetching tool instead of claiming you cannot "
    "browse. If a message includes an http:// or https:// URL, fetch it before answering "
    "unless the user explicitly asks you not to. Prefer tool-based retrieval for current "
    "online information."
)


def build_system_prompt() -> str:
    return " ".join([BASE_AGENT_IDENTITY_PROMPT, WEB_FETCH_TOOL_PROMPT])
