"""MCP server: the marketing-pipeline eval as a service (Gates 2 + 4).

One tool, `evaluate_marketing_draft`. Same 9 checks as the pipeline,
via `evaluate()` from Gate 1. No new checks.

Gate 4: every call must carry a credential. The server verifies it
before the tool runs, on every call: present, signature valid, not
expired, scope covers the tool. Any failure -> the tool does not run.

Transport: stdio (default). Run from the repo root:
    MCP_EVAL_SECRET=... ~/langgraph-lab/.venv/bin/python mcp-eval-service/server.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer

from auth import verify_token
from marketing_pipeline.evaluate import evaluate

TOOL = "evaluate_marketing_draft"

SECRET = os.environ.get("MCP_EVAL_SECRET")
if not SECRET:
    print("MCP_EVAL_SECRET is not set", file=sys.stderr)
    raise SystemExit(1)

mcp = MCPServer("marketing-eval")


@mcp.tool(description="Run the 9 marketing-draft eval checks on a draft. Requires a credential: pass the token from issue_token.py as `credential`. Returns the checks, citation coverage, cited numbers, pass/fail and feedback as JSON, or an error if the credential is missing, invalid, expired, or out of scope.")
def evaluate_marketing_draft(draft: str, research_docs: list[dict], deck_bodies: list[str], credential: str = "") -> str:
    """Check one marketing draft.

    draft: draft text.
    research_docs: research items, each with at least "source".
    deck_bodies: deck slide bodies, for the 9th check.
    credential: token from issue_token.py. Verified on every call.
    """
    ok, reason = verify_token(credential, SECRET, TOOL)
    if not ok:
        return json.dumps({"error": "unauthorized: " + reason})
    result = evaluate(draft, research_docs, deck_bodies)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
