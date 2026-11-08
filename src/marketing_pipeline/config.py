"""Configuration for the marketing pipeline.

Everything environment-specific lives here and is overridable by
environment variables, so the same code runs on a laptop, in Docker,
or on another machine without editing source.

No secrets live here: the pipeline talks only to a local Ollama server
and writes only local files. There is no cloud model, no API key, and
no external publish step anywhere in the pipeline.
"""

import os

# --- Ollama (local models only) -------------------------------------------
# Default is Ollama on the same machine. If Ollama runs elsewhere
# (another host, a VM, a container host), set OLLAMA_BASE_URL.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PLANNER_MODEL = os.environ.get("OLLAMA_PLANNER_MODEL", "qwen3:14b")
SYNTH_MODEL = os.environ.get("OLLAMA_SYNTH_MODEL", "qwen3:8b")
WRITER_MODEL = os.environ.get("OLLAMA_WRITER_MODEL", "qwen3:14b")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
# Context window for generation calls. 2048 is enough for the small prompts
# used here and keeps a 14b model inside a 12 GB GPU; raise it only if you
# have the VRAM for it.
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "2048"))

# --- Brand (the sample brand; make it yours) -------------------------------
# The pipeline retrieves over the markdown docs in KNOWLEDGE_BASE_DIR and
# only ever claims what those docs say. Ship it with the samples, or drop
# in your own brand docs and set BRAND_NAME / BRAND_SERVICES to match.
BRAND_NAME = os.environ.get("BRAND_NAME", "Example Consulting")

_DEFAULT_SERVICES = [
    "RAG / local inference (Ollama / vLLM)",
    "LangGraph orchestration",
    "Containers & Kubernetes / Docker",
    "Data platforms & reporting",
]
_services_env = os.environ.get("BRAND_SERVICES", "")
SERVICES = (
    [s.strip() for s in _services_env.split(",") if s.strip()]
    if _services_env
    else list(_DEFAULT_SERVICES)
)

KNOWLEDGE_BASE_DIR = os.environ.get("KNOWLEDGE_BASE_DIR", "knowledge_base")
CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB", "step7.db")

DEFAULT_GOAL = os.environ.get(
    "DEFAULT_GOAL",
    "Explain, safely and honestly, how Example Consulting guides "
    "organisations through their AI journey",
)
DEFAULT_AUDIENCE = os.environ.get(
    "DEFAULT_AUDIENCE", "organisations starting their AI journey"
)

# --- Bundled sample knowledge base ----------------------------------------
# Written into KNOWLEDGE_BASE_DIR on first run, only when that directory
# has no .md files yet. These are generic sample docs: no real clients,
# no numbers, no proprietary material. Replace them with your own.
SAMPLE_DOCS = {
    "positioning.md": (
        "Example Consulting guides organisations through their AI journey, "
        "deploying AI agents safely. Example Consulting is not a freelancer. "
        "Its work is domain-agnostic, with safety, human approval and "
        "measured evidence before anything is deployed or published."
    ),
    "services-ai.md": (
        "Example Consulting services in AI: RAG and local inference with "
        "Ollama and vLLM, LangGraph orchestration for agent workflows, "
        "and keeping models local where possible, with larger models only "
        "where the job is hard enough to need them."
    ),
    "services-platform.md": (
        "Example Consulting services in platforms: Containers and "
        "Kubernetes and Docker for deployment, and data platforms and "
        "reporting for business applications. Deployment includes "
        "checkpoints, human approval before publish, and logs and cost "
        "metrics for every run."
    ),
}
