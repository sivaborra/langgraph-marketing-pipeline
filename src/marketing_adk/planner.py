"""ADK planner agent: the shared planner prompt as an LlmAgent.

The instruction IS the shared prompt - the same words the LangGraph
planner node sends to Ollama. Only the model differs: Gemini first,
local Ollama as fallback when Google is down.
"""

import asyncio
import json
import re

from google.adk.agents import LlmAgent
from google.genai import types

from marketing_pipeline.config import DEFAULT_AUDIENCE, DEFAULT_GOAL, SERVICES
from marketing_pipeline.rules import planner_prompt
from .models import adk_model
from .runner import run_with_fallback


def build_planner_agent(goal=DEFAULT_GOAL, audience=DEFAULT_AUDIENCE, wanted=None, backend=None):
    """Planner agent on the shared prompt. Backend 'gemini' (default) or
    'ollama'; the words are the same ones the LangGraph planner sends."""
    return LlmAgent(
        name="planner",
        model=adk_model("planner", backend),
        instruction=planner_prompt(goal, audience, wanted),
        generate_content_config=types.GenerateContentConfig(temperature=0),
    )


async def run_planner_once(goal=DEFAULT_GOAL, audience=DEFAULT_AUDIENCE, wanted=None):
    """Hello run: Gemini first, local Ollama fallback when Google is down.
    Returns (plan dict, backend that served it)."""
    content = types.Content(role="user", parts=[types.Part(text="Return the plan.")])
    text, events, backend = await run_with_fallback(
        lambda b: build_planner_agent(goal, audience, wanted, backend=b), content)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"planner did not return JSON (backend: {backend}). Raw reply:\n{text}")
    return json.loads(match.group(0)), backend


if __name__ == "__main__":
    plan, backend = asyncio.run(run_planner_once())
    print(f"backend: {backend}")
    print(json.dumps(plan, indent=2))
