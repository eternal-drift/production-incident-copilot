"""
Tests the real MCP server (app/mcp_server.py) via the SDK's in-memory
transport -- runs the actual server object and protocol round trip
(initialize, list_tools, call_tool), just without a real network socket.
Not a fake/mocked check: this is the same server object the live
mcp-server container runs (see docker-compose.yml).
"""
import pytest
from mcp import ClientSession
from mcp.client._memory import InMemoryTransport

from app.mcp_server import server


@pytest.mark.asyncio
async def test_mcp_server_exposes_incident_status_tool():
    async with InMemoryTransport(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "incident_status" in [t.name for t in tools.tools]


@pytest.mark.asyncio
async def test_mcp_incident_status_call_returns_expected_shape():
    async with InMemoryTransport(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("incident_status", {})
            assert not result.is_error
            import json
            body = json.loads(result.content[0].text)
            assert "found" in body
            assert "incidents" in body
