"""MCP client test: Gate 4 auth checks (Gate 3 round-trip + credential).

Spawns the server over stdio, lists its tools, then calls
`evaluate_marketing_draft` four times with the passing draft:
no credential, valid credential, expired credential, wrong-scope
credential. The client mints the test credentials itself with auth.py
(the issuer role); the server verifies each one before the tool runs.
No pipeline code is imported here.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from auth import mint_token

SERVER = "/home/muse/langgraph-lab-github/mcp-eval-service/server.py"
PYTHON = "/home/muse/langgraph-lab/.venv/bin/python"
TOOL = "evaluate_marketing_draft"

SECRET = os.environ.get("MCP_EVAL_SECRET")
if not SECRET:
    print("MCP_EVAL_SECRET is not set", file=sys.stderr)
    raise SystemExit(1)

DOCS = [
    {"source": "knowledge_base/positioning.md"},
    {"source": "knowledge_base/services-ai.md"},
    {"source": "knowledge_base/services-platform.md"},
]

PASS_DRAFT = """Safe AI automation for small teams starts with clear goals [1]. Baltic guides organisations through their AI journey with local inference and RAG [2]. The platform covers containers, Kubernetes and Docker for deployment [3].

Sources
[1] knowledge_base/positioning.md
[2] knowledge_base/services-ai.md
[3] knowledge_base/services-platform.md
"""


async def call(session, draft, credential):
    result = await session.call_tool(
        TOOL,
        {"draft": draft, "research_docs": DOCS,
         "deck_bodies": ["Slide one: goals", "Slide two: platform"],
         "credential": credential},
    )
    return json.loads(result.content[0].text)


async def main():
    params = StdioServerParameters(
        command=PYTHON, args=[SERVER],
        env={**os.environ, "MCP_EVAL_SECRET": SECRET},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            cases = [
                ("no credential", ""),
                ("valid credential", mint_token(SECRET, TOOL, 300)),
                ("expired credential", mint_token(SECRET, TOOL, -60)),
                ("wrong scope", mint_token(SECRET, "some-other-tool", 300)),
            ]
            for label, credential in cases:
                data = await call(session, PASS_DRAFT, credential)
                print(label, "->", data)


if __name__ == "__main__":
    asyncio.run(main())
