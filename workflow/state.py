from typing import TypedDict, List, Dict, Annotated, Sequence, Optional
import operator

class GraphState(TypedDict):
    """
    Represents the state of our cycling route evolution graph.
    """
    user_intent: str
    user_profile: Dict
    plan: List[str]
    route_data: Dict  # coordinates, total_distance, total_elevation
    weather_info: Dict
    poi_info: List[Dict]
    safety_warnings: List[str]
    final_plan_markdown: str
    route_research_context: str
    intent_type: str        # "TYPE_A" (explicit A->B) | "TYPE_B" (loop/abstract)
    lifestyle_context: Dict # sunset timing, bike lane preference, etc.
    parsed_constraints: Dict
    analysis_summary: Dict
    # Message history
    messages: Annotated[Sequence[Dict], operator.add]
