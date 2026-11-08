"""LangGraph marketing pipeline: drafts + slide decks, eval-gated, human-approved.

Planner -> researcher (local RAG) -> writer (strict citations) -> deck
-> 9-check eval gate -> human approval -> local-only publish.

Local Ollama models only. No cloud model, no API key, no external publish.
"""

__version__ = "0.1.0"
