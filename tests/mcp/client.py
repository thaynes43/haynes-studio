from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = "http://localhost/mcp"
API_URL = "http://studio-api.studio.svc.cluster.local"


@asynccontextmanager
async def connect(app, authorization):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        headers={"Authorization": authorization},
    ) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                hello = await session.initialize()
                assert hello.serverInfo.name == "studio-mcp"
                assert hello.serverInfo.version == "1.0.0"
                assert hello.capabilities.resources is None
                yield session


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    assert not result.isError, result.structuredContent
    return result.structuredContent


async def fail(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    assert result.isError
    return result.structuredContent["error"]
