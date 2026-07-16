from __future__ import annotations

import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("skillify-echo")


@mcp.tool()
def echo(text: str) -> str:
    return text


@mcp.tool()
async def wait(seconds: float) -> str:
    import anyio

    await anyio.sleep(seconds)
    return "done"


if __name__ == "__main__":
    mcp.run(transport="stdio")
