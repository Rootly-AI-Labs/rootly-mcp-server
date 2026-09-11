"""Verify that the hosted server is discoverable by a FastMCP 4 client."""

from __future__ import annotations

import asyncio
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main() -> None:
    server_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8000").rstrip("/")
    api_token = os.environ["ROOTLY_API_TOKEN"]
    transport = StreamableHttpTransport(
        f"{server_url}/mcp",
        headers={"Authorization": f"Bearer {api_token}"},
    )

    async with Client(transport, mode="legacy") as client:
        tools = await client.list_tools()

    tool_names = {tool.name for tool in tools}
    required_tools = {"list_incidents", "list_services", "list_teams"}
    missing_tools = required_tools - tool_names
    if missing_tools:
        missing = ", ".join(sorted(missing_tools))
        raise RuntimeError(f"FastMCP 4 discovery did not return required tools: {missing}")

    print(f"FastMCP 4 discovered {len(tools)} tools over hosted streamable HTTP")


if __name__ == "__main__":
    asyncio.run(main())
