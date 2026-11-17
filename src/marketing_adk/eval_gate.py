"""ADK eval gate: the 9 checks on a draft + deck, wrapping the shared
scripts/eval_draft.py evaluate() — never the writer judging itself.
Plus the retry loop: eval fails -> writer again with the feedback -> deck
again -> eval again, max 2 attempts (same as the LangGraph graph).
The loop is app-orchestrated in Python (not an ADK LoopAgent): the
tool-calling agent loop is unreliable on qwen3, and the deterministic
stages belong in code. A LoopAgent is the ADK-native form to revisit
on Gemini, where the agent loop is reliable.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

from google.adk.tools import FunctionTool

from marketing_pipeline.config import DEFAULT_GOAL, SERVICES, SYNTH_MODEL, WRITER_MODEL
from marketing_pipeline.llm import _generate
from marketing_pipeline.retrieve import retrieve
from marketing_pipeline.rules import synthesis_prompt, writer_prompt
from .deck_tool import make_deck
from .writer import run_writer_once


def _load_evaluate():
    """Load scripts/eval_draft.py as a module (it is a standalone script,
    not a package) and return its evaluate() function."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "eval_draft.py"
    spec = importlib.util.spec_from_file_location("eval_draft", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


_EVALUATE = _load_evaluate()


def run_eval(draft: str, deck_path: str, n_docs: int) -> dict:
    """Run the 9 checks. Returns the report: passed, checks, coverage,
    cited numbers, feedback, deck slides checked."""
    return _EVALUATE(draft, Path(deck_path), n_docs)


EVAL_TOOL = FunctionTool(run_eval)


async def run_eval_loop(plan, research, draft, deck_info, run_id, max_attempts=2):
    """Eval -> (fail) writer with feedback -> deck -> eval, max attempts.
    Returns (draft, deck_info, report, attempts). The first eval uses the
    draft and deck handed in; a failure re-writes and re-builds once."""
    from marketing_pipeline.retrieve import DOCS_PREFIX
    n_docs = len([r for r in research if r["source"].startswith(DOCS_PREFIX)])
    attempts = 0
    report = None
    while attempts < max_attempts:
        attempts += 1
        report = run_eval(draft, deck_info["deck_path"], n_docs)
        print(f"Eval attempt {attempts}: passed={report['passed']} coverage={report['citation_coverage']}")
        if report["passed"]:
            return draft, deck_info, report, attempts
        if attempts >= max_attempts:
            break
        feedback = " ".join(report["feedback"])
        print(f"Eval failed, retrying the writer with feedback: {feedback}")
        draft, _backend = await run_writer_once(plan, research, feedback=feedback)
        deck_info = make_deck(plan, research, draft, run_id)
    return draft, deck_info, report, attempts


if __name__ == "__main__":
    # Hello run: plan + research + draft + deck from the shared calls,
    # then the gate both ways (good draft passes, sabotaged draft fails),
    # then the retry loop on the good draft (passes on attempt 1).
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
    deck_info = make_deck(plan, research, draft, "gate7-test")
    from marketing_pipeline.retrieve import DOCS_PREFIX
    n_docs = len([r for r in research if r["source"].startswith(DOCS_PREFIX)])
    good = run_eval(draft, deck_info["deck_path"], n_docs)
    print("GOOD DRAFT:", json.dumps(good, indent=2))
    sabotaged = draft.replace("[1]", "").replace("[2]", "").replace("[3]", "")
    bad = run_eval(sabotaged, deck_info["deck_path"], n_docs)
    print("SABOTAGED DRAFT:", json.dumps(bad, indent=2))
    final_draft, final_deck, report, attempts = asyncio.run(
        run_eval_loop(plan, research, draft, deck_info, "gate7-test"))
    print(f"LOOP: attempts={attempts} passed={report['passed']} deck={final_deck['deck_path']}")
