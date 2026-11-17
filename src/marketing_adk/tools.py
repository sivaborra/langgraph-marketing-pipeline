"""ADK tools: thin FunctionTool wrappers around the shared modules.

The tool IS the shared function - no reimplementation, no second
retrieval logic. The agent calls it; the model never sees the KB
except through it.
"""

from google.adk.tools import FunctionTool

from marketing_pipeline.retrieve import retrieve


def retrieve_docs(query: str, top_k: int = 3) -> list[dict]:
    """Retrieve the most relevant knowledge-base docs for a query.

    Searches the local knowledge base by embedding similarity and
    returns the top matches with their source file, snippet and score.
    Use this before synthesising anything: never invent facts the
    retrieved docs do not contain.
    """
    return retrieve(query, top_k=top_k)


RETRIEVE_TOOL = FunctionTool(retrieve_docs)

