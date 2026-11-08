# LangGraph marketing pipeline

A multi-agent marketing content pipeline built with LangGraph: give it a
goal and an audience, and it plans, researches a local knowledge base,
drafts with strict numeric citations, builds a slide deck, and scores the
result against a 9-check eval gate. **Nothing publishes without a human
saying yes** — the graph literally stops at an approval interrupt and waits.
Publishing is local only: a markdown draft and a `.pptx` in `published/`.

It runs entirely on local Ollama models. No cloud LLM, no external
publishing, no tracking.

## What it is not

- **Not a webpage generator.** It writes marketing drafts and slide decks,
  not websites.
- **No AWS Bedrock, no MCP, no Langfuse/LangSmith.** The only LLM calls go
  to a local Ollama server. There is no observability integration and no
  tool-calling protocol in the loop.
- **Not a commercial product.** This is a guided learning exercise that
  became a working deployment pipeline. It is published so others can learn
  from the pattern — eval gate, approval interrupt, checkpoint resume — not
  as a supported marketing tool.

## How it works

```
goal + audience
  → planner (qwen3:14b)          outline: topic, audience, angle, services
  → researcher subgraph           retrieve from the knowledge base (bge-m3
      retrieve → synthesise         embeddings, cosine similarity) and
      (qwen3:8b)                  summarise with qwen3:8b
  → writer (qwen3:14b)            draft with a numeric citation on every
                                  factual sentence; banned phrases rejected
  → deck (python-pptx)           one slide per draft section
  → evals (9 checks)              pass → approval interrupt
                                  fail → back to the writer with feedback,
                                         max 2 attempts, then unpublished
  → approve (human)               yes → local publish (published/<run_id>/)
                                  no  → rejected, nothing published
```

The 9 eval checks: `citations_present`, `citations_valid`,
`all_docs_cited`, `sources_section`, `banned_claims_zero` (the phrases
"guaranteed roi", "no risk", "best-in-class", "unlimited" must not appear),
`pii_zero`, `draft_length_ok` (≥ 200 characters), `citation_coverage_ge_0_5`
(at least half of the long sentences carry a citation), and
`deck_slides_distinct` (no two slides with identical body text).

State is checkpointed to SQLite (`step7.db`, keyed by run id) after every
step, so a killed process or container resumes the same run instead of
restarting it — including a run paused at approval.

## Quickstart

Prerequisites: Python 3.12 and [Ollama](https://ollama.com) running
locally with the models below pulled (`ollama pull qwen3:14b qwen3:8b bge-m3`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# CLI: run a draft, then approve it (two separate commands, same run id)
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli run demo
PYTHONPATH=src .venv/bin/python -m marketing_pipeline.cli approve demo yes

# API: same pipeline behind FastAPI
PYTHONPATH=src .venv/bin/uvicorn marketing_pipeline.api:app --port 8000
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/api/v1/marketing/run \
  -H 'Content-Type: application/json' \
  -d '{"goal": "A short blog post", "audience": "engineering managers"}'
```

Docker (the container talks to Ollama on the host):

```bash
docker build -t marketing-pipeline .
docker run -d --name marketing-pipeline --restart unless-stopped \
  -p 8000:8000 marketing-pipeline
```

API endpoints: `GET /healthz`, `POST /api/v1/marketing/run`,
`POST /api/v1/runs/{run_id}/approve` (`{"decision": "yes"|"no"}`),
`GET /api/v1/runs/{run_id}`, `GET /metrics`.

## Configuration

Everything is an environment variable; defaults live in
`src/marketing_pipeline/config.py` (copy `.env.example` to `.env` to
override):

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_PLANNER_MODEL` | `qwen3:14b` | Planner model |
| `OLLAMA_WRITER_MODEL` | `qwen3:14b` | Writer model |
| `OLLAMA_SYNTH_MODEL` | `qwen3:8b` | Research synthesis model |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Retrieval embeddings |
| `OLLAMA_NUM_CTX` | `2048` | Context window for generation calls |
| `BRAND_NAME` | `Example Consulting` | Brand name used in drafts |
| `KNOWLEDGE_BASE_DIR` | `knowledge_base` | Folder of `.md` source docs |
| `CHECKPOINT_DB` | `step7.db` | SQLite checkpoint path |

The knowledge base ships with three short sample documents for a fictional
"Example Consulting". Replace them with your own `.md` files — the
researcher retrieves only from that folder, so the pipeline can only cite
what you put there. That is deliberate: the eval gate catches citation and
format problems, not wrong facts. Your documents never leave the machine.

The writer runs with `temperature 0` and `num_ctx 2048` (the 14b model at
Ollama's default 40k context overflows a 12 GB GPU — the context cap is a
hard-won lesson, not a tuning choice).

## Layout

```
src/marketing_pipeline/   the pipeline: graph.py, cli.py, api.py, config.py
knowledge_base/           sample docs (swap in your own)
exercises/                Phase 1 toy graphs — state, edges, checkpoints,
                          interrupts, streaming, subgraphs, a FastAPI toy
docs/                     mock Q&A, eval validation, architecture diagrams
scripts/                  run_all.sh (all Phase 1 exercises), smoke_ex7.sh
Dockerfile                python:3.12-slim, uvicorn on :8000
requirements.txt          pinned to the versions this was verified against
```

## Provenance

Built by Siva Borra, October–November 2026, as a guided learning exercise
(Phases 1–4: LangGraph fundamentals → the full graph → FastAPI + Docker →
interview-ready). In his lab it built 12 decks and published 8 locally,
at zero cost per run on a local RTX 3060. The sample knowledge base replaces
the original company's real marketing documents, which stay private; the
code itself contains no client material. The architecture diagrams
(`docs/architecture-diagrams.pdf`) and the mock Q&A (`docs/`) describe the
design decisions and the failure modes found along the way.

## License

Apache License 2.0 — see `LICENSE`. Copyright 2026 Siva Borra.
