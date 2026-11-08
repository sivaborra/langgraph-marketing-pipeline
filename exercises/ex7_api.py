"""Ex7: Deployment surface — minimal FastAPI wrapping the Ex1 toy graph."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI
from langgraph.graph import StateGraph, START, END
from exercises.common import ToyState, stub_plan, stub_research, stub_write, save_json

def plan_node(state):
    return {"plan": stub_plan(state["topic"]), "trace": ["plan"]}

def research_node(state):
    return {"research": stub_research(state["topic"]), "trace": state["trace"] + ["research"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], state["research"]), "trace": state["trace"] + ["write"]}

g = StateGraph(ToyState)
g.add_node("plan", plan_node); g.add_node("research", research_node); g.add_node("write", write_node)
g.add_edge(START, "plan"); g.add_edge("plan", "research"); g.add_edge("research", "write"); g.add_edge("write", END)
app_graph = g.compile()

app = FastAPI()
RUNS_STORE = []

@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": "0.1.0", "service": "langgraph-lab-ex7"}

@app.post("/run")
def run(body: dict):
    topic = body.get("topic", "LangGraph orchestration for Example Consulting")
    out = app_graph.invoke({"topic": topic, "trace": []})
    rec = {"run_id": f"run-{len(RUNS_STORE)+1}", "topic": topic, "trace": out["trace"], "draft_present": bool(out.get("draft"))}
    RUNS_STORE.append(rec)
    save_json("ex7_runs.json", RUNS_STORE)
    return rec

@app.get("/runs")
def runs():
    return {"runs": RUNS_STORE}
