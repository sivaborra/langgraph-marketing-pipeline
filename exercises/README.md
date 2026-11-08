# Phase 1 exercises — learn LangGraph by building the pieces

The small toy graphs the full pipeline was built from, in order. Each one
is runnable on its own from the repo root (venv active, no Ollama needed —
they use stub data, not real models):

| File | What it teaches |
|---|---|
| `ex1_state_nodes_edges.py` | State, nodes, edges — a 3-node toy graph: plan → research → write |
| `ex2_conditional.py` | Conditional edges (branching on state) |
| `ex3_crash.py` / `ex3_resume.py` | Checkpoints: kill the process mid-run, resume from the same state |
| `ex4_interrupt.py` | Human-in-the-loop: `interrupt()` pauses the graph for approval |
| `ex5_streaming.py` | Streaming updates as the graph runs |
| `ex6_subgraph.py` | Subgraphs: retrieve → synthesise inside a parent graph |
| `ex7_api.py` | FastAPI around a toy graph (the shape Phase 3 follows) |
| `ex8.py` | Checkpointed graph with SQLite persistence |

Run them all in order:

```bash
./scripts/run_all.sh
```

`common.py` holds the shared toy state and stub functions (fake planner /
researcher / writer — no LLM calls). The real pipeline that combines these
pieces is in `src/marketing_pipeline/graph.py`.
