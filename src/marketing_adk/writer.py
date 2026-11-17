"""ADK writer agent: write the draft from the plan and research, using the
shared writer prompt and rules. Same shape as the LangGraph writer: a
markdown draft with numeric citations, no banned phrases, >=200 chars.
"""

import asyncio
import re

from google.adk.agents import LlmAgent
from google.genai import types

from marketing_pipeline.config import BRAND_NAME, DEFAULT_GOAL, SYNTH_MODEL, WRITER_MODEL
from marketing_pipeline.llm import _generate
from marketing_pipeline.retrieve import retrieve
from marketing_pipeline.rules import BANNED_PHRASES, synthesis_prompt, writer_prompt
from .models import adk_model
from .runner import run_with_fallback


def build_writer_agent(backend=None):
    """Writer on the shared rules. The model writes; the shared prompt
    carries the citation and banned-phrase rules. No tools — writing only."""
    return LlmAgent(
        name="writer",
        model=adk_model("writer", backend, think=False),
        instruction=(
            f"You are the writer for {BRAND_NAME} marketing. Write a blog "
            "draft in markdown from the plan and research in the user message, "
            "using ONLY that research. Every brand sentence MUST end with a "
            "numeric citation like [1] or [2]. One claim per sentence, at most "
            "about 25 words. Never invent a client, a number, a result, or a "
            "service. Never use: guaranteed ROI, no risk, best-in-class, "
            "unlimited (for outcomes). End with a call to action saying the "
            "draft is for human review only and is NOT published, then a "
            "Sources section listing [1], [2], ... with their file names."
        ),
        tools=[],
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )


def _validate_draft(draft):
    """The writer's own checks (same as the LangGraph writer node):
    >=200 chars, no banned phrases, at least one numeric citation."""
    draft = (draft or "").strip()
    if len(draft) < 200:
        raise ValueError("writer draft too short")
    lowered = draft.lower()
    bad = [b for b in BANNED_PHRASES if b in lowered]
    if bad:
        raise ValueError(f"writer draft contains banned phrase(s): {bad}")
    if not re.search(r"\[\d+\]", draft):
        raise ValueError("writer draft contains no numeric citation")
    return draft


async def run_writer_once(plan, research, feedback=""):
    """Hello run: write the draft. Returns (draft, backend).
    If the agent produces no usable draft (loops, empty, or fails the
    checks), the draft comes from the shared plain call instead."""
    prompt = writer_prompt(plan, research, feedback)
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    text, events, backend = await run_with_fallback(
        lambda b: build_writer_agent(backend=b), content, partial_on_timeout=True)
    draft = (text or "").strip()
    try:
        draft = _validate_draft(draft)
        return draft, backend
    except ValueError as e:
        print(f"Agent draft unusable ({e}); using the shared plain call.")
        draft = _generate(WRITER_MODEL, prompt).get("response", "")
        draft = _validate_draft(draft)
        print("Draft from the shared plain call.")
        return draft, backend


if __name__ == "__main__":
    # Hello run: a small plan + research from the shared retrieve/synthesis.
    plan = {
        "objective": DEFAULT_GOAL,
        "audience": "Operations and engineering leaders",
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
    draft, backend = asyncio.run(run_writer_once(plan, research))
    print(f"backend: {backend}")
    print(f"draft chars: {len(draft)}")
    print(draft)
