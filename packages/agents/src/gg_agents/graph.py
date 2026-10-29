"""Graph assembly.

route ─┬─ retrieve → grade ─┬─ generate → verify ─┬─ END
       │        ▲           ├─ rewrite ───┘(≤2)   └─ generate (one retry)
       │        └───────────┘
       ├─ external → retrieve  (external evidence joins internal at generate)
       ├─ warehouse ──┬─ generate (tool result as synthetic parent)
       ├─ compare ────┤         └─ END on tool failure / unsupportable rate
       ├─ graph_walk ─┘
       └─ out_of_scope → END                      no_evidence → END

The compare node runs the warehouse count and the external lookup together for
rate-comparison questions ("our complaint rate vs MAUDE"); with no shared
denominator it ends at insufficient_evidence, surfacing both counts separately.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gg_agents.nodes import AgentDeps, AgentNodes
from gg_agents.state import MAX_REWRITES, AgentState


def _after_route(state: AgentState) -> str:
    if state["pattern"] == "aggregate":
        return "warehouse"
    if state["pattern"] == "trace":
        return "graph_walk"
    if state["pattern"] == "compare":
        return "compare"
    if state["pattern"] == "external":
        return "external"
    if state["pattern"] == "out_of_scope":
        return "out_of_scope"
    return "retrieve"


def _after_grade(state: AgentState) -> str:
    if state["grade_sufficient"]:
        return "generate"
    if state["rewrites"] < MAX_REWRITES:
        return "rewrite"
    if state["parents"] or state.get("external_parents"):
        # Rewrites exhausted but something was retrieved (or an external
        # lookup succeeded): generate anyway and let the verifier decide
        # whether it is answerable.
        return "generate"
    return "no_evidence"


def _after_tool(state: AgentState) -> str:
    # A tool failure sets the verdict and an honest answer; success leaves
    # the verdict empty and hands the result to generation.
    return END if state["verdict"] else "generate"


def _after_verify(state: AgentState) -> str:
    return END if state["verdict"] else "generate"


def build_agent_graph(
    deps: AgentDeps, *, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    nodes = AgentNodes(deps)
    graph = StateGraph(AgentState)
    graph.add_node("route", nodes.route)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("grade", nodes.grade)
    graph.add_node("rewrite", nodes.rewrite)
    graph.add_node("generate", nodes.generate)
    graph.add_node("verify", nodes.verify)
    graph.add_node("no_evidence", nodes.no_evidence)
    graph.add_node("external", nodes.external)
    graph.add_node("warehouse", nodes.warehouse)
    graph.add_node("compare", nodes.compare)
    graph.add_node("graph_walk", nodes.graph_walk)
    graph.add_node("out_of_scope", nodes.out_of_scope)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        _after_route,
        {
            "retrieve": "retrieve",
            "external": "external",
            "warehouse": "warehouse",
            "compare": "compare",
            "graph_walk": "graph_walk",
            "out_of_scope": "out_of_scope",
        },
    )
    graph.add_edge("external", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        _after_grade,
        {"generate": "generate", "rewrite": "rewrite", "no_evidence": "no_evidence"},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges("warehouse", _after_tool, {END: END, "generate": "generate"})
    graph.add_conditional_edges("compare", _after_tool, {END: END, "generate": "generate"})
    graph.add_conditional_edges("graph_walk", _after_tool, {END: END, "generate": "generate"})
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", _after_verify, {END: END, "generate": "generate"})
    graph.add_edge("no_evidence", END)
    graph.add_edge("out_of_scope", END)
    return graph.compile(checkpointer=checkpointer)
