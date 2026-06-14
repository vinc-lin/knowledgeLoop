"""Stdio MCP client for the Codebase-Memory-MCP backend."""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_CBM_COMMAND = ["uvx", "codebase-memory-mcp"]


class CBMUnavailable(RuntimeError):
    """CBM is unreachable or returned an error."""


def parse_tool_result(result) -> Any:
    """Extract a CBM tool's payload from an mcp CallToolResult.

    Prefers structuredContent; else JSON-parses the first text block; else raw text.
    Raises CBMUnavailable if the result is flagged isError.
    """
    if getattr(result, "isError", False):
        raise CBMUnavailable(f"CBM tool error: {_first_text(result)}")
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    text = _first_text(result)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _first_text(result) -> Optional[str]:
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return None


def backoff_delays(n: int, base: float = 0.5, cap: float = 8.0) -> list[float]:
    """Exponential backoff schedule: base, 2*base, 4*base, ... capped at `cap`."""
    return [min(cap, base * (2 ** i)) for i in range(n)]


class CBMClient:
    """Owns one long-lived CBM subprocess reached over stdio MCP."""

    def __init__(self, command: Optional[list[str]] = None, *, call_timeout: float = 30.0,
                 env: Optional[dict] = None, cwd: Optional[str] = None):
        cmd = command or DEFAULT_CBM_COMMAND
        # NOTE: the MCP SDK merges `env` over a clean get_default_environment(), NOT the parent
        # env. Callers must include any non-CBM_* vars CBM needs (see repo_memory.deploy.PRESERVE_ENV).
        self._params = StdioServerParameters(command=cmd[0], args=list(cmd[1:]), env=env, cwd=cwd)
        self._call_timeout = call_timeout
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    @property
    def running(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(self._params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # spawn/handshake failure
            await stack.aclose()
            raise CBMUnavailable(f"CBM start failed: {exc}") from exc
        self._stack, self._session = stack, session

    async def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        if self._session is None:
            raise CBMUnavailable("CBM client not started")
        result = await self._session.call_tool(
            name, arguments or {},
            read_timeout_seconds=timedelta(seconds=self._call_timeout),
        )
        return parse_tool_result(result)

    async def call_tool_with_restart(self, name: str, arguments: Optional[dict] = None,
                                     *, max_restarts: int = 2) -> Any:
        last: Optional[Exception] = None
        for attempt in range(max_restarts + 1):
            try:
                return await self.call_tool(name, arguments)
            except Exception as exc:
                last = exc
                if attempt < max_restarts:
                    await self._restart(attempt)
        raise CBMUnavailable(f"CBM call '{name}' failed after {max_restarts} restarts: {last}")

    async def _restart(self, attempt: int) -> None:
        await asyncio.sleep(backoff_delays(attempt + 1)[-1])
        await self.aclose()
        try:
            await self.start()
        except CBMUnavailable:
            pass  # next attempt's call_tool will raise "not started"

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self._session = None
