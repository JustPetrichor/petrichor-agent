from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.config import Settings
from app.types import ToolDefinition, ToolExecutionResult


@dataclass(slots=True)
class _ServerConnection:
    name: str
    session: ClientSession


class McpToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._connections: dict[str, _ServerConnection] = {}
        self._tools: dict[str, ToolDefinition] = {}

    async def start(self) -> None:
        if not self._settings.mcp_enabled:
            return

        config_path = Path(self._settings.mcp_config_path)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        if not config_path.exists():
            return

        config = json.loads(config_path.read_text(encoding="utf-8"))
        for server_name, server_config in config.get("mcpServers", {}).items():
            session = await self._connect_server(server_name, server_config)
            self._connections[server_name] = _ServerConnection(server_name, session)
            for tool in await self._list_all_tools(session):
                exposed_name = self._exposed_tool_name(server_name, tool.name)
                self._tools[exposed_name] = ToolDefinition(
                    name=exposed_name,
                    description=tool.description or f"MCP tool {tool.name} from {server_name}",
                    parameters=_normalize_schema(tool.inputSchema),
                    server_name=server_name,
                    original_name=tool.name,
                )

    async def close(self) -> None:
        await self._stack.aclose()
        self._connections.clear()
        self._tools.clear()

    def has_tools(self) -> bool:
        return bool(self._tools)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown MCP tool: {name}")

        connection = self._connections.get(tool.server_name)
        if connection is None:
            raise ValueError(f"MCP server not connected: {tool.server_name}")

        result = await connection.session.call_tool(
            tool.original_name,
            arguments=arguments,
        )
        return ToolExecutionResult(
            tool_name=tool.name,
            original_name=tool.original_name,
            server_name=tool.server_name,
            content=_serialize_tool_result_content(result),
            is_error=bool(result.isError),
            structured_content=result.structuredContent,
        )

    async def _connect_server(
        self,
        server_name: str,
        server_config: dict[str, Any],
    ) -> ClientSession:
        if "url" in server_config:
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(
                    server_config["url"],
                    headers=server_config.get("headers"),
                    timeout=self._settings.mcp_tool_call_timeout_seconds,
                )
            )
        elif "command" in server_config:
            params = StdioServerParameters(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env"),
                cwd=server_config.get("cwd"),
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        else:
            raise ValueError(f"MCP server '{server_name}' is missing either 'url' or 'command'.")

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _list_all_tools(self, session: ClientSession) -> list[mcp_types.Tool]:
        tools: list[mcp_types.Tool] = []
        cursor: str | None = None
        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(result.tools)
            cursor = result.nextCursor
            if not cursor:
                return tools

    def _exposed_tool_name(self, server_name: str, tool_name: str) -> str:
        base = f"mcp_{server_name}_{tool_name}"
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", base)
        if len(sanitized) <= 64:
            return sanitized
        suffix = abs(hash((server_name, tool_name))) % 100000000
        return f"{sanitized[:55]}_{suffix:08d}"


def _normalize_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    if isinstance(schema, dict) and schema:
        return {"type": "object", **schema}
    return {"type": "object", "properties": {}, "additionalProperties": True}


def _serialize_tool_result_content(result: mcp_types.CallToolResult) -> str:
    parts: list[str] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
            continue
        data = getattr(item, "data", None)
        if data is not None:
            parts.append(json.dumps(data, ensure_ascii=True))
            continue
        uri = getattr(item, "uri", None)
        if uri is not None:
            parts.append(str(uri))
            continue
        parts.append(str(item))

    if parts:
        return "\n".join(parts)
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent, ensure_ascii=True)
    return ""
