"""CLI for the marketing pipeline: run a draft, then approve or reject it.

Two engines, one CLI. Pick with --engine (default langgraph):

    python -m marketing_pipeline.cli run <thread-id> [--engine langgraph]
    python -m marketing_pipeline.cli approve <thread-id> yes|no [--engine langgraph]
    python -m marketing_pipeline.cli run <thread-id> --engine adk [yes|no]

LangGraph (default): two phases, same thread id — the run pauses at the
approval interrupt and only resumes when a human answers. Fresh checkpoint
DB for a clean demo: rm -f step7.db before the first run.

ADK: one phase — the run does planner -> researcher -> writer -> deck ->
eval loop, then asks the human for approval and publishes or rejects.
Give yes/no as the third argument to skip the prompt (scripts/tests);
omit it to be asked. There is no checkpoint/resume on the ADK path.
"""

import asyncio
import os
import sys

from langgraph.types import Command

from .config import BRAND_NAME, DEFAULT_AUDIENCE, DEFAULT_GOAL, SERVICES
from .graph import app, safe_json


def _parse_engine(argv):
    """Pull --engine <name> out of argv (default langgraph). Returns
    (engine, remaining argv)."""
    argv = list(argv)
    engine = "langgraph"
    if "--engine" in argv:
        i = argv.index("--engine")
        if i + 1 < len(argv):
            engine = argv[i + 1].lower()
            del argv[i:i + 2]
        else:
            del argv[i]
    if engine not in ("langgraph", "adk"):
        raise SystemExit("--engine must be 'langgraph' or 'adk'")
    return engine, argv


def _run_adk(thread, decision):
    """The ADK path: full pipeline in one go, approval at the end."""
    from marketing_adk.pipeline import run_adk_pipeline
    result = asyncio.run(run_adk_pipeline(
        goal=DEFAULT_GOAL, audience=DEFAULT_AUDIENCE,
        run_id=thread, decision=decision))
    print(safe_json({k: v for k, v in result.items()
                     if k in ("deck", "eval", "attempts", "published", "status")}))
    if result.get("status") == "published":
        print("\nGATE (yes): PASS — human approved, local publish only, status published.")
    elif result.get("status") == "rejected":
        print("\nGATE (no): PASS — human rejected, nothing published, status rejected.")
    elif result.get("status") == "eval_failed":
        print("\nGATE: FAIL — eval did not pass after max attempts, nothing published.")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    engine, argv = _parse_engine(argv)
    stage = argv[0] if len(argv) > 0 else "run"
    thread = argv[1] if len(argv) > 1 else "demo"
    answer = argv[2] if len(argv) > 2 else "yes"
    if engine == "adk":
        if stage == "run":
            decision = answer if len(argv) > 2 else None
            _run_adk(thread, decision)
        elif stage == "approve":
            raise SystemExit("ADK is single-phase: approval happens inside the run, "
                             "so there is no separate approve step. Re-run with "
                             f"'run {thread} --engine adk'.")
        else:
            raise SystemExit("stage must be 'run' or 'approve'")
        return
    cfg = {"configurable": {"thread_id": thread}}
    if stage == "run":
        result = app.invoke({
            "run_id": thread,
            "brand": BRAND_NAME,
            "audience": DEFAULT_AUDIENCE,
            "goal": DEFAULT_GOAL,
            "inputs": {"services": list(SERVICES)},
        }, cfg)
        st = app.get_state(cfg)
        print(safe_json(result))
        print("\nPAUSED at approve. Next nodes:", st.next)
        print(f"Resume with: python -m marketing_pipeline.cli approve {thread} yes   (or no)")
        print("Gate for this phase: run paused at approve, approved still None, published False.")
    elif stage == "approve":
        result = app.invoke(Command(resume=answer), cfg)
        print(safe_json(result))
        if answer.lower() == "yes":
            assert result["approved"] == "yes", "approved is not yes"
            assert result["published"] is True, "publish did not happen on yes"
            assert result["status"] == "published", "status is not published"
            assert os.path.exists(os.path.join("published", thread, "draft.md")), "published draft file missing"
            print("\nGATE (yes): PASS — human approved, local publish only, status published.")
        else:
            assert result["approved"] == "no", "approved is not no"
            assert result["published"] is False, "something published on no — that must never happen"
            assert result["status"] == "rejected", "status is not rejected"
            assert not os.path.exists(os.path.join("published", thread, "draft.md")), "published file exists after no"
            print("\nGATE (no): PASS — human rejected, nothing published, status rejected.")
    else:
        raise SystemExit("stage must be 'run' or 'approve'")


if __name__ == "__main__":
    main()
