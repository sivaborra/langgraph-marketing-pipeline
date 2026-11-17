"""Ollama transport: raw POST, text generation, embeddings.

Shared by the LangGraph path (generation + embeddings) and the ADK path
(embeddings for retrieval only - generation there goes through Gemini).
"""

import json
import urllib.request
import urllib.error

from .config import EMBED_MODEL, NUM_CTX, OLLAMA_BASE_URL


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

