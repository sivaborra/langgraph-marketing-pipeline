"""Marketing content pipeline: planner -> researcher -> writer -> deck -> evals -> human approval -> local publish.

Graph: START -> planner -> researcher -> writer -> deck -> evals --(fail, <2 attempts)--> writer;
evals --(pass)--> approve; evals --(fail, >=2 attempts)--> END.

Researcher subgraph: retrieve -> synthesise.
- retrieve: bge-m3 embeddings (Ollama /api/embeddings, no vector DB,
  cosine similarity in plain Python) over the markdown docs in
  knowledge_base/ only.
- synthesise: qwen3:8b, temperature 0. Synthesis summarises retrieved
  docs; it is not planning, so 8b is the cheapest-first choice here.

Knowledge base:
- On first run the pipeline writes the bundled sample docs into
  knowledge_base/ (see config.SAMPLE_DOCS). Replace them with your own
  brand docs and re-run — the retrieval code does not change. No client
  docs, no client names in the shipped samples.
- Nothing publishes without human approval, and publish is local only
  (a published/ folder). No LinkedIn, no WordPress, no external call.

Models (defaults, overridable by environment — see config.py):
planner qwen3:14b, synthesis qwen3:8b, writer qwen3:14b, embeddings bge-m3.
All calls go to a local Ollama server (OLLAMA_BASE_URL, default
http://localhost:11434). No cloud model, no API key.

Eval gate (9 checks, plain code — never the writer judging itself):
citations_present, citations_valid, all_docs_cited, sources_section,
banned_claims_zero, pii_zero, draft_length_ok, citation_coverage_ge_0_5,
deck_slides_distinct. Max 2 attempts, then the run ends unpublished.

Run:
    python -m marketing_pipeline.cli run <thread-id>
    python -m marketing_pipeline.cli approve <thread-id> yes|no
"""

import json
import re
import sqlite3
import urllib
import time
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from .config import (
    BRAND_NAME,
    CHECKPOINT_DB,
    EMBED_MODEL,
    PLANNER_MODEL,
    SERVICES,
    SYNTH_MODEL,
    WRITER_MODEL,
)
from .deck import _deck_slide_bodies, build_deck
from .llm import _generate
from .retrieve import DOCS_PREFIX, retrieve
from .rules import BANNED_PHRASES, PII_PATTERNS, planner_prompt, synthesis_prompt, writer_prompt
from .store import publish


# ---- Planner (unchanged from Step 2) ----

class Plan(TypedDict):
    objective: str
    audience: str
    services: list
    channel_mix: list
    kpis: list
    outline: list


class MarketingState(TypedDict, total=False):
    run_id: str
    brand: str
    audience: str
    goal: str
    inputs: dict
    plan: Plan
    outline: list
    research: list
    draft: str
    deck_path: str
    deck_slides: int
    deck_fallback_slides: list
    evals: dict
    approved: str
    publish_targets: list
    published: bool
    costs: dict
    planner_source: str
    synthesis_source: str
    writer_source: str
    eval_attempts: int
    eval_feedback: str
    status: str
    error: str


def _extract_json(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model did not return a JSON object")
    return json.loads(text[start:end + 1])


def planner_node(state: MarketingState):
    goal, audience = state["goal"], state["audience"]
    wanted = state.get("inputs", {}).get("services", SERVICES)
    prompt = planner_prompt(goal, audience, wanted)
    started = time.time()
    data = _generate(PLANNER_MODEL, prompt)
    plan_raw = _extract_json(data.get("response", ""))
    # Normalise the model's services to SERVICES. The model sometimes
    # returns a split or shortened name instead of the exact entry — an
    # exact-match filter then emptied the list and the run died with
    # "model returned no allowed service" (5 Nov 2026). A returned name
    # maps to an allowed entry when it matches exactly, or when it is a
    # case-insensitive part of one (either direction).
    def _normalise_service(name):
        n = str(name).strip()
        if n in SERVICES:
            return n
        low = n.lower()
        for allowed in SERVICES:
            a = allowed.lower()
            if low in a or a in low:
                return allowed
        return None
    services = []
    for s in plan_raw.get("services", []):
        mapped = _normalise_service(s)
        if mapped and mapped not in services:
            services.append(mapped)
    if not services:
        raise ValueError("model returned no allowed service")
    plan: Plan = {
        "objective": str(plan_raw.get("objective") or goal),
        "audience": str(plan_raw.get("audience") or audience),
        "services": services,
        "channel_mix": list(plan_raw.get("channel_mix") or []),
        "kpis": list(plan_raw.get("kpis") or []),
        "outline": list(plan_raw.get("outline") or []),
    }
    if not (plan["channel_mix"] and plan["kpis"] and plan["outline"]):
        raise ValueError("model plan is missing channel_mix, kpis or outline")
    return {
        "plan": plan,
        "outline": plan["outline"],
        "status": "plan_ready",
        "approved": None,
        "published": False,
        "planner_source": f"ollama:{PLANNER_MODEL}",
        "costs": {"planner": {
            "model": PLANNER_MODEL,
            "prompt_tokens": data.get("prompt_eval_count"),
            "output_tokens": data.get("eval_count"),
            "duration_s": round(time.time() - started, 1),
            "cost_sek": 0,
        }},
    }


# ---- Researcher subgraph: retrieve -> synthesise ----

class ResearchState(TypedDict, total=False):
    query: str
    candidates: list
    research: list
    synthesis_duration_s: float  # FIX from Step 3: this field was missing, so duration came back null


def retrieve_node(state: ResearchState):
    return {"candidates": retrieve(state["query"])}

def synthesise_node(state: ResearchState):
    cands = state["candidates"]
    prompt = synthesis_prompt(cands)
    started = time.time()
    data = _generate(SYNTH_MODEL, prompt)
    research = []
    for c in cands:
        research.append({"source": c["source"], "snippet": c["snippet"],
                         "score": c["score"]})
    research.append({"source": "synthesis", "snippet": data.get("response", "").strip(),
                     "score": None})
    return {"research": research,
            "synthesis_duration_s": round(time.time() - started, 1)}


sub = StateGraph(ResearchState)
sub.add_node("retrieve", retrieve_node)
sub.add_node("synthesise", synthesise_node)
sub.add_edge(START, "retrieve")
sub.add_edge("retrieve", "synthesise")
sub.add_edge("synthesise", END)
researcher_app = sub.compile()


def researcher_node(state: MarketingState):
    plan = state["plan"]
    query = " ".join(plan["services"] + plan["outline"])
    out = researcher_app.invoke({"query": query})
    costs = dict(state.get("costs") or {})
    costs["researcher"] = {
        "embed_model": EMBED_MODEL,
        "synthesis_model": SYNTH_MODEL,
        "synthesis_duration_s": out.get("synthesis_duration_s"),
        "cost_sek": 0,
    }
    return {"research": out["research"],
            "synthesis_source": f"ollama:{SYNTH_MODEL}",
            "costs": costs,
            "status": "research_ready"}



# ---- Writer node: draft with numeric citations bound to research ----

BANNED_PHRASES = ["guaranteed roi", "no risk", "best-in-class", "unlimited"]

def writer_node(state: MarketingState):
    plan = state['plan']
    feedback = state.get('eval_feedback') or ''
    prompt = writer_prompt(plan, state['research'], feedback)
    started = time.time()
    data = _generate(WRITER_MODEL, prompt)
    draft = data.get("response", "").strip()
    if len(draft) < 200:
        raise ValueError("writer draft too short")
    lowered = draft.lower()
    bad = [b for b in BANNED_PHRASES if b in lowered]
    if bad:
        raise ValueError(f"writer draft contains banned phrase(s): {bad}")
    if not re.search(r"\[\d+\]", draft):
        raise ValueError("writer draft contains no numeric citation")
    costs = dict(state.get("costs") or {})
    costs["writer"] = {
        "model": WRITER_MODEL,
        "prompt_tokens": data.get("prompt_eval_count"),
        "output_tokens": data.get("eval_count"),
        "duration_s": round(time.time() - started, 1),
        "cost_sek": 0,
    }
    return {"draft": draft,
            "writer_source": f"ollama:{WRITER_MODEL}",
            "costs": costs,
            "status": "draft_ready"}



# ---- Evals node: external CODE checks, never the writer judging itself ----

PII_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",  # email-like
    r"\b\d{3}[- ]\d{3}[- ]\d{4}\b",  # phone-like
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",  # IBAN-like
]

def evals_node(state: MarketingState):
    draft = state["draft"]
    docs = [r for r in state["research"] if r["source"].startswith(DOCS_PREFIX)]
    n_docs = len(docs)
    cited = sorted(set(int(n) for n in re.findall(r"\[(\d+)\]", draft)))
    checks = {}
    checks["citations_present"] = len(cited) >= 1
    checks["citations_valid"] = all(1 <= n <= n_docs for n in cited)
    checks["all_docs_cited"] = set(cited) == set(range(1, n_docs + 1))
    checks["sources_section"] = "sources" in draft.lower()
    checks["banned_claims_zero"] = not any(b in draft.lower() for b in BANNED_PHRASES)
    checks["pii_zero"] = not any(re.search(p, draft) for p in PII_PATTERNS)
    checks["draft_length_ok"] = len(draft) >= 200
    # Citation coverage, simple and honest: share of long sentences that carry a citation.
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", draft) if len(s.strip()) > 40]
    cited_sentences = sum(1 for s in sentences if re.search(r"\[\d+\]", s))
    coverage = round(cited_sentences / len(sentences), 3) if sentences else 0.0
    checks["citation_coverage_ge_0_5"] = coverage >= 0.5
    # 9th check (5 Nov 2026, Siva's finding): the DECK must differ slide to
    # slide. The old gate only ever looked at the draft, so a deck with
    # identical content on every slide passed. The deck is built before evals
    # now, so it can be read here. A deck that cannot be read fails, loudly.
    deck_bodies = _deck_slide_bodies(state.get("deck_path") or "")
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
    attempts = int(state.get("eval_attempts") or 0) + 1
    evals = {"checks": checks, "citation_coverage": coverage,
             "cited_numbers": cited, "n_docs": n_docs, "passed": passed,
             "attempts": attempts, "deck_slides_checked": len(deck_bodies)}
    status = "eval_passed" if passed else ("eval_failed" if attempts >= 2 else "eval_retry")
    return {"evals": evals, "eval_attempts": attempts,
            "eval_feedback": "; ".join(feedback_parts),
            "status": status}


def route_after_evals(state: MarketingState):
    # Pass -> approve. Fail with attempts left -> writer (which rewrites the
    # draft; deck rebuilds from it on the way back through). Fail at 2 -> END,
    # no publish (a deck file may exist in outputs/, but it is not approved).
    if state["evals"]["passed"]:
        return "approve"
    if int(state.get("eval_attempts") or 0) >= 2:
        return "end"
    return "writer"


def deck_node(state: MarketingState):
    plan = state["plan"]
    deck_path, deck_slides, fallback_slides = build_deck(
        plan, state["research"], state.get("draft") or "", state.get("run_id", "demo"))
    return {"deck_path": deck_path,
            "deck_slides": deck_slides,
            "deck_fallback_slides": fallback_slides,
            "status": "deck_ready"}

# ---- Approval interrupt + local publish (NOT real LinkedIn/WordPress) ----

def approve_node(state: MarketingState):
    # This node PAUSES at interrupt(). The run resumes only when a human
    # answers via Command(resume="yes") or Command(resume="no") with the
    # same thread_id. Nothing publishes without that answer.
    answer = interrupt({
        "question": "Approve publish to the LOCAL published/ folder only? (yes/no)",
        "deck_path": state.get("deck_path"),
        "draft_preview": (state.get("draft") or "")[:500],
    })
    return {"approved": str(answer).strip().lower()}


def publish_node(state: MarketingState):
    publish(state["draft"], state.get("deck_path"), state.get("run_id", "demo"))
    return {"published": True,
            "publish_targets": ["local published/ folder"],
            "status": "published"}

def rejected_node(state: MarketingState):
    # Human said no: nothing is published, and no published/ file is made.
    return {"published": False, "status": "rejected"}


def route_after_approve(state: MarketingState):
    return "publish" if (state.get("approved") or "").lower() == "yes" else "rejected"


graph = StateGraph(MarketingState)
graph.add_node("planner", planner_node)
graph.add_node("researcher", researcher_node)
graph.add_node("writer", writer_node)
graph.add_node("deck", deck_node)
graph.add_node("evals", evals_node)
graph.add_edge(START, "planner")
graph.add_edge("planner", "researcher")
graph.add_edge("researcher", "writer")
# Deck is built BEFORE evals (5 Nov 2026): the 9th check reads the deck, so
# evals must run after it. Retry loop is writer -> deck -> evals.
graph.add_edge("writer", "deck")
graph.add_edge("deck", "evals")
graph.add_conditional_edges("evals", route_after_evals, {"writer": "writer", "approve": "approve", "end": END})
graph.add_node("approve", approve_node)
graph.add_node("publish", publish_node)
graph.add_node("rejected", rejected_node)
graph.add_conditional_edges("approve", route_after_approve, {"publish": "publish", "rejected": "rejected"})
graph.add_edge("publish", END)
graph.add_edge("rejected", END)
# Checkpointed app: SqliteSaver with a long-lived connection (Ex7 lesson:
# NOT from_conn_string for a server/CLI that resumes across processes).
_conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
app = graph.compile(checkpointer=SqliteSaver(_conn))


def safe_json(obj):
    # Result at an interrupt contains an Interrupt object, which json
    # cannot serialise. Print it as its string form instead of crashing
    # AFTER the graph has already paused correctly.
    def _fix(o):
        if isinstance(o, dict):
            return {k: _fix(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_fix(v) for v in o]
        if o.__class__.__name__ == "Interrupt":
            return str(o)
        try:
            json.dumps(o)
            return o
        except TypeError:
            return str(o)
    return json.dumps(_fix(obj), indent=2, ensure_ascii=False)
