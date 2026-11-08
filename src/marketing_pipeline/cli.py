"""CLI for the marketing pipeline: run a draft, then approve or reject it.

Two phases, same thread id — the run pauses at the approval interrupt
and only resumes when a human answers:

    python -m marketing_pipeline.cli run <thread-id>
    python -m marketing_pipeline.cli approve <thread-id> yes|no

Fresh checkpoint DB for a clean demo: rm -f step7.db before the first run.
"""

import os
import sys

from langgraph.types import Command

from .config import BRAND_NAME, DEFAULT_AUDIENCE, DEFAULT_GOAL, SERVICES
from .graph import app, safe_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    stage = argv[0] if len(argv) > 0 else "run"
    thread = argv[1] if len(argv) > 1 else "demo"
    answer = argv[2] if len(argv) > 2 else "yes"
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
