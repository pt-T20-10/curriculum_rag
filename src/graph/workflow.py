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
from src import stop_signal

logger = setup_logger(name="WorkflowBuilder", logfile="logs/workflow.log")

def _with_stop_check(node_fn):
    """
    Wrap a LangGraph node function with a pre-execution stop signal check.
    If stop is requested before the node runs, return empty dict immediately
    instead of executing — skips the node without crashing the graph.
    """
    def wrapper(state: AgentState) -> dict:
        if stop_signal.is_stopped():
            logger.info(f"Stop signal detected — skipping node '{node_fn.__name__}'")
            return {}
        return node_fn(state)
    wrapper.__name__ = node_fn.__name__
    return wrapper
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
        "messages": [
            f"✓ Completed: Chapter {current_chapter + 1}, "
            f"Subsection {current_subsection + 1}"
        ],
    }


def append_and_update_chapter(state: AgentState) -> dict:
    """
    Checkpoint node: accumulate content and advance to the next chapter.

    When this fires for Chapter 1 (current_chapter_index == 0), the
    accumulated final_content is also snapshot into chapter1_content so
    the UI preview gate can display it without touching final_content.
    """
    current_chapter = state["current_chapter_index"]
    new_chapter     = current_chapter + 1
    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1} → "
        f"Moving to Chapter {new_chapter + 1}"
    )
    content_update = _accumulate_content(state)

    result: dict = {
        **content_update,
        "current_chapter_index":    new_chapter,
        "current_subsection_index": 0,
        "revision_number":          0,
        "chapter_header_written":   False,
        "messages": [f"✓ Completed: Chapter {current_chapter + 1} (all subsections)"],
    }

    # Snapshot Chapter 1 content for the preview gate.
    # Only captured once — when the first chapter finishes.
    if current_chapter == 0:
        result["chapter1_content"] = content_update["final_content"]
        logger.info("Chapter 1 content snapshot saved for preview gate")

    return result


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


def check_next_step_ch1(state: AgentState) -> str:
    """
    Routing function for the Chapter-1-only workflow.

    Identical to check_next_step() except NEXT_CHAPTER routes to END
    instead of update_chapter, so the graph terminates after Chapter 1
    completes and hands control back to the UI preview gate.
    """
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

        total_subsections = len(subsections)
        total_chapters    = len(chapters)

        if sub_idx < total_subsections - 1:
            return WorkflowDecision.CONTINUE_SUBSECTION

        elif chap_idx < total_chapters - 1:
            # Chapter 1 done — stop here for preview gate
            logger.info("Chapter 1 complete — routing to END for preview gate")
            return WorkflowDecision.NEXT_CHAPTER   # mapped to update_chapter → END

        else:
            # Single-chapter textbook — go straight to publisher
            return WorkflowDecision.FINISHED

    except (IndexError, KeyError, AttributeError) as e:
        logger.error(f"ch1 workflow decision error: {e}")
        return WorkflowDecision.FINISHED
    except Exception as e:
        logger.error(f"Unexpected error in ch1 workflow decision: {e}", exc_info=True)
        return WorkflowDecision.FINISHED


# ---------------------------------------------------------------------------
# Shared node registration helpers
# ---------------------------------------------------------------------------

def _register_content_nodes(builder: StateGraph) -> None:
    """Register researcher → publisher nodes + checkpoint utilities."""
    builder.add_node("researcher",        _with_stop_check(perform_research))
    builder.add_node("writer",            _with_stop_check(write_section))
    builder.add_node("reviewer",          _with_stop_check(review_section))
    builder.add_node("illustrator",       _with_stop_check(illustrate_section))
    builder.add_node("publisher",         _with_stop_check(publish_curriculum))
    builder.add_node("update_subsection", _with_stop_check(append_and_update_subsection))
    builder.add_node("update_chapter",    _with_stop_check(append_and_update_chapter))


def _define_content_edges(builder: StateGraph) -> None:
    """Define all edges for the full researcher-to-publisher loop."""
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
    Phase-A workflow: topic validation + ingestion + curriculum planning.
    Terminates after planner — UI curriculum review gate follows.

    Entry point: validator
    Route: validator → (invalid → END) | (valid → ingestion → planner → END)
    """
    logger.info("Building planning workflow (validator → ingestion → planner → END)...")
    builder = StateGraph(AgentState)
    builder.add_node("validator", _with_stop_check(validate_topic_node))
    builder.add_node("ingestion", _with_stop_check(perform_ingestion))
    builder.add_node("planner",   _with_stop_check(plan_curriculum))
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


def create_chapter1_workflow() -> CompiledStateGraph:
    """
    Phase-B1 workflow: generate Chapter 1 only, then stop for preview.

    Uses check_next_step_ch1() which routes NEXT_CHAPTER to update_chapter → END
    instead of continuing, so the graph terminates after the first chapter
    checkpoint and returns control to the UI preview gate.

    For single-chapter textbooks, routes FINISHED → publisher as normal.

    Entry point: researcher (curriculum already in state from Phase A)
    """
    logger.info("Building Chapter 1 workflow (researcher → ch1 loop → END)...")
    builder = StateGraph(AgentState)

    builder.add_node("researcher",        _with_stop_check(perform_research))
    builder.add_node("writer",            _with_stop_check(write_section))
    builder.add_node("reviewer",          _with_stop_check(review_section))
    builder.add_node("illustrator",       _with_stop_check(illustrate_section))
    builder.add_node("publisher",         _with_stop_check(publish_curriculum))
    builder.add_node("update_subsection", _with_stop_check(append_and_update_subsection))
    builder.add_node("update_chapter",    _with_stop_check(append_and_update_chapter))

    builder.add_edge("researcher", "writer")
    builder.add_edge("writer",     "reviewer")
    builder.add_conditional_edges(
        "reviewer", route_after_review,
        {WorkflowDecision.REVISE: "writer", WorkflowDecision.APPROVE: "illustrator"},
    )
    builder.add_conditional_edges(
        "illustrator", check_next_step_ch1,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "update_subsection",
            WorkflowDecision.NEXT_CHAPTER:        "update_chapter",   # → END after ch1
            WorkflowDecision.FINISHED:            "publisher",        # single-chapter
        },
    )
    builder.add_edge("update_subsection", "researcher")
    builder.add_edge("update_chapter",    END)   # stop after ch1 checkpoint
    builder.add_edge("publisher",         END)

    builder.set_entry_point("researcher")
    graph = builder.compile()
    logger.info("✓ Chapter 1 workflow compiled")
    return graph


def create_remaining_workflow() -> CompiledStateGraph:
    """
    Phase-B2 workflow: generate Chapter 2 onwards and publish.

    Starts from current_chapter_index (already 1 after Chapter 1 checkpoint)
    and runs the full content loop through to publisher.

    Entry point: researcher
    """
    logger.info("Building remaining chapters workflow (researcher → … → publisher → END)...")
    builder = StateGraph(AgentState)
    _register_content_nodes(builder)
    _define_content_edges(builder)
    builder.set_entry_point("researcher")
    graph = builder.compile()
    logger.info("✓ Remaining chapters workflow compiled")
    return graph


def create_content_workflow() -> CompiledStateGraph:
    """
    Legacy Phase-B workflow: full content loop (all chapters) → publisher.
    Kept for backward compatibility. Prefer create_chapter1_workflow() +
    create_remaining_workflow() for Phase 5 preview gate support.
    """
    logger.info("Building content workflow (researcher → … → publisher → END)...")
    builder = StateGraph(AgentState)
    _register_content_nodes(builder)
    _define_content_edges(builder)
    builder.set_entry_point("researcher")
    graph = builder.compile()
    logger.info("✓ Content workflow compiled")
    return graph