from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from app.config import Settings
from app.services.mcp import McpToolRegistry


def _write_test_server(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            app = FastMCP("test-fetch")

            @app.tool()
            def fetch_page(url: str) -> str:
                return f"page:{url}"

            if __name__ == "__main__":
                app.run("stdio")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_mcp_registry_loads_stdio_server_and_calls_tool(tmp_path: Path) -> None:
    server_script = tmp_path / "test_mcp_server.py"
    _write_test_server(server_script)

    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fetch": {
                        "command": sys.executable,
                        "args": [str(server_script)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    registry = McpToolRegistry(
        Settings(
            mcp_enabled=True,
            mcp_config_path=str(config_path),
        )
    )

    try:
        await registry.start()
        schemas = registry.get_tool_schemas()

        assert registry.has_tools() is True
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "mcp_fetch_fetch_page"

        result = await registry.call_tool(
            "mcp_fetch_fetch_page",
            {"url": "https://example.com"},
        )
        assert result.content == "page:https://example.com"
        assert result.server_name == "fetch"
        assert result.original_name == "fetch_page"
    finally:
        await registry.close()
