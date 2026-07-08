"""MCP client for the GitHub MCP server.

This is the piece that makes the "we use real MCP" claim defensible in an
interview: agents don't import github_mcp.py's functions directly. Instead
this client launches app/mcp_servers/github_mcp.py as a subprocess over
stdio, performs the MCP handshake, and calls tools by name through the
protocol — exactly like Claude Desktop or any MCP host would. Swapping this
for a different GitHub MCP implementation (or a hosted one) requires no
change to the agents.

Usage:
    async with GitHubMCPClient() as client:
        files = await client.call_tool("list_changed_files", {...})
"""
import json
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.logging_setup import get_logger

logger = get_logger(__name__)


class GitHubMCPClient:
    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "GitHubMCPClient":
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_servers.github_mcp"],
        )
        read, write = await self._stack.enter_async_context(stdio_client(server_params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        logger.info("mcp_session_initialized", server="github_mcp")
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    async def call_tool(self, name: str, arguments: dict):
        assert self._session is not None, "use 'async with GitHubMCPClient()' before calling tools"
        result = await self._session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"MCP tool '{name}' returned an error: {result.content}")

        # MCP tool results are a list of content blocks (text/image/etc).
        # Our GitHub tools always return JSON-serializable text content.
        text_parts = [block.text for block in result.content if block.type == "text"]
        payload = "".join(text_parts)
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
