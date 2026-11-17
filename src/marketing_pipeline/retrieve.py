"""Shared retrieval: local embeddings + cosine top-3 over the knowledge base.

Used by the LangGraph researcher node and the ADK researcher tool alike.
Embeddings are always local bge-m3 via Ollama - retrieval is shared, so
this module never touches the generation model.
"""

import math
import os

from .config import KNOWLEDGE_BASE_DIR, SAMPLE_DOCS
from .llm import _embed

DOCS_DIR = KNOWLEDGE_BASE_DIR
DOCS_PREFIX = KNOWLEDGE_BASE_DIR.rstrip("/") + "/"


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


def retrieve(query, top_k=3):
    """Top-k knowledge-base docs for a query, by bge-m3 cosine similarity.

    Returns a list of {"source", "snippet", "score"} dicts, best first.
    One chunk per file: the docs are short on purpose.
    """
    _ensure_knowledge_base()
    q_emb = _embed(query)
    scored = []
    for name in sorted(os.listdir(DOCS_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(DOCS_DIR, name), encoding="utf-8") as f:
            text = f.read().strip()
        score = _cosine(q_emb, _embed(text))
        scored.append({"source": f"{DOCS_DIR}/{name}",
                       "snippet": text, "score": round(score, 4)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]

