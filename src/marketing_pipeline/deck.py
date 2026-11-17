"""Shared deck building: PPTX from the plan outline, no new facts.

Used by the LangGraph deck node and the ADK deck tool alike.
"""

import os
import re

from .config import BRAND_NAME
from .retrieve import DOCS_PREFIX

from .config import BRAND_NAME
from .retrieve import DOCS_PREFIX


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
    ## sections, each section goes to the outline item its heading matches
    best. Paragraphs before the first heading (the intro) and drafts
    without ## sections fall back to per-paragraph keyword matching.
    Returns {outline item: [paragraphs]}. No paragraph is dropped."""
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
    Returns [] when the deck cannot be read - the eval check then fails
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


def _short(text, limit=200):
    """Shorten to a whole word, never mid-word. Adds ... when cut."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ..."


def build_deck(plan, research, draft, run_id, out_dir="outputs"):
    """Build the deck for a plan.

    Returns (deck_path, deck_slides, fallback_slides). Each slide carries
    its own draft paragraphs; a slide with no matching paragraph falls
    back to the doc snippets, so a run never ends with an empty slide.
    """
    try:
        from pptx import Presentation
        from pptx.util import Pt
    except ImportError as e:
        raise RuntimeError("python-pptx is not installed in this venv. Run: pip install python-pptx, then re-run.") from e
    docs = [r for r in research if r["source"].startswith(DOCS_PREFIX)]
    assigned = _assign_paragraphs(draft or "", plan["outline"])
    os.makedirs(out_dir, exist_ok=True)
    deck_path = os.path.join(out_dir, f"deck-{run_id}.pptx")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = BRAND_NAME
    slide.placeholders[1].text = f"{plan['objective']}\n\nDRAFT - for human review only. NOT published."
    fallback_slides = []
    for item in plan["outline"]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = _short(item, 60)
        title_tf = slide.shapes.title.text_frame
        title_tf.word_wrap = True
        title_tf.paragraphs[0].runs[0].font.size = Pt(28)
        body = slide.placeholders[1].text_frame
        body.word_wrap = True
        if assigned[item]:
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
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Next step: human review"
    slide.placeholders[1].text = ("This deck is a draft from an evaluated draft. "
                                  "Nothing in it is published until a human approves it.\n"
                                  f"Services: {', '.join(plan['services'])}")
    prs.save(deck_path)
    return deck_path, 2 + len(plan["outline"]), fallback_slides

