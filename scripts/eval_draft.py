#!/usr/bin/env python3
"""Standalone eval gate for the marketing pipeline (gh-aw port).

The SAME 9 checks as evals_node in src/marketing_pipeline/graph.py
(and phase2_step7_v2.py on AIBeast), as plain code — never the writer
judging itself. The gh-aw marketing-draft workflow runs this script;
a human still approves the draft PR before anything publishes.

Checks (names identical to the graph):
  citations_present, citations_valid, all_docs_cited, sources_section,
  banned_claims_zero, pii_zero, draft_length_ok,
  citation_coverage_ge_0_5, deck_slides_distinct.

Citations [1]..[n] map to the retrieved source docs, in order.
Pass the docs the writer was told to cite with --sources, or a
knowledge-base dir with --kb (takes the first --top-k .md files,
sorted — mirroring the graph's retrieve top-3).

Usage:
  python scripts/eval_draft.py --draft drafts/run-abc/draft.md \
      --deck drafts/run-abc/deck-run-abc.pptx --kb knowledge_base
  python scripts/eval_draft.py --draft d.md --deck d.pptx \
      --sources knowledge_base/positioning.md knowledge_base/services-ai.md

Exit 0 = all 9 checks pass. Exit 1 = at least one fails.
Prints a JSON report (checks, coverage, cited numbers, feedback).
"""

import argparse
import json
import re
import sys
from pathlib import Path

BANNED_PHRASES = ["guaranteed roi", "no risk", "best-in-class", "unlimited"]

PII_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",  # email-like
    r"\b\d{3}[- ]\d{3}[- ]\d{4}\b",  # phone-like
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",  # IBAN-like
]


def deck_slide_bodies(deck_path):
    """Body text of each content slide (skips title + closing slides).

    Title text is EXCLUDED on purpose: titles always differ, so including
    them would let identical bodies pass. Only the body paragraphs count.
    Returns [] when the deck cannot be read — the check then fails
    instead of crashing the run.
    """
    try:
        from pptx import Presentation
        prs = Presentation(str(deck_path))
        bodies = []
        for slide in list(prs.slides)[1:-1]:
            title = slide.shapes.title
            parts = []
            for sh in slide.shapes:
                if title is not None and sh.shape_id == title.shape_id:
                    continue
                if sh.has_text_frame:
                    parts.append(sh.text_frame.text)
            bodies.append("\n".join(parts))
        return bodies
    except Exception:
        return []


def evaluate(draft_text, deck_path, n_docs):
    draft = draft_text or ""
    cited = sorted(set(int(n) for n in re.findall(r"\[(\d+)\]", draft)))
    checks = {}
    checks["citations_present"] = len(cited) >= 1
    checks["citations_valid"] = all(1 <= n <= n_docs for n in cited)
    checks["all_docs_cited"] = set(cited) == set(range(1, n_docs + 1))
    checks["sources_section"] = "sources" in draft.lower()
    checks["banned_claims_zero"] = not any(b in draft.lower() for b in BANNED_PHRASES)
    checks["pii_zero"] = not any(re.search(p, draft) for p in PII_PATTERNS)
    checks["draft_length_ok"] = len(draft) >= 200
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", draft) if len(s.strip()) > 40]
    cited_sentences = sum(1 for s in sentences if re.search(r"\[\d+\]", s))
    coverage = round(cited_sentences / len(sentences), 3) if sentences else 0.0
    checks["citation_coverage_ge_0_5"] = coverage >= 0.5
    deck_bodies = deck_slide_bodies(deck_path)
    checks["deck_slides_distinct"] = len(deck_bodies) >= 1 and len(set(deck_bodies)) == len(deck_bodies)

    feedback = []
    if not checks["citations_valid"]:
        feedback.append(
            f"Citations {cited} do not all map to the {n_docs} research docs; "
            f"use only [1]..[{n_docs}]."
        )
    if not checks["all_docs_cited"]:
        feedback.append(
            f"Not all research docs are cited; cited={cited}, docs=1..{n_docs}."
        )
    if not checks["banned_claims_zero"]:
        feedback.append("Draft contains a banned phrase; remove it.")
    if not checks["pii_zero"]:
        feedback.append("Draft contains a PII-like pattern (email/phone/IBAN); remove it.")
    if not checks["citation_coverage_ge_0_5"]:
        feedback.append(
            f"Citation coverage is {coverage} (need >= 0.5); cite more factual sentences."
        )
    if not checks["sources_section"]:
        feedback.append("Draft is missing a Sources section.")
    if not checks["deck_slides_distinct"]:
        feedback.append("Deck content slides are identical; each slide must carry its own draft section.")

    return {
        "checks": checks,
        "citation_coverage": coverage,
        "cited_numbers": cited,
        "n_docs": n_docs,
        "passed": all(checks.values()),
        "feedback": feedback,
        "deck_slides_checked": len(deck_bodies),
    }


def main():
    parser = argparse.ArgumentParser(description="Eval gate: 9 checks on a marketing draft + deck.")
    parser.add_argument("--draft", required=True, help="Path to draft.md")
    parser.add_argument("--deck", required=True, help="Path to the .pptx deck")
    parser.add_argument("--sources", nargs="*", default=[],
                        help="Source docs the writer was told to cite, in citation order")
    parser.add_argument("--kb", help="Knowledge-base dir (sorted .md files, first --top-k)")
    parser.add_argument("--top-k", type=int, default=3,
                        help="How many KB docs count as retrieved sources (default 3)")
    args = parser.parse_args()

    if args.sources:
        sources = [Path(s) for s in args.sources]
    elif args.kb:
        sources = sorted(Path(args.kb).glob("*.md"))[: args.top_k]
    else:
        parser.error("give --sources or --kb")
    n_docs = len(sources)
    if n_docs == 0:
        print(json.dumps({"passed": False, "feedback": ["No source docs found."]}, indent=2))
        return 1

    draft_text = Path(args.draft).read_text(encoding="utf-8")
    report = evaluate(draft_text, Path(args.deck), n_docs)
    report["sources"] = [str(s) for s in sources]
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
