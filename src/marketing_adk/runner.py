"""Shared ADK run helpers: one agent call, fallback, tool results.

Every ADK agent in this package runs through here, so the timeout,
the Gemini-first/Ollama-fallback chain and the tool-result capture
exist once, not once per agent.
"""

import asyncio
import os

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.errors import ClientError, ServerError

async def _collect(runner, user_id, session_id, content, events):
    """Collect the event stream. Events go into the passed-in list so they
    survive a timeout/cancellation (the caller may still use a tool result)."""
    text = ""
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        events.append(event)
        # One line per event, printed as it arrives, so a mid-run abort
        # still shows how far the run got (tool call? tool result? text?).
        if event.content and event.content.parts:
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                fr = getattr(part, "function_response", None)
                t = getattr(part, "text", None)
                if fc is not None:
                    print(f"[event] tool call: {fc.name} args={fc.args}")
                elif fr is not None:
                    print(f"[event] tool result: {fr.name}")
                elif t:
                    print(f"[event] text ({len(t)} chars): {t[:150]!r}")
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts)
    return text


async def run_agent_once(agent, content, timeout=120, partial_on_timeout=False):
    """One agent call, failing fast: timeout, no silent hang.
    Returns (final text, all events). With partial_on_timeout=True, a
    timeout returns the events collected so far instead of raising —
    for an agent that loops on tool calls, the tool result is still usable."""
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="marketing_adk", session_service=session_service)
    session = await session_service.create_session(app_name="marketing_adk", user_id="siva")
    events = []
    try:
        text = await asyncio.wait_for(
            _collect(runner, "siva", session.id, content, events), timeout=timeout)
        return text, events
    except TimeoutError:
        if not partial_on_timeout:
            raise
        print(f"Agent timed out after {timeout}s — using the events so far ({len(events)}).")
        return "", events


async def run_with_fallback(make_agent, content, timeout=120, partial_on_timeout=False):
    """Gemini first, local Ollama fallback when Google is down.
    make_agent(backend) builds the agent. Returns (text, events, backend).
    'Down' means 5xx, timeout, or a 429 quota/rate-limit (ClientError with
    code 429). Any other 4xx (400/401/403) is a real problem and re-raises.
    partial_on_timeout applies to the Ollama leg only."""
    if os.environ.get("ADK_MODEL_BACKEND", "gemini").lower() == "ollama":
        # Ollama-only run (e.g. Gemini quota exhausted): skip Gemini entirely.
        text, events = await run_agent_once(
            make_agent("ollama"), content, timeout, partial_on_timeout=partial_on_timeout)
        return text, events, "ollama"
    try:
        text, events = await run_agent_once(make_agent("gemini"), content, timeout)
        return text, events, "gemini"
    except (ServerError, TimeoutError, ClientError) as e:
        if isinstance(e, ClientError) and getattr(e, "code", None) != 429:
            raise
        print(f"Gemini down ({type(e).__name__}), falling back to local Ollama.")
        text, events = await run_agent_once(
            make_agent("ollama"), content, timeout, partial_on_timeout=partial_on_timeout)
        return text, events, "ollama"


def find_tool_result(events, name):
    """The return value of a named tool call, from the event stream.
    Tolerant of ADK's two response shapes (raw value, or {'result': ...})."""
    for event in events:
        parts = (event.content.parts if event.content else None) or []
        for part in parts:
            resp = getattr(part, "function_response", None)
            if resp is not None and getattr(resp, "name", None) == name:
                result = resp.response
                if isinstance(result, dict) and "result" in result:
                    return result["result"]
                return result
    return None
