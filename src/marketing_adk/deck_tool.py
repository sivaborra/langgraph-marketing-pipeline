"""ADK deck tool: build the .pptx from the plan, research and draft, using
the shared deck builder. The tool does the deterministic work; the agent
just calls it. Same shape as the LangGraph deck node.
"""

import asyncio
import json
import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from marketing_pipeline.config import DEFAULT_GOAL, SERVICES, SYNTH_MODEL, WRITER_MODEL
from marketing_pipeline.deck import build_deck
from marketing_pipeline.llm import _generate
from marketing_pipeline.retrieve import retrieve
from marketing_pipeline.rules import synthesis_prompt, writer_prompt
from .models import adk_model
from .runner import find_tool_result, run_with_fallback


def make_deck(plan: dict, research: list, draft: str, run_id: str) -> dict:
    """Build the deck with the shared builder. Returns a JSON-serialisable
    result: the .pptx path, the slide count, and any fallback slides."""
    deck_path, deck_slides, fallback_slides = build_deck(plan, research, draft, run_id)
    return {
        "deck_path": deck_path,
        "deck_slides": deck_slides,
        "fallback_slides": fallback_slides,
    }


DECK_TOOL = FunctionTool(make_deck)


def build_deck_agent(backend=None):
    """Deck builder agent. One job: call make_deck with the plan, research,
    draft and run id from the user message, then report the path and slides."""
    return LlmAgent(
        name="deck_builder",
        model=adk_model("writer", backend, think=False),
        instruction=(
            "You build the slide deck. Call the make_deck tool exactly once "
            "with the plan, research, draft and run_id from the user message. "
            "Then reply with ONLY the deck path and the slide count, e.g. "
            "'deck: outputs/deck-gate6-test.pptx slides: 5'. Nothing else."
        ),
        tools=[DECK_TOOL],
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )


async def run_deck_once(plan, research, draft, run_id):
    """Hello run: build the deck. Returns (deck info dict, backend).
    If the agent does not produce a usable tool result (loops), the deck
    comes from the shared builder directly."""
    content = types.Content(role="user", parts=[types.Part(text=json.dumps({
        "plan": plan, "research": research, "draft": draft, "run_id": run_id,
    }))])
    text, events, backend = await run_with_fallback(
        lambda b: build_deck_agent(backend=b), content, partial_on_timeout=True)
    info = find_tool_result(events, "make_deck")
    if info is None:
        print("Tool result not captured from events; calling shared build_deck directly.")
        info = make_deck(plan, research, draft, run_id)
    if not os.path.exists(info["deck_path"]):
        raise ValueError(f"deck file missing: {info['deck_path']}")
    return info, backend


if __name__ == "__main__":
    # Hello run: plan + research + draft from the shared calls, then the deck.
    plan = {
        "objective": DEFAULT_GOAL,
        "audience": "Operations and engineering leaders",
        "services": list(SERVICES),
        "outline": [
            "How Example Consulting guides organisations through their AI journey",
            "RAG and local inference",
            "Platforms and safe deployment",
        ],
    }
    docs = retrieve(DEFAULT_GOAL)
    research = [{"source": d["source"], "snippet": d["snippet"], "score": d.get("score")} for d in docs]
    synth = _generate(SYNTH_MODEL, synthesis_prompt(docs)).get("response", "").strip()
    research.append({"source": "synthesis", "snippet": synth, "score": None})
    draft = _generate(WRITER_MODEL, writer_prompt(plan, research)).get("response", "").strip()
    info, backend = asyncio.run(run_deck_once(plan, research, draft, "gate6-test"))
    print(f"backend: {backend}")
    print(json.dumps(info, indent=2))
