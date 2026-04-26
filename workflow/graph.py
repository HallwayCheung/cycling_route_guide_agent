from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import GraphState
from .nodes import (
    demand_parser_node, intent_research_node, geospatial_analysis_node, coordinate_control_node, planner_node, executor_node,
    route_policy_node, lifestyle_enrichment_node, physical_simulation_node,
    explainability_node, rag_node, safety_and_supply_node, finalizer_node
)

def create_graph():
    """
    Cycling route agent graph with lifestyle enrichment.
    Flow: intent_research → geospatial_analysis → planner → executor → route_policy → lifestyle_enrichment → physics → explainability → [HITL] → rag → safety_supply → finalizer
    """
    workflow = StateGraph(GraphState)

    # Add Nodes
    workflow.add_node("demand_parser",       demand_parser_node)
    workflow.add_node("intent_research",     intent_research_node)
    workflow.add_node("geospatial_analysis", geospatial_analysis_node)
    workflow.add_node("coordinate_control",  coordinate_control_node)
    workflow.add_node("planner",             planner_node)
    workflow.add_node("executor",            executor_node)
    workflow.add_node("route_policy",        route_policy_node)
    workflow.add_node("lifestyle",           lifestyle_enrichment_node)
    workflow.add_node("physics",             physical_simulation_node)
    workflow.add_node("explainability",      explainability_node)
    workflow.add_node("rag",                 rag_node)
    workflow.add_node("safety_supply",       safety_and_supply_node)
    workflow.add_node("finalizer",           finalizer_node)

    # Graph flow
    workflow.set_entry_point("demand_parser")
    workflow.add_edge("demand_parser", "intent_research")
    workflow.add_edge("intent_research", "geospatial_analysis")
    workflow.add_edge("geospatial_analysis", "coordinate_control")
    workflow.add_edge("coordinate_control", "planner")
    workflow.add_edge("planner",         "executor")
    workflow.add_edge("executor",        "route_policy")
    workflow.add_edge("route_policy",    "lifestyle")
    workflow.add_edge("lifestyle",       "physics")

    # HITL pause before rag (user selects route)
    workflow.add_edge("physics",         "explainability")
    workflow.add_edge("explainability",  "rag")
    workflow.add_edge("rag",             "safety_supply")
    workflow.add_edge("safety_supply",   "finalizer")
    workflow.add_edge("finalizer",       END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory, interrupt_before=["rag"])
