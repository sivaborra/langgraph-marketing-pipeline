"""Ex5: Streaming — node start/end/interrupt events."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from exercises.common import ToyState, stub_plan, stub_write, CKPT, save_text

def plan_node(state):
    return {"plan": stub_plan(state["topic"]), "trace": ["plan"]}

def approve_node(state):
    interrupt("approve?")
    return {"status": "approved", "trace": state["trace"] + ["approved"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], "x"), "trace": state["trace"] + ["write"]}

if __name__ == "__main__":
    events = []
    db = os.path.join(CKPT, "ex5.db")
    with SqliteSaver.from_conn_string(db) as cp:
        g = StateGraph(ToyState)
        g.add_node("plan", plan_node); g.add_node("approve", approve_node); g.add_node("write", write_node)
        g.add_edge(START, "plan"); g.add_edge("plan", "approve"); g.add_edge("approve", "write"); g.add_edge("write", END)
        app = g.compile(checkpointer=cp)
        for event in app.stream({"topic": "LangGraph orchestration", "trace": []},
                                config={"configurable": {"thread_id": "ex5"}},
                                stream_mode="events"):
            kind = event.get("event", "")
            name = event.get("name", "")
            events.append(f"{kind} :: {name}")
    lines = sorted(set(events))
    save_text("ex5_stream_events.txt", "\n".join(lines) + "\n")
    print("\n".join(lines))
    assert any("plan" in e for e in lines), "no plan event streamed"
    print("artefact: runs/ex5_stream_events.txt")
