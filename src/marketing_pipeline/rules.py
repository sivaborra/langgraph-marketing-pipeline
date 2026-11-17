"""Shared rules: the constraints both paths must obey.

One source of truth - if a rule changes here, both engines change.
The prompt builders join this file in a later step.
"""
from .config import BRAND_NAME, SERVICES
from .retrieve import DOCS_PREFIX


def planner_prompt(goal, audience, wanted=None):
    """Shared planner prompt: the exact prompt the LangGraph planner node
    sends, reused as the ADK planner agent's instruction. One source of
    truth - if the prompt changes here, both engines change."""
    wanted = list(wanted) if wanted else list(SERVICES)
    return (
        f"You are the planner for {BRAND_NAME} marketing.\n"
        f"{BRAND_NAME} guides organisations through their AI journey, "
        "deploying AI agents safely. It is not a freelancer.\n"
        f"Goal: {goal}\nAudience: {audience}\n"
        f"Services the caller asked about: {', '.join(wanted)}\n"
        "Allowed services (use ONLY these, never invent one, never name a client):\n"
        + "\n".join(f"- {s}" for s in SERVICES)
        + "\n\nReturn ONLY this JSON, no other text:\n"
        '{"objective": "...", "audience": "...", '
        '"services": ["..."], "channel_mix": ["blog draft", "LinkedIn draft", '
        '"presentation deck outline"], "kpis": ["..."], "outline": ["..."]}\n'
        "Rules: kpis must include 'draft ready for human review (not published)' "
        "and '0 banned claims'. Outline must have 4-6 items. Outline items are "
        "slide headlines: short, at most 45 characters each, headline-style, "
        "no trailing filler (e.g. 'Safe AI automation for small teams', not "
        "'Introduction to the company and its role in AI journey guidance')."
    )

BANNED_PHRASES = ["guaranteed roi", "no risk", "best-in-class", "unlimited"]

PII_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",  # email-like
    r"\b\d{3}[- ]\d{3}[- ]\d{4}\b",  # phone-like
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",  # IBAN-like
]
SYNTHESIS_INSTRUCTION = (
    f"Summarise ONLY what the retrieved {BRAND_NAME} docs say, "
    "for the marketing plan. Do not add facts, clients, numbers or "
    "claims that are not in the docs. If a doc does not cover a "
    "point, say so instead of inventing it."
)


def synthesis_prompt(candidates):
    """Shared synthesis prompt: the exact prompt the LangGraph synthesis
    node sends, built from the retrieved candidates."""
    context = "\n\n".join(
        f"[{c['source']} | score {c['score']}] {c['snippet']}" for c in candidates)
    return (
        f"{SYNTHESIS_INSTRUCTION}\n\n"
        f"Retrieved docs:\n{context}\n\n"
        "Return 3-5 short bullet lines, each starting with its source "
        "file name, e.g. '- services-ai.md: ...'"
    )



def writer_prompt(plan, research, feedback=""):
    """Shared writer prompt: the exact prompt the LangGraph writer node
    sends, built from the plan and the numbered brand-doc research.
    The synthesis entry is not a source, so it is excluded."""
    docs = [r for r in research if r["source"].startswith(DOCS_PREFIX)]
    numbered = "\n".join(
        f"[{i+1}] {r['source']}: {r['snippet']}" for i, r in enumerate(docs))
    feedback_block = (
        f"\n\nPrevious draft FAILED eval for these reasons, fix all of them "
        f"in this revision and do not repeat them:\n{feedback}\n"
        if feedback else "")
    return (
        f"You are the writer for {BRAND_NAME} marketing. Write a blog draft "
        "in markdown, following this outline, using ONLY the research below.\n\n"
        f"Objective: {plan['objective']}\n"
        f"Audience: {plan['audience']}\n"
        f"Outline:\n" + "\n".join(f"- {o}" for o in plan["outline"]) + "\n\n"
        f"Research (cite these, and only these, by number):\n{numbered}\n\n"
        "Rules, all mandatory:\n"
        "1. CITATION RULE (strict): EVERY sentence that states something about "
        "the brand, its services, its approach, or its market MUST end with a "
        "numeric citation like [1] or [2] that points to the research list "
        "above. No brand sentence without a citation, no exceptions.\n"
        "2. ONE CLAIM PER SENTENCE: keep factual sentences short, at most "
        "about 25 words each, so each one can carry its citation cleanly. "
        "Do not pack three claims into one long uncited sentence.\n"
        "3. REPEAT CITATIONS: cite the same source again in each new paragraph "
        "and each new section. Citing once at the start and then writing "
        "uncited paragraphs afterwards is a failure.\n"
        "4. Keep purely structural text to a minimum: headings, and at most "
        "two short intro sentences. Do not write a long uncited introduction "
        "or conclusion.\n"
        "5. Never invent a client, a number, a result, or a service.\n"
        "6. Never use these banned phrases: guaranteed ROI, no risk, "
        "best-in-class, unlimited (for outcomes).\n"
        "7. End with a call to action that says the draft is for human "
        "review only and is NOT published.\n"
        "8. End the draft with a 'Sources' section listing [1], [2], ... "
        "with their source file names.\n"
        "9. NO REPEATED CLAIMS: each paragraph must make a different point. "
        "Do not restate a claim from another paragraph in different words. "
        "If one paragraph covers containers, Kubernetes and Docker, no other "
        "paragraph may cover them; if one paragraph states the positioning, "
        "no other paragraph may repeat it."
        + feedback_block
    )
