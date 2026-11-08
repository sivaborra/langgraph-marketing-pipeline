"""Shared deterministic stubs for Phase 1 familiarisation.

No API keys, no network, no real LLMs. All "model" output is canned text
about Example Consulting's own services (allowed by the plan) so the graph
mechanics — state, edges, checkpoints, interrupts — are what is exercised.
"""
import json
import os
from typing import TypedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(BASE, "runs")
CKPT = os.path.join(BASE, "checkpoints")
os.makedirs(RUNS, exist_ok=True)
os.makedirs(CKPT, exist_ok=True)

# Sample services for the fictional Example Consulting — the same generic
# list as src/marketing_pipeline/config.py. (The lab originals named the
# author's real consultancy services; the public package uses generic ones.)
SAMPLE_SERVICES = (
    "RAG / local inference (Ollama / vLLM); LangGraph orchestration; "
    "Containers & Kubernetes / Docker; Data platforms & reporting"
)

def stub_plan(topic: str) -> str:
    return f"Plan for '{topic}': audience=engineering leaders; channels=blog+LinkedIn; services={SAMPLE_SERVICES}"

def stub_research(topic: str) -> str:
    return f"Research notes for '{topic}': Example Consulting guides organisations through their AI journey, deploying AI agents SAFELY, domain-agnostic. Sources: Example services list (sample material)."

def stub_write(topic: str, research: str) -> str:
    return (
        f"Draft blog for '{topic}': Example Consulting helps organisations deploy AI agents safely. "
        f"Based on: {research[:120]}"
    )

def save_json(name: str, data) -> str:
    path = os.path.join(RUNS, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path

def save_text(name: str, text: str) -> str:
    path = os.path.join(RUNS, name)
    with open(path, "w") as f:
        f.write(text)
    return path

class ToyState(TypedDict, total=False):
    topic: str
    plan: str
    research: str
    draft: str
    trace: list
    status: str
