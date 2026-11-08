"""FastAPI service over the marketing pipeline (Phase 3).

Endpoints:
    GET  /healthz                    service + Ollama model list
    POST /api/v1/marketing/run      start a run (pauses at approval)
    POST /api/v1/runs/{run_id}/approve   {"decision": "yes"|"no"}
    GET  /api/v1/runs/{run_id}      run state
    GET  /metrics                   decks built / runs published locally

Run from the repo root (venv active):
    uvicorn marketing_pipeline.api:app --port 8000
or in Docker (see Dockerfile). The checkpoint DB lives in the working
directory, so run from the repo root or set CHECKPOINT_DB.
"""

import glob
import json
import time
import urllib.request
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.types import Command

from . import config
from .graph import app as graph_app

START = time.time()
RUNS_STARTED_THIS_PROCESS = 0

app = FastAPI(title="Marketing pipeline API")


@app.get("/healthz")
def healthz():
    try:
        with urllib.request.urlopen(
                config.OLLAMA_BASE_URL + "/api/tags", timeout=5) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        models = []
    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - START, 1),
        "models": models,
    }


class RunRequest(BaseModel):
    goal: str = config.DEFAULT_GOAL
    audience: str = config.DEFAULT_AUDIENCE
    services: list[str] | None = None


@app.post("/api/v1/marketing/run")
def run_marketing(req: RunRequest):
    global RUNS_STARTED_THIS_PROCESS
    RUNS_STARTED_THIS_PROCESS += 1
    run_id = "run-" + uuid.uuid4().hex[:8]
    cfg = {"configurable": {"thread_id": run_id}}
    try:
        result = graph_app.invoke({
            "run_id": run_id,
            "brand": config.BRAND_NAME,
            "audience": req.audience,
            "goal": req.goal,
            "inputs": {"services": req.services or list(config.SERVICES)},
        }, cfg)
    except ValueError as e:
        # A planner/writer/eval failure used to surface as a bare
        # "Internal Server Error". Return the reason instead.
        raise HTTPException(status_code=422, detail=str(e))
    state = graph_app.get_state(cfg)
    return {
        "run_id": run_id,
        "status": result.get("status"),
        "approved": result.get("approved"),
        "published": result.get("published"),
        "deck_path": result.get("deck_path"),
        "next": list(state.next) if state.next else [],
        "draft_preview": (result.get("draft") or "")[:500],
    }


class ApproveRequest(BaseModel):
    decision: str


@app.post("/api/v1/runs/{run_id}/approve")
def approve_run(run_id: str, req: ApproveRequest):
    decision = req.decision.strip().lower()
    if decision not in ("yes", "no"):
        raise HTTPException(status_code=400, detail="decision must be 'yes' or 'no'")
    cfg = {"configurable": {"thread_id": run_id}}
    result = graph_app.invoke(Command(resume=decision), cfg)
    return {
        "run_id": run_id,
        "status": result.get("status"),
        "approved": result.get("approved"),
        "published": result.get("published"),
        "deck_path": result.get("deck_path"),
    }


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str):
    cfg = {"configurable": {"thread_id": run_id}}
    state = graph_app.get_state(cfg)
    values = state.values or {}
    return {
        "run_id": run_id,
        "status": values.get("status"),
        "approved": values.get("approved"),
        "published": values.get("published"),
        "deck_path": values.get("deck_path"),
        "next": list(state.next) if state.next else [],
    }


@app.get("/metrics")
def metrics():
    # Filesystem counts survive a container restart; the in-memory
    # counter does not, and is labelled as such on purpose.
    return {
        "service": "marketing-pipeline",
        "uptime_seconds": round(time.time() - START, 1),
        "decks_built": len(glob.glob("outputs/deck-*.pptx")),
        "runs_published_locally": len(glob.glob("published/*/draft.md")),
        "runs_started_this_process": RUNS_STARTED_THIS_PROCESS,
    }
