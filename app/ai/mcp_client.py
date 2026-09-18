"""
MCP client for the live incident-status tool served by app/mcp_server.py.
Used by app/graph/workflow.py's live_node instead of calling
app/ai/live_tool.py directly -- this is what makes MCP a real protocol
boundary rather than a same-process function call, per the project
plan's Phase 9 scope.

Same graceful-degradation posture as the rest of this project (LLM
unavailable, embeddings unavailable): if the MCP server can't be
reached, the caller falls back to the direct DB call rather than
failing the whole request. See live_node in workflow.py for the
fallback wiring.
"""
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import settings


async def get_incident_status_via_mcp(incident_id: str | None = None, title_contains: str | None = None) -> dict:
    async with streamable_http_client(settings.mcp_server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "incident_status", {"incident_id": incident_id, "title_contains": title_contains}
            )
            if result.is_error:
                raise RuntimeError(f"MCP tool call failed: {result.content}")
            return json.loads(result.content[0].text)
