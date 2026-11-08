"""Ex6: Subgraphs — retrieve -> synthesise subgraph inside a parent graph."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from exercises.common import ToyState, stub_write, save_json

class SubState(ToyState, total=False):
    retrieved: str
    synthesis: str

def retrieve(state):
    return {"retrieved": "Example services (sample material): LangGraph orchestration; RAG / local inference; containers & Kubernetes."}

def synthesise(state):
    return {"synthesis": "Synthesis: " + state["retrieved"]}

sub = StateGraph(SubState)
sub.add_node("retrieve", retrieve); sub.add_node("synthesise", synthesise)
sub.add_edge(START, "retrieve"); sub.add_edge("retrieve", "synthesise"); sub.add_edge("synthesise", END)
research_subgraph = sub.compile()

def plan_node(state):
    return {"plan": "Plan: blog about Example LangGraph orchestration", "trace": ["plan"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], state.get("synthesis", "")), "trace": state["trace"] + ["write"]}

parent = StateGraph(ToyState)
parent.add_node("plan", plan_node)
parent.add_node("research", research_subgraph)
parent.add_node("write", write_node)
parent.add_edge(START, "plan"); parent.add_edge("plan", "research"); parent.add_edge("research", "write"); parent.add_edge("write", END)
app = parent.compile()

if __name__ == "__main__":
    out = app.invoke({"topic": "LangGraph orchestration for Example", "trace": []})
    print("trace:", out["trace"])
    print("synthesis present:", bool(out.get("synthesis")), "| draft present:", bool(out.get("draft")))
    save_json("ex6_subgraph.json", {"trace": out["trace"], "synthesis": out.get("synthesis"), "draft_present": bool(out.get("draft"))})
    assert out["trace"] == ["plan", "write"] or "write" in out["trace"]
    print("artefact: runs/ex6_subgraph.json")
