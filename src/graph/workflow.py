"""
LangGraph workflow orchestration for AI Textbook Generator.
"""

from enum import Enum

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

from src.graph.state import AgentState
from src.log_config import setup_logger

from src.agents.ingester import perform_ingestion
from src.agents.planner import plan_curriculum
from src.agents.researcher import perform_research
from src.agents.writer import write_section
from src.agents.reviewer import review_section
from src.agents.illustrator import illustrate_section
from src.agents.publisher import publish_curriculum
from src.agents.validator import validate_topic_node

logger = setup_logger(name="WorkflowBuilder", logfile="logs/workflow.log")


class WorkflowDecision(str, Enum):
    CONTINUE_SUBSECTION = "continue_subsection"
    NEXT_CHAPTER        = "next_chapter"
    FINISHED            = "finished"
    REVISE              = "revise"
    APPROVE             = "approve"


def route_after_review(state: AgentState) -> str:
    feedback = state.get("review_feedback", "")
    if feedback:
        logger.info(f"Review decision: REVISE — feedback: {feedback[:80]}")
        return WorkflowDecision.REVISE
    logger.info("Review decision: APPROVE — proceeding to illustrator")
    return WorkflowDecision.APPROVE


def _accumulate_content(state: AgentState) -> dict:
    current = state.get("current_content", "")
    final   = state.get("final_content", "")
    if current:
        accumulated = final + "\n\n" + current if final else current
    else:
        accumulated = final
    return {"final_content": accumulated, "current_content": ""}


def append_and_update_subsection(state: AgentState) -> dict:
    current_chapter    = state["current_chapter_index"]
    current_subsection = state["current_subsection_index"]
    new_subsection     = current_subsection + 1
    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1}, "
        f"Subsection {current_subsection + 1} → Moving to Subsection {new_subsection + 1}"
    )
    content_update = _accumulate_content(state)
    return {
        **content_update,
        "current_subsection_index": new_subsection,
        "revision_number":          0,
        "chapter_header_written":   False,
        "messages": [f"✓ Completed: Chapter {current_chapter + 1}, Subsection {current_subsection + 1}"],
    }


def append_and_update_chapter(state: AgentState) -> dict:
    current_chapter = state["current_chapter_index"]
    new_chapter     = current_chapter + 1
    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1} → Moving to Chapter {new_chapter + 1}"
    )
    content_update = _accumulate_content(state)
    return {
        **content_update,
        "current_chapter_index":    new_chapter,
        "current_subsection_index": 0,
        "revision_number":          0,
        "chapter_header_written":   False,
        "messages": [f"✓ Completed: Chapter {current_chapter + 1} (all subsections)"],
    }


def check_next_step(state: AgentState) -> str:
    curriculum = state["curriculum"]
    chap_idx   = state["current_chapter_index"]
    sub_idx    = state["current_subsection_index"]
    try:
        if hasattr(curriculum, 'chapters'):
            chapters    = curriculum.chapters
            subsections = chapters[chap_idx].subsections
        else:
            chapters    = curriculum["chapters"]
            subsections = chapters[chap_idx]["subsections"]

        total_chapters    = len(chapters)
        total_subsections = len(subsections)

        if sub_idx < total_subsections - 1:
            logger.info(f"Decision: Continue subsection ({sub_idx + 1}/{total_subsections})")
            return WorkflowDecision.CONTINUE_SUBSECTION
        elif chap_idx < total_chapters - 1:
            logger.info(f"Decision: Next chapter ({chap_idx + 1}/{total_chapters})")
            return WorkflowDecision.NEXT_CHAPTER
        else:
            logger.info("Decision: Finished")
            return WorkflowDecision.FINISHED

    except (IndexError, KeyError, AttributeError) as e:
        logger.error(f"Workflow decision error: {e}")
        return WorkflowDecision.FINISHED
    except Exception as e:
        logger.error(f"Unexpected error in workflow decision: {e}", exc_info=True)
        return WorkflowDecision.FINISHED


# ---------------------------------------------------------------------------
# Shared helpers for building node sets
# ---------------------------------------------------------------------------

def _register_content_nodes(builder: StateGraph) -> None:
    """Register researcher → publisher nodes + checkpoint utilities."""
    builder.add_node("researcher",        perform_research)
    builder.add_node("writer",            write_section)
    builder.add_node("reviewer",          review_section)
    builder.add_node("illustrator",       illustrate_section)
    builder.add_node("publisher",         publish_curriculum)
    builder.add_node("update_subsection", append_and_update_subsection)
    builder.add_node("update_chapter",    append_and_update_chapter)


def _define_content_edges(builder: StateGraph) -> None:
    """Define all edges for the researcher-to-publisher loop."""
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer",     "reviewer")
    builder.add_conditional_edges(
        "reviewer", route_after_review,
        {WorkflowDecision.REVISE: "writer", WorkflowDecision.APPROVE: "illustrator"},
    )
    builder.add_conditional_edges(
        "illustrator", check_next_step,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "update_subsection",
            WorkflowDecision.NEXT_CHAPTER:        "update_chapter",
            WorkflowDecision.FINISHED:            "publisher",
        },
    )
    builder.add_edge("update_subsection", "researcher")
    builder.add_edge("update_chapter",    "researcher")
    builder.add_edge("publisher",         END)


# ---------------------------------------------------------------------------
# Public workflow factories
# ---------------------------------------------------------------------------

def create_workflow() -> CompiledStateGraph:
    """Full single-shot workflow: ingestion → planner → content loop → publisher."""
    logger.info("Building full workflow graph...")
    builder = StateGraph(AgentState)

    builder.add_node("ingestion", perform_ingestion)
    builder.add_node("planner",   plan_curriculum)
    _register_content_nodes(builder)

    builder.add_edge("ingestion", "planner")
    builder.add_edge("planner",   "researcher")
    _define_content_edges(builder)

    builder.set_entry_point("ingestion")
    graph = builder.compile()
    logger.info("✓ Full workflow compiled")
    return graph


def create_planning_workflow() -> CompiledStateGraph:
    """
    Phase-A workflow: ingestion + planning only.
    Terminates after planner emits curriculum — UI review gate follows.
    """
    logger.info("Building planning workflow (ingestion → planner → END)...")
    builder = StateGraph(AgentState)
    builder.add_node("validator",  validate_topic_node)
    builder.add_node("ingestion",  perform_ingestion)
    builder.add_node("planner",    plan_curriculum)
    builder.add_conditional_edges(
        "validator",
        lambda s: "end" if s.get("validation_failed") else "continue",
        {"end": END, "continue": "ingestion"},
    )
    builder.add_edge("ingestion", "planner")
    builder.add_edge("planner",   END)
    builder.set_entry_point("validator")
    graph = builder.compile()
    logger.info("✓ Planning workflow compiled")
    return graph


def create_content_workflow() -> CompiledStateGraph:
    """
    Phase-B workflow: content loop only.
    Expects curriculum + planning outputs already present in initial_state.
    Entry point: researcher.
    """
    logger.info("Building content workflow (researcher → … → publisher → END)...")
    builder = StateGraph(AgentState)
    _register_content_nodes(builder)
    _define_content_edges(builder)
    builder.set_entry_point("researcher")
    graph = builder.compile()
    logger.info("✓ Content workflow compiled")
    return graph