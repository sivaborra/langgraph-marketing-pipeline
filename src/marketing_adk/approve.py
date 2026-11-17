"""ADK approval + publish: the human gate, app-orchestrated.
ADK has no interrupt(), so the app asks the human between runner calls:
print the draft preview + deck path, read yes/no, then publish (shared
store helper) or reject. Nothing publishes without a yes.
"""

import os

from marketing_pipeline.config import DEFAULT_GOAL, SERVICES, SYNTH_MODEL, WRITER_MODEL
from marketing_pipeline.llm import _generate
from marketing_pipeline.retrieve import retrieve
from marketing_pipeline.rules import synthesis_prompt, writer_prompt
from marketing_pipeline.store import publish
from .deck_tool import make_deck


def ask_approval(draft, deck_path):
    """Print the approval question (draft preview + deck path) and read
    the human's answer. Returns the normalised answer ('yes'/'no')."""
    print("Approve publish to the LOCAL published/ folder only? (yes/no)")
    print(f"Deck: {deck_path}")
    print("Draft preview:")
    print((draft or "")[:500])
    answer = input("Approve? (yes/no): ").strip().lower()
    return answer


def run_approve_once(draft, deck_path, run_id, decision=None):
    """Approval gate. decision='yes' publishes, 'no' rejects. If decision
    is None, the human is asked. Returns the publish/reject outcome."""
    approved = (decision.strip().lower() if decision is not None
                else ask_approval(draft, deck_path))
    if approved == "yes":
        out_dir = publish(draft, deck_path, run_id)
        return {"published": True,
                "publish_targets": ["local published/ folder"],
                "status": "published",
                "out_dir": out_dir}
    return {"published": False, "status": "rejected"}


if __name__ == "__main__":
    # Hello run: build a draft + deck from the shared calls, then approve
    # once with yes (publishes) and once with no (rejects, nothing written).
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
    deck_info = make_deck(plan, research, draft, "gate8-test")
    deck_path = deck_info["deck_path"]
    yes = run_approve_once(draft, deck_path, "gate8-yes", decision="yes")
    print(f"YES: {yes}")
    assert yes["published"] and os.path.exists(os.path.join(yes["out_dir"], "draft.md"))
    assert os.path.exists(os.path.join(yes["out_dir"], os.path.basename(deck_path)))
    print(f"Published files verified in {yes['out_dir']}")
    no = run_approve_once(draft, deck_path, "gate8-no", decision="no")
    print(f"NO: {no}")
    assert not no["published"] and not os.path.exists(os.path.join("published", "gate8-no"))
    print("Rejection verified: no published/gate8-no folder was made.")
