"""
End-to-end test: spin up the server over stdio and drive it with a real MCP client.
Confirms the tools are discoverable and callable THROUGH the MCP protocol (not just
as plain Python functions). Prints each tool result; server logs appear on stderr.

Usage:  python scripts/test_mcp_client.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "river_mcp.server"],
        env={**os.environ, "PYTHONPATH": os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("DISCOVERED TOOLS:", [t.name for t in tools.tools])

            calls = [
                ("list_scenes", {}),
                ("compute_water_mask", {"scene": "synthetic_river.tif", "index": "ndwi"}),
                ("measure_river_width", {"scene": "synthetic_river.tif", "index": "ndwi", "max_samples": 5}),
                ("detect_obstruction_candidates", {"scene": "synthetic_river.tif", "index": "mndwi", "sensitivity": 0.5}),
                ("measure_river_width", {"scene": "../etc/passwd"}),  # security check
            ]
            for name, args in calls:
                res = await session.call_tool(name, args)
                payload = res.content[0].text if res.content else "{}"
                print(f"\n>>> {name}({json.dumps(args)})")
                print(payload[:700])


if __name__ == "__main__":
    asyncio.run(main())
