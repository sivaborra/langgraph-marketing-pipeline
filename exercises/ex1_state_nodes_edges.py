"""Ex1: State / nodes / edges — 3-node toy graph plan -> research -> write."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from exercises.common import ToyState, stub_plan, stub_research, stub_write, save_json, save_text

def plan_node(state):
    before = dict(state)
    out = {"plan": stub_plan(state["topic"]), "trace": state.get("trace", []) + ["plan"]}
    return out

def research_node(state):
    return {"research": stub_research(state["topic"]), "trace": state.get("trace", []) + ["research"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], state["research"]), "trace": state.get("trace", []) + ["write"]}

graph = StateGraph(ToyState)
graph.add_node("plan", plan_node)
graph.add_node("research", research_node)
graph.add_node("write", write_node)
graph.add_edge(START, "plan")
graph.add_edge("plan", "research")
graph.add_edge("research", "write")
graph.add_edge("write", END)
app = graph.compile()

if __name__ == "__main__":
    # Stream so we capture state before/after each node.
    snapshots = []
    final = None
    for event in app.stream({"topic": "LangGraph orchestration for Example Consulting", "trace": []}, stream_mode="values"):
        snapshots.append(event)
        final = event
    save_json("ex1_state.json", {"snapshots": snapshots, "final": final})
    mermaid = app.get_graph().draw_mermaid()
    save_text("ex1_mermaid.md", "# Ex1 graph\n\n```mermaid\n" + mermaid + "\n```\n")
    print("nodes visited:", final["trace"])
    print("plan present:", bool(final.get("plan")), "| research present:", bool(final.get("research")), "| draft present:", bool(final.get("draft")))
    print("snapshots:", len(snapshots))
    print("artefacts: runs/ex1_state.json, runs/ex1_mermaid.md")
