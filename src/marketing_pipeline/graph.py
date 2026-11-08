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
import math
import os
import re
import time
import urllib.request
import shutil
import sqlite3
import urllib.error
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from .config import (
    BRAND_NAME,
    CHECKPOINT_DB,
    EMBED_MODEL,
    KNOWLEDGE_BASE_DIR,
    NUM_CTX,
    OLLAMA_BASE_URL,
    PLANNER_MODEL,
    SAMPLE_DOCS,
    SERVICES,
    SYNTH_MODEL,
    WRITER_MODEL,
)

PLANNER_MODEL = "qwen3:14b"
SYNTH_MODEL = "qwen3:8b"
WRITER_MODEL = "qwen3:14b"  # writer first: local 14b, per the model-per-node mapping
EMBED_MODEL = "bge-m3"
DOCS_DIR = KNOWLEDGE_BASE_DIR
DOCS_PREFIX = KNOWLEDGE_BASE_DIR.rstrip("/") + "/"

def _post(path, payload, timeout=600):
    req = urllib.request.Request(
        OLLAMA_BASE_URL + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama {path} HTTP {e.code}: {e.read().decode()[:500]}")


def _generate(model, prompt):
    data = _post("/api/generate", {
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX}, "think": False})
    return data


def _embed(text):
    data = _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text})
    return data["embedding"]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _ensure_knowledge_base():
    """Create the knowledge base from the bundled samples on first run.

    If the directory already holds .md files they are left untouched:
    drop your own brand docs in and the pipeline retrieves over them.
    """
    os.makedirs(DOCS_DIR, exist_ok=True)
    if any(n.endswith(".md") for n in os.listdir(DOCS_DIR)):
        return
    for name, text in SAMPLE_DOCS.items():
        with open(os.path.join(DOCS_DIR, name), "w", encoding="utf-8") as f:
            f.write(text + "\n")


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
    prompt = (
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
    _ensure_knowledge_base()
    query = state["query"]
    q_emb = _embed(query)
    scored = []
    for name in sorted(os.listdir(DOCS_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(DOCS_DIR, name), encoding="utf-8") as f:
            text = f.read().strip()
        # One chunk per file for this step: docs are short on purpose.
        score = _cosine(q_emb, _embed(text))
        scored.append({"source": f"{DOCS_DIR}/{name}",
                       "snippet": text, "score": round(score, 4)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return {"candidates": scored[:3]}


def synthesise_node(state: ResearchState):
    cands = state["candidates"]
    context = "\n\n".join(
        f"[{c['source']} | score {c['score']}] {c['snippet']}" for c in cands)
    prompt = (
        f"Summarise ONLY what the retrieved {BRAND_NAME} docs below say, "
        "for the marketing plan. Do not add facts, clients, numbers or "
        "claims that are not in the docs. If a doc does not cover a "
        "point, say so instead of inventing it.\n\n"
        f"Retrieved docs:\n{context}\n\n"
        "Return 3-5 short bullet lines, each starting with its source "
        "file name, e.g. '- services-ai.md: ...'"
    )
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
    plan = state["plan"]
    feedback = state.get("eval_feedback") or ""
    feedback_block = (f"\n\nPrevious draft FAILED eval for these reasons, fix all of them "
                      f"in this revision and do not repeat them:\n{feedback}\n"
                      if feedback else "")
    # Number the brand-doc research items only; synthesis is not a source.
    docs = [r for r in state["research"] if r["source"].startswith(DOCS_PREFIX)]
    numbered = "\n".join(
        f"[{i+1}] {r['source']}: {r['snippet']}" for i, r in enumerate(docs))
    prompt = (
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



def _draft_sections(draft):
    """Draft as a list of (heading, [paragraphs]) sections. The '# ' title,
    the Sources section and the review footer are dropped. Paragraphs before
    the first '## ' heading belong to heading None (the intro)."""
    sections, cur, paras = [], [], []
    heading, in_sources = None, False

    def flush_para():
        nonlocal cur, paras
        if cur:
            p = " ".join(cur)
            if len(p) > 20:
                paras.append(p)
            cur = []

    def flush_section():
        nonlocal paras, heading
        flush_para()
        sections.append((heading, paras))
        paras = []

    for line in (draft or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            continue
        if s.startswith("## "):
            if s.lower().startswith("## sources"):
                in_sources = True
            flush_section()
            heading = s[3:].strip() if not in_sources else None
            continue
        if in_sources or s.startswith("---"):
            continue
        if "NOT published" in s and "human review" in s:
            continue
        if not s:
            flush_para()
        else:
            cur.append(s)
    flush_section()
    return [(h, ps) for (h, ps) in sections if ps]


def _draft_body_paragraphs(draft):
    """Draft paragraphs minus the title, the Sources section and the review
    footer. Kept for compatibility; _assign_paragraphs now uses sections."""
    return [p for (_h, ps) in _draft_sections(draft) for p in ps]


_STOPWORDS = {"using", "with", "and", "for", "the", "into", "your", "our"}


def _keywords(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 3 and w not in _STOPWORDS}


def _best_match(text, outline):
    """Outline item sharing the most keywords with text; (item, score)."""
    tk = _keywords(text)
    best, best_score = outline[0], 0
    for item in outline:
        score = len(_keywords(item) & tk)
        if score > best_score:
            best, best_score = item, score
    return best, best_score


def _assign_paragraphs(draft, outline):
    """Give every draft paragraph to its slide. When the writer produced
    ## sections (the norm since headlines became short, 5 Nov 2026), each
    section goes to the outline item its heading matches best — overlap
    between two short topical strings is far more reliable than matching a
    long paragraph against a 3-keyword headline. The old paragraph-only
    matching misfiled paragraphs onto the first slide (run-9a8b0e77: the
    Power BI and Guided Implementation paragraphs both landed on slide 1,
    slides 3 and 4 fell back to identical doc snippets, and
    deck_slides_distinct failed twice). Paragraphs before the first heading
    (the intro) and drafts without ## sections fall back to per-paragraph
    keyword matching. Returns {outline item: [paragraphs]}.
    No paragraph is dropped."""
    assigned = {item: [] for item in outline}
    sections = _draft_sections(draft)
    has_headings = any(h for (h, _ps) in sections)
    for heading, paras in sections:
        if heading is None or not has_headings:
            for p in paras:
                best, _s = _best_match(p, outline)
                assigned[best].append(p)
        else:
            best, score = _best_match(heading, outline)
            if score == 0:
                for p in paras:
                    b2, _s2 = _best_match(p, outline)
                    assigned[b2].append(p)
            else:
                assigned[best].extend(paras)
    return assigned


def _deck_slide_bodies(deck_path):
    """Body text of each content slide (skips title + closing slides).
    Title text is EXCLUDED on purpose: titles always differ, so including
    them would let identical bodies pass. Only the body paragraphs count.
    Returns [] when the deck cannot be read — the eval check then fails
    instead of crashing the run."""
    try:
        from pptx import Presentation
        prs = Presentation(deck_path)
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


# ---- Deck node: PPTX from the plan outline, no new facts ----

def _short(text, limit=200):
    """Shorten to a whole word, never mid-word. Adds … when cut (5 Nov 2026:
    the old [:200] slice ended lines mid-word on every content slide)."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def deck_node(state: MarketingState):
    try:
        from pptx import Presentation
        from pptx.util import Pt
    except ImportError as e:
        raise RuntimeError("python-pptx is not installed in this venv. Run: pip install python-pptx, then re-run.") from e
    plan = state["plan"]
    docs = [r for r in state["research"] if r["source"].startswith(DOCS_PREFIX)]
    # Each slide carries its own draft paragraphs (5 Nov 2026 rework: the old
    # version repeated the same three doc snippets on every slide, so all
    # slides had identical content). A slide with no matching paragraph falls
    # back to the doc snippets, so a run never ends with an empty slide.
    assigned = _assign_paragraphs(state.get("draft") or "", plan["outline"])
    os.makedirs("outputs", exist_ok=True)
    deck_path = os.path.join("outputs", f"deck-{state.get('run_id', 'demo')}.pptx")
    prs = Presentation()
    # Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = BRAND_NAME
    slide.placeholders[1].text = f"{plan['objective']}\n\nDRAFT — for human review only. NOT published."
    # One slide per outline item, with its own draft paragraphs
    fallback_slides = []
    for item in plan["outline"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        # Titles: whole-word cut at 60 chars + 28pt. The default title font
        # is ~44pt: a 70-80 char title wrapped to 3-4 lines, overflowed the
        # title box and printed on top of the body (seen 5 Nov 2026).
        slide.shapes.title.text = _short(item, 60)
        title_tf = slide.shapes.title.text_frame
        title_tf.word_wrap = True
        title_tf.paragraphs[0].runs[0].font.size = Pt(28)
        body = slide.placeholders[1].text_frame
        body.word_wrap = True
        # No repeated "Audience:" line: it sat exactly where the overflowing
        # title landed, so the two printed on top of each other. The audience
        # is already in the title slide's objective.
        if assigned[item]:
            # Full paragraphs, not cut at 280 chars: draft paragraphs are
            # ~350 chars max and fit the body box at 14pt; cutting them left
            # every slide ending in a dangling "..." (seen 5 Nov 2026).
            # _short at 600 is a safety net only.
            lines = [_short(p, 600) for p in assigned[item]]
        else:
            fallback_slides.append(item)
            lines = [f"[{doc['source']}] {_short(doc['snippet'])}" for doc in docs]
        body.text = lines[0]
        body.paragraphs[0].font.size = Pt(14)
        for line in lines[1:]:
            para = body.add_paragraph()
            para.text = line
            para.font.size = Pt(14)
    # Closing slide
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Next step: human review"
    slide.placeholders[1].text = ("This deck is a draft from an evaluated draft. "
                                  "Nothing in it is published until a human approves it.\n"
                                  f"Services: {', '.join(plan['services'])}")
    prs.save(deck_path)
    return {"deck_path": deck_path,
            "deck_slides": 2 + len(plan["outline"]),  # title + one per outline item + closing
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
    # Local publish stub ONLY: copy draft + deck into published/<run_id>/.
    # No LinkedIn, no WordPress, no external call of any kind.
    out_dir = os.path.join("published", state.get("run_id", "demo"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "draft.md"), "w", encoding="utf-8") as f:
        f.write(state["draft"])
    deck_src = state.get("deck_path")
    if deck_src and os.path.exists(deck_src):
        shutil.copy(deck_src, os.path.join(out_dir, os.path.basename(deck_src)))
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
