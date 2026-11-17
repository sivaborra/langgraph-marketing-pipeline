"""ADK model selection: Gemini first, local Ollama as fallback.

Backend by env ADK_MODEL_BACKEND ('gemini' default, 'ollama' to skip
Gemini entirely). The runner tries Gemini first and falls back to
Ollama automatically when Google is down - the fallback is the whole
point, so a failed Gemini call never kills a run.
"""

import os

from marketing_pipeline.config import GEMINI_MODEL, PLANNER_MODEL, SYNTH_MODEL, WRITER_MODEL

_MODELS = {"planner": PLANNER_MODEL, "writer": WRITER_MODEL, "synth": SYNTH_MODEL}


def adk_model(role="planner", backend=None, think=None):
    """Model for an ADK agent: a Gemini name, or a LiteLLM Ollama model.

    think: only for the Ollama path. think=False stops qwen3 thinking
    out loud in the agent loop (reasoning leaks into the reply and loops
    until Ollama aborts with the repeat limit). None leaves it alone.
    """
    backend = (backend or os.environ.get("ADK_MODEL_BACKEND", "gemini")).lower()
    if backend == "ollama":
        from google.adk.models.lite_llm import LiteLlm
        kwargs = {}
        if think is not None:
            kwargs["think"] = think
        return LiteLlm(model=f"ollama/{_MODELS[role]}", **kwargs)
    return GEMINI_MODEL

