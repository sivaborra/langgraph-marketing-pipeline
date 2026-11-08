"""Ex2: Conditional routing — deep_research vs quick_draft on input."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from exercises.common import ToyState, stub_research, save_json

def route(state):
    return "deep_research" if "deep dive" in state["topic"] else "quick_draft"

def deep(state):
    return {"research": "DEEP: " + stub_research(state["topic"]), "trace": ["deep_research"]}

def quick(state):
    return {"research": "QUICK: " + stub_research(state["topic"]), "trace": ["quick_draft"]}

def write_node(state):
    return {"draft": "Draft from " + state["research"][:80], "trace": state["trace"] + ["write"]}

graph = StateGraph(ToyState)
graph.add_node("deep_research", deep)
graph.add_node("quick_draft", quick)
graph.add_node("write", write_node)
graph.add_conditional_edges(START, route, {"deep_research": "deep_research", "quick_draft": "quick_draft"})
graph.add_edge("deep_research", "write")
graph.add_edge("quick_draft", "write")
graph.add_edge("write", END)
app = graph.compile()

if __name__ == "__main__":
    results = {}
    for label, topic in [("deep", "deep dive: LangGraph orchestration"), ("quick", "LangGraph orchestration")]:
        out = app.invoke({"topic": topic, "trace": []})
        results[label] = {"topic": topic, "trace": out["trace"], "research_prefix": out["research"][:6]}
        print(label, "->", out["trace"])
    save_json("ex2_conditional.json", results)
    assert results["deep"]["trace"][0] == "deep_research" and results["quick"]["trace"][0] == "quick_draft"
    print("artefact: runs/ex2_conditional.json — branches differ as expected")
