"""Ex3 (resume half): resume thread ex3-thread after the SIGKILL.

Invoking with None input on the same thread_id continues from the last
checkpoint (after plan), re-running research and write — it must NOT
re-run plan, and the final trace must be plan/research/write.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from exercises.common import ToyState, stub_research, stub_write, CKPT, save_json

def research_node(state):
    return {"research": stub_research(state["topic"]), "trace": state["trace"] + ["research"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], state["research"]), "trace": state["trace"] + ["write"]}

# plan node is intentionally NOT re-executed on resume: it is only present
# in the graph definition; LangGraph restarts from the checkpoint after it.
def plan_node(state):
    return {"plan": "SHOULD-NOT-RERUN", "trace": ["plan-RERUN"]}

if __name__ == "__main__":
    db = os.path.join(CKPT, "ex3.db")
    assert os.path.exists(db), "checkpoint DB missing — crash half did not run"
    with SqliteSaver.from_conn_string(db) as cp:
        g = StateGraph(ToyState)
        g.add_node("plan", plan_node); g.add_node("research", research_node); g.add_node("write", write_node)
        g.add_edge(START, "plan"); g.add_edge("plan", "research"); g.add_edge("research", "write"); g.add_edge("write", END)
        app = g.compile(checkpointer=cp)
        before = app.get_state(config={"configurable": {"thread_id": "ex3-thread"}})
        print("checkpoint before resume — values keys:", sorted(before.values.keys()), "| next:", before.next)
        out = app.invoke(None, config={"configurable": {"thread_id": "ex3-thread"}})
        print("resumed final trace:", out["trace"])
        assert out["trace"] == ["plan", "research", "write"], out["trace"]
        assert "SHOULD-NOT-RERUN" not in out.get("plan", "")
        save_json("ex3_resume.json", {"before_next": list(before.next), "final_trace": out["trace"],
                                      "draft_present": bool(out.get("draft")), "db": db})
        print("artefacts: runs/ex3_resume.json, checkpoints/ex3.db — RESUME PROVED, plan not re-run")
