"""
Real MCP server wrapping the live incident-status capability, per the
project plan's Phase 9 scope: "Wrap the live incident-status capability
as a real MCP server and consume it through the application." Deliberately
scoped to exactly that one capability -- not a general-purpose MCP gateway
-- since the plan itself flags MCP as the first thing to cut if it grows
beyond a small, defensible slice.

Runs as its own process/service (own port, own ASGI app), not inside the
main FastAPI app -- this is what makes it a genuine MCP server an
external MCP client could also connect to, rather than just an internal
function call wearing an MCP-shaped costume.

    python -m app.mcp_server
"""
from mcp.server.mcpserver import MCPServer

from app.ai.live_tool import get_incident_status
from app.database import AsyncSessionLocal

server = MCPServer(name="incident-copilot-mcp", version="0.1.0")


@server.tool()
async def incident_status(incident_id: str | None = None, title_contains: str | None = None) -> dict:
    """Look up current incident status. Read-only -- see docs/threat-model.md
    on why operational tools in this project never write/mutate state."""
    async with AsyncSessionLocal() as db:
        return await get_incident_status(db, incident_id=incident_id, title_contains=title_contains)


if __name__ == "__main__":
    import os

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    # DNS-rebinding protection checks the Host header against an allowlist;
    # the default only allows localhost, which rejects legitimate
    # service-to-service calls by Docker/Kubernetes service name (e.g.
    # "mcp-server:8100"). Extend it explicitly rather than disabling the
    # protection outright.
    allowed_hosts = ["127.0.0.1", "127.0.0.1:8100", "localhost", "localhost:8100"]
    extra_host = os.environ.get("MCP_ALLOWED_HOST")
    if extra_host:
        allowed_hosts.append(extra_host)
    security = TransportSecuritySettings(allowed_hosts=allowed_hosts)

    uvicorn.run(server.streamable_http_app(transport_security=security), host="0.0.0.0", port=8100)
