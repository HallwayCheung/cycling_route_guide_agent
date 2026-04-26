import asyncio
import os
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class CyclingMcpClient:
    def __init__(self):
        self.python_path = os.getenv("CYCLING_MCP_PYTHON", sys.executable)
        self.server_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_servers", "main.py")
        self.server_params = StdioServerParameters(
            command=self.python_path,
            args=[self.server_script],
            env=os.environ.copy()
        )

    async def call_tool(self, tool_name: str, arguments: dict):
        """
        Connects to MCP server, calls a tool, and returns result.
        """
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return result.content[0].text
