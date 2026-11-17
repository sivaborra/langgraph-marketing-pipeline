"""ADK pipeline: chain the gates into one run.
planner -> researcher -> writer -> deck -> eval loop -> approve.
One async function, so the CLI can run the whole ADK path in one go.
"""

import asyncio
import sys

from marketing_pipeline.config import DEFAULT_AUDIENCE, DEFAULT_GOAL
from .approve import run_approve_once
from .deck_tool import run_deck_once
from .eval_gate import run_eval_loop
from .planner import run_planner_once
from .researcher import run_researcher_once
from .writer import run_writer_once


async def run_adk_pipeline(goal=DEFAULT_GOAL, audience=DEFAULT_AUDIENCE,
                           run_id="demo", decision=None):
    """Run the full ADK path. decision='yes'/'no' skips the human prompt
    (for scripts/tests); None asks the human at the approval step.
    Returns a result dict with the plan, research, draft, deck, eval
    report, attempts and publish outcome."""
    plan, plan_backend = await run_planner_once(goal, audience)
    print(f"[planner] backend: {plan_backend}")
    research, research_backend = await run_researcher_once(query=goal)
    print(f"[researcher] backend: {research_backend} docs: {len(research)}")
    draft, writer_backend = await run_writer_once(plan, research)
    print(f"[writer] backend: {writer_backend} draft chars: {len(draft)}")
    deck_info, deck_backend = await run_deck_once(plan, research, draft, run_id)
    print(f"[deck] backend: {deck_backend} deck: {deck_info['deck_path']} slides: {deck_info['deck_slides']}")
    draft, deck_info, report, attempts = await run_eval_loop(plan, research, draft, deck_info, run_id)
    print(f"[eval] attempts: {attempts} passed: {report['passed']}")
    if not report["passed"]:
        print("Eval did not pass after max attempts; nothing publishes.")
        return {"plan": plan, "research": research, "draft": draft,
                "deck": deck_info, "eval": report, "attempts": attempts,
                "published": False, "status": "eval_failed"}
    outcome = run_approve_once(draft, deck_info["deck_path"], run_id, decision=decision)
    print(f"[approve] {outcome}")
    return {"plan": plan, "research": research, "draft": draft,
            "deck": deck_info, "eval": report, "attempts": attempts,
            **outcome}


if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else "demo"
    decision = sys.argv[2] if len(sys.argv) > 2 else None
    result = asyncio.run(run_adk_pipeline(run_id=run_id, decision=decision))
    print(f"status: {result.get('status')} published: {result.get('published')}")
