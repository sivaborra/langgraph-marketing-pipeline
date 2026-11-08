"""Ex3 (crash half): graph that writes a marker after plan, then sleeps in research.

Run in background by run_all.sh, which kills it with SIGKILL after the
plan marker appears, then ex3_resume.py resumes the same thread_id.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from exercises.common import ToyState, stub_plan, stub_research, stub_write, CKPT, RUNS

MARKER = os.path.join(RUNS, "ex3_plan_done.txt")

def plan_node(state):
    with open(MARKER, "w") as f:
        f.write("plan done, pid=%d\n" % os.getpid())
    return {"plan": stub_plan(state["topic"]), "trace": ["plan"]}

def research_node(state):
    time.sleep(60)  # killed during this sleep in the crash demo
    return {"research": stub_research(state["topic"]), "trace": state["trace"] + ["research"]}

def write_node(state):
    return {"draft": stub_write(state["topic"], state["research"]), "trace": state["trace"] + ["write"]}

def build(checkpointer):
    g = StateGraph(ToyState)
    g.add_node("plan", plan_node); g.add_node("research", research_node); g.add_node("write", write_node)
    g.add_edge(START, "plan"); g.add_edge("plan", "research"); g.add_edge("research", "write"); g.add_edge("write", END)
    return g.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    db = os.path.join(CKPT, "ex3.db")
    with SqliteSaver.from_conn_string(db) as cp:
        app = build(cp)
        out = app.invoke({"topic": "LangGraph orchestration for Example Consulting", "trace": []},
                         config={"configurable": {"thread_id": "ex3-thread"}})
        print("completed (not crashed):", out["trace"])
