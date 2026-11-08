from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

class State(TypedDict):
    topic: str
    plan: str
    research: str
    draft: str

def plan_node(state: State):
    print("  [plan] running")
    return {"plan": "Outline v1"}

def research_node(state: State):
    print("  [research] running, plan =", state["plan"])
    return {"research": "Research based on " + state["plan"]}

def write_node(state: State):
    print("  [write] running, research =", state["research"])
    return {"draft": "Draft from " + state["research"]}

graph = StateGraph(State)
graph.add_node("plan", plan_node)
graph.add_node("research", research_node)
graph.add_node("write", write_node)
graph.add_edge(START, "plan")
graph.add_edge("plan", "research")
graph.add_edge("research", "write")
graph.add_edge("write", END)

config = {"configurable": {"thread_id": "tt-1"}}

with SqliteSaver.from_conn_string("checkpoints8.db") as checkpointer:
    app = graph.compile(checkpointer=checkpointer)

    # 1. Full run (imagine the draft then fails eval)
    print("=== RUN 1 (bad plan, bad draft) ===")
    print(app.invoke({"topic": "Example marketing"}, config))

    # 2. List the checkpoints - one per node boundary, newest first
    print("\n=== HISTORY ===")
    history = list(app.get_state_history(config))
    for snap in history:
        print("  next:", snap.next, "values:", snap.values)

    # 3. Rewind to the checkpoint AFTER plan (next = research)
    target = [s for s in history if s.next == ("research",)][0]
    print("\n=== REWINDING to after-plan checkpoint ===")
    print("  values there:", target.values)

    # 4. Fix the plan AT that checkpoint - this forks a new branch
    #    (the old branch stays in history, it is not overwritten)
    new_config = app.update_state(target.config, {"plan": "Outline v2 FIXED"})

    # 5. Resume from the fork - plan must NOT re-run
    print("\n=== RERUN from fork ===")
    print(app.invoke(None, new_config))
