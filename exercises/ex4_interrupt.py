"""Ex4: Interrupts — approval step after plan; awaiting_human, then yes / no."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command
from exercises.common import ToyState, stub_plan, stub_write, CKPT, save_text

def plan_node(state):
    return {"plan": stub_plan(state["topic"]), "trace": ["plan"]}

def approve_node(state):
    answer = interrupt("approve plan? (yes/no)")
    if answer == "yes":
        return {"status": "approved", "trace": state["trace"] + ["approved"]}
    return {"status": "rejected", "trace": state["trace"] + ["rejected"]}

def write_node(state):
    if state.get("status") != "approved":
        return {"draft": "", "trace": state["trace"]}
    return {"draft": stub_write(state["topic"], "approved plan"), "trace": state["trace"] + ["write"]}

def build(cp):
    g = StateGraph(ToyState)
    g.add_node("plan", plan_node); g.add_node("approve", approve_node); g.add_node("write", write_node)
    g.add_edge(START, "plan"); g.add_edge("plan", "approve"); g.add_edge("approve", "write"); g.add_edge("write", END)
    return g.compile(checkpointer=cp)

if __name__ == "__main__":
    log = []
    db = os.path.join(CKPT, "ex4.db")
    with SqliteSaver.from_conn_string(db) as cp:
        app = build(cp)
        for label, answer, tid in [("yes", "yes", "ex4-yes"), ("no", "no", "ex4-no")]:
            first = app.invoke({"topic": "LangGraph orchestration", "trace": []}, config={"configurable": {"thread_id": tid}})
            log.append(f"{label}: first invoke returned keys={sorted(first.keys())}")
            log.append(f"{label}: interrupt present={'__interrupt__' in first} -> {first.get('__interrupt__')}")
            assert "__interrupt__" in first, "expected awaiting_human interrupt"
            log.append(f"{label}: status=awaiting_human (interrupt raised, graph paused)")
            final = app.invoke(Command(resume=answer), config={"configurable": {"thread_id": tid}})
            log.append(f"{label}: after resume={answer}: status={final.get('status')} trace={final['trace']} draft_present={bool(final.get('draft'))}")
            if answer == "yes":
                assert final["status"] == "approved" and final["draft"]
            else:
                assert final["status"] == "rejected" and not final["draft"]
    save_text("ex4_interrupt.txt", "\n".join(log) + "\n")
    print("\n".join(log))
    print("artefact: runs/ex4_interrupt.txt")
