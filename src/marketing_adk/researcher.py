"""ADK researcher agent: retrieve with the shared tool, synthesise with
the shared rules. Same shape as the LangGraph researcher: 3 docs plus
a synthesis entry.
"""

import asyncio
import json

from google.adk.agents import LlmAgent
from google.genai import types

from marketing_pipeline.config import DEFAULT_GOAL, SYNTH_MODEL
from marketing_pipeline.llm import _generate
from marketing_pipeline.retrieve import retrieve
from marketing_pipeline.rules import SYNTHESIS_INSTRUCTION, synthesis_prompt
from .models import adk_model
from .runner import find_tool_result, run_with_fallback
from .tools import RETRIEVE_TOOL


def build_researcher_agent(backend=None):
    """Researcher on the shared synthesis rules, with the retrieve tool.
    The model synthesises; the tool retrieves. Neither invents facts."""
    return LlmAgent(
        name="researcher",
        model=adk_model("writer", backend, think=False),
        instruction=(
            "Call the retrieve_docs tool exactly once with the query to get the "
            "retrieved docs. Then output ONLY the bullet lines, one per line, "
            "each starting with its source file name, e.g. '- services-ai.md: ...' "
            "No introduction, no reasoning, no JSON, no title, nothing before "
            "the first bullet and nothing after the last."
        ),
        tools=[RETRIEVE_TOOL],
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )


async def run_researcher_once(query=DEFAULT_GOAL):
    """Hello run: retrieve + synthesise. Returns (research list, backend).
    Research is the 3 retrieved docs plus a synthesis entry, the same
    shape the LangGraph researcher returns. If the agent loops on the tool
    and never answers, the synthesis comes from the shared plain call
    (the deterministic path) instead of the agent's missing final text."""
    content = types.Content(role="user", parts=[types.Part(text=f"Research this for the marketing plan: {query}")])
    text, events, backend = await run_with_fallback(
        lambda b: build_researcher_agent(backend=b), content, partial_on_timeout=True)
    docs = find_tool_result(events, "retrieve_docs")
    if docs is None:
        print("Tool result not captured from events; calling shared retrieve directly.")
        docs = retrieve(query)
    research = [{"source": d["source"], "snippet": d["snippet"], "score": d.get("score")} for d in docs]
    synthesis = text.strip()
    if not synthesis:
        # Agent looped on the tool and never answered; anchor the synthesis
        # to the shared deterministic path (same prompt + plain call as LangGraph).
        synthesis = _generate(SYNTH_MODEL, synthesis_prompt(docs)).get("response", "").strip()
        print("Synthesis from the shared plain call (agent produced no final text).")
    research.append({"source": "synthesis", "snippet": synthesis, "score": None})
    return research, backend


if __name__ == "__main__":
    research, backend = asyncio.run(run_researcher_once())
    print(f"backend: {backend}")
    print(json.dumps(research, indent=2))
