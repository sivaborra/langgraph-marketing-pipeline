"""Pure eval function: the 9 marketing-draft checks, no graph state.

Moved verbatim from `evals_node` in `graph.py` (Gate 1). Same 9 checks,
same thresholds. `evaluate()` takes plain inputs so the MCP server can
call it without the graph: a remote caller has no deck file path, so it
passes deck slide bodies, not a path.
"""

import re

from .rules import BANNED_PHRASES, PII_PATTERNS


def evaluate(draft, research_docs, deck_bodies):
    """Check one draft. Returns checks, coverage, cited numbers, passed, feedback.

    draft: draft text (str).
    research_docs: research items already filtered to brand docs,
        each a dict with at least "source". Only the count is used.
    deck_bodies: deck slide bodies (list of str), for the 9th check.
    """
    n_docs = len(research_docs)
    cited = sorted(set(int(n) for n in re.findall(r"\[(\d+)\]", draft)))
    checks = {}
    checks["citations_present"] = len(cited) >= 1
    checks["citations_valid"] = all(1 <= n <= n_docs for n in cited)
    checks["all_docs_cited"] = set(cited) == set(range(1, n_docs + 1))
    checks["sources_section"] = "sources" in draft.lower()
    checks["banned_claims_zero"] = not any(b in draft.lower() for b in BANNED_PHRASES)
    checks["pii_zero"] = not any(re.search(p, draft) for p in PII_PATTERNS)
    checks["draft_length_ok"] = len(draft) >= 200
    # Citation coverage: share of long sentences that carry a citation.
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", draft) if len(s.strip()) > 40]
    cited_sentences = sum(1 for s in sentences if re.search(r"\[\d+\]", s))
    coverage = round(cited_sentences / len(sentences), 3) if sentences else 0.0
    checks["citation_coverage_ge_0_5"] = coverage >= 0.5
    checks["deck_slides_distinct"] = len(deck_bodies) >= 1 and len(set(deck_bodies)) == len(deck_bodies)
    passed = all(checks.values())
    feedback_parts = []
    if not checks["citations_valid"]:
        feedback_parts.append(f"Citations {cited} do not all map to the {n_docs} research docs; use only [1]..[{n_docs}].")
    if not checks["all_docs_cited"]:
        feedback_parts.append(f"Not all research docs are cited; cited={cited}, docs=1..{n_docs}.")
    if not checks["banned_claims_zero"]:
        feedback_parts.append("Draft contains a banned phrase; remove it.")
    if not checks["pii_zero"]:
        feedback_parts.append("Draft contains a PII-like pattern (email/phone/IBAN); remove it.")
    if not checks["citation_coverage_ge_0_5"]:
        feedback_parts.append(f"Citation coverage is {coverage} (need >= 0.5); cite more factual sentences.")
    if not checks["sources_section"]:
        feedback_parts.append("Draft is missing a Sources section.")
    if not checks["deck_slides_distinct"]:
        feedback_parts.append("Deck content slides are identical; each slide must carry its own draft section.")
    return {"checks": checks, "citation_coverage": coverage,
            "cited_numbers": cited, "n_docs": n_docs, "passed": passed,
            "feedback": "; ".join(feedback_parts),
            "deck_slides_checked": len(deck_bodies)} 
