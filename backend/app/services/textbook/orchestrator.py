"""
LangGraph workflow orchestration for AI Textbook Generator.
"""

from enum import Enum

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

from app.schemas.curriculum import AgentState
from app.utils.log_config import setup_logger
from app.schemas.curriculum import (
    AgentState,
    SubSection,
    get_chapter_and_subsection,
    clean_section_title,
)
# CRAG pipeline nodes (Target 1)
from app.services.textbook.query_formulator import formulate_query
from app.services.textbook.retriever        import retriever_node
from app.services.textbook.evaluator        import evaluate_context
from app.services.textbook.writer           import write_section_crag, extract_section_summary
from app.services.textbook.ingester import perform_ingestion
from app.services.textbook.planner import plan_curriculum, generate_metadata_node    
from app.services.textbook.reviewer import review_section
from app.services.textbook.illustrator import illustrate_section
from app.services.textbook.publisher import publish_curriculum
from app.services.textbook.validator import validate_topic_node
from app.utils import stop_signal

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
    RETRY_RETRIEVAL     = "retry_retrieval"
    """
    Route back to QueryFormulator for a fresh retrieval attempt.
    Triggered by:
      - ContextEvaluator: context_quality == 'insufficient' (first attempt only)
      - Reviewer:         rejection_type == 'missing_context'
    """


def route_after_review(state: AgentState) -> str:
    """
    True Dynamic Routing gate (Target 2): classify rejection and route accordingly.

    Routing table:
        No feedback       → APPROVE  (to illustrator)
        missing_context   → RETRY_RETRIEVAL (back to QueryFormulator for re-fetch)
        formatting_error  → REVISE   (back to ContentWriter — same context, fix format)
        None / fallback   → REVISE   (safe default)
    """
    feedback       = state.get("review_feedback", "")
    rejection_type = state.get("rejection_type")

    if not feedback:
        logger.info("Review decision: APPROVE — proceeding to illustrator")
        return WorkflowDecision.APPROVE

    if rejection_type == "missing_context":
        logger.info(
            f"Review decision: RETRY_RETRIEVAL "
            f"(missing_context) — feedback: {feedback[:80]}"
        )
        return WorkflowDecision.RETRY_RETRIEVAL

    # formatting_error OR None — content knowledge is correct, fix structure only
    logger.info(
        f"Review decision: REVISE "
        f"(rejection_type='{rejection_type}') — feedback: {feedback[:80]}"
    )
    return WorkflowDecision.REVISE


def route_after_ingestion(state: AgentState) -> str:
    """
    Guard gate: verify ingestion succeeded before starting the CRAG loop.

    Reads the last ingestion status message to determine if ChromaDB was
    populated. If ingestion failed (no URLs found, all filtered, crawl error),
    routes to END rather than allowing the CRAG loop to run against an
    empty database and hallucinate content.

    Returns:
        CONTINUE_SUBSECTION — ingestion succeeded, proceed to query_formulator
        FINISHED            — ingestion failed, terminate workflow gracefully
    """
    messages = state.get("messages", [])

    for msg in reversed(messages[-5:]):
        if isinstance(msg, str):
            if msg.startswith("✓ Ingestion complete"):
                logger.info("Ingestion gate: PASSED — proceeding to CRAG loop")
                return WorkflowDecision.CONTINUE_SUBSECTION
            if msg.startswith("✗ Ingestion failed") or msg.startswith("⛔"):
                logger.error(
                    f"Ingestion gate: FAILED — aborting workflow. Reason: {msg}"
                )
                return WorkflowDecision.FINISHED

    logger.warning(
        "Ingestion gate: no clear success/failure signal in messages — "
        "proceeding to CRAG loop (fail open)"
    )
    return WorkflowDecision.CONTINUE_SUBSECTION


def route_after_context_evaluation(state: AgentState) -> str:
    """
    CRAG routing gate: decide whether retrieved context is sufficient to write.

    Retry logic (max 1 retry per subsection, no new state field needed):
        used_rag_queries == [] means ContextEvaluator made no supplemental
        tool calls — the initial ChromaDB context was all there was.
        One retry is allowed in this case (QueryFormulator shifts query angle).

        used_rag_queries != [] means supplemental fetches were already attempted.
        Proceed to ContentWriter regardless — fail open.

    Args:
        state: Current LangGraph workflow state.

    Returns:
        RETRY_RETRIEVAL     — route back to QueryFormulator for re-fetch
        CONTINUE_SUBSECTION — route forward to ContentWriter
    """
    context_quality = state.get("context_quality", "sufficient")
    used_queries    = state.get("used_rag_queries", [])

    if context_quality == "insufficient" and len(used_queries) == 0:
        logger.info(
            "Context quality: INSUFFICIENT (no supplemental fetches attempted) "
            "— retrying via QueryFormulator"
        )
        return WorkflowDecision.RETRY_RETRIEVAL

    if context_quality == "insufficient":
        logger.warning(
            "Context quality: still INSUFFICIENT after supplemental fetch "
            "— proceeding to ContentWriter (fail open)"
        )
    else:
        logger.info("Context quality: SUFFICIENT — proceeding to ContentWriter")

    return WorkflowDecision.CONTINUE_SUBSECTION



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
        f"Subsection {current_subsection + 1} → Moving to {new_subsection + 1}"
    )

    content_update = _accumulate_content(state)

    # Extract summary từ section vừa approve để Writer dùng ở section tiếp theo
    completed_content = state.get("current_content", "")
    display_sec       = f"{current_chapter + 1}.{current_subsection + 1}"
    try:
        curriculum  = state["curriculum"]
        _, subsection = get_chapter_and_subsection(curriculum, current_chapter, current_subsection)
        sec_title   = subsection.title if isinstance(subsection, SubSection) else subsection.get("title", "")
        sec_title   = clean_section_title(sec_title)
        new_summary = extract_section_summary(completed_content, display_sec, sec_title)
        prior       = state.get("section_summaries", [])
        updated_summaries = prior + [new_summary]
    except Exception as e:
        logger.warning(f"Failed to extract section summary: {e}")
        updated_summaries = state.get("section_summaries", [])

    return {
        **content_update,
        "current_subsection_index": new_subsection,
        "revision_number":          0,
        "chapter_header_written":   False,
        "section_summaries":        updated_summaries,
        # Reset per-subsection accumulators
        "used_rag_queries":         [],
        # Reset CRAG pipeline fields for next subsection
        "retrieval_query":          "",
        "context_quality":          "sufficient",
        "web_supplement_context":   "",
        "rejection_type":           None,
        "messages": [
            f"✓ Completed: Chapter {current_chapter + 1}, "
            f"Subsection {current_subsection + 1}"
        ],
    }



def append_and_update_chapter(state: AgentState) -> dict:
    current_chapter = state["current_chapter_index"]
    new_chapter     = current_chapter + 1

    logger.info(
        f"Checkpoint: Completed Chapter {current_chapter + 1} → "
        f"Moving to Chapter {new_chapter + 1}"
    )

    content_update = _accumulate_content(state)

    # Extract summary cho subsection cuối của chapter
    completed_content  = state.get("current_content", "")
    current_subsection = state["current_subsection_index"]
    display_sec        = f"{current_chapter + 1}.{current_subsection + 1}"
    try:
        curriculum = state["curriculum"]
        _, subsection = get_chapter_and_subsection(curriculum, current_chapter, current_subsection)
        sec_title  = subsection.title if isinstance(subsection, SubSection) else subsection.get("title", "")
        sec_title  = clean_section_title(sec_title)
        new_summary = extract_section_summary(completed_content, display_sec, sec_title)
        prior       = state.get("section_summaries", [])
        updated_summaries = prior + [new_summary]
    except Exception as e:
        logger.warning(f"Failed to extract section summary: {e}")
        updated_summaries = state.get("section_summaries", [])

    result: dict = {
        **content_update,
        "current_chapter_index":    new_chapter,
        "current_subsection_index": 0,
        "revision_number":          0,
        "chapter_header_written":   False,
        "section_summaries":        updated_summaries,
        # Reset per-subsection accumulators
        "used_rag_queries":         [],
        # Reset CRAG pipeline fields for next chapter's first subsection
        "retrieval_query":          "",
        "context_quality":          "sufficient",
        "web_supplement_context":   "",
        "rejection_type":           None,
        "messages": [f"✓ Completed: Chapter {current_chapter + 1}"],
    }

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
    """Register CRAG pipeline nodes + quality/output pipeline + checkpoint utilities."""
    # CRAG pipeline (Target 1)
    builder.add_node("query_formulator",  _with_stop_check(formulate_query))
    builder.add_node("retriever_node",    _with_stop_check(retriever_node))
    builder.add_node("context_evaluator", _with_stop_check(evaluate_context))
    builder.add_node("content_writer",    _with_stop_check(write_section_crag))
    # Quality + output pipeline (unchanged)
    builder.add_node("reviewer",          _with_stop_check(review_section))
    builder.add_node("illustrator",       _with_stop_check(illustrate_section))
    builder.add_node("publisher",         _with_stop_check(publish_curriculum))
    builder.add_node("update_subsection", _with_stop_check(append_and_update_subsection))
    builder.add_node("update_chapter",    _with_stop_check(append_and_update_chapter))



def _define_content_edges(builder: StateGraph) -> None:
    """
    Define CRAG pipeline edges for the full content generation loop.

    Topology:
        query_formulator → retriever_node → context_evaluator
            → [route_after_context_evaluation]
                insufficient (first attempt) → query_formulator   (re-fetch)
                sufficient / retried         → content_writer

        content_writer → reviewer
            → [route_after_review — True Dynamic Routing]
                approve          → illustrator
                formatting_error → content_writer   (rewrite, same context)
                missing_context  → query_formulator  (full re-retrieval cycle)

        illustrator → [check_next_step]
            → update_subsection → query_formulator
            → update_chapter    → query_formulator
            → publisher         → END
    """
    # CRAG linear chain
    builder.add_edge("query_formulator", "retriever_node")
    builder.add_edge("retriever_node",   "context_evaluator")

    # Context quality gate
    builder.add_conditional_edges(
        "context_evaluator", route_after_context_evaluation,
        {
            WorkflowDecision.RETRY_RETRIEVAL:     "query_formulator",
            WorkflowDecision.CONTINUE_SUBSECTION: "content_writer",
        },
    )

    builder.add_edge("content_writer", "reviewer")

    # True Dynamic Routing after review
    builder.add_conditional_edges(
        "reviewer", route_after_review,
        {
            WorkflowDecision.APPROVE:         "illustrator",
            WorkflowDecision.REVISE:          "content_writer",
            WorkflowDecision.RETRY_RETRIEVAL: "query_formulator",
        },
    )

    # Progress checkpoint routing (unchanged logic, updated target node)
    builder.add_conditional_edges(
        "illustrator", check_next_step,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "update_subsection",
            WorkflowDecision.NEXT_CHAPTER:        "update_chapter",
            WorkflowDecision.FINISHED:            "publisher",
        },
    )
    builder.add_edge("update_subsection", "query_formulator")
    builder.add_edge("update_chapter",    "query_formulator")
    builder.add_edge("publisher",         END)


# ---------------------------------------------------------------------------
# Public workflow factories
# ---------------------------------------------------------------------------

def create_planning_only_workflow() -> CompiledStateGraph:
    """
    Planning-only workflow: generate curriculum without crawling.

    Entry point: planner → END

    Used for initial curriculum generation. User reviews curriculum,
    then triggers the content generation workflow separately.
    """
    logger.info("Building planning-only workflow (planner → END)...")
    builder = StateGraph(AgentState)

    builder.add_node("planner", _with_stop_check(plan_curriculum))
    builder.set_entry_point("planner")
    builder.add_edge("planner", END)

    graph = builder.compile()
    logger.info("✓ Planning-only workflow compiled")
    return graph


def create_content_after_confirm_workflow() -> CompiledStateGraph:
    """
    Content generation workflow: crawl → generate → publish.

    Entry point: ingestion → researcher → writer → ... → publisher → END

    Used after user confirms curriculum. Curriculum already in state.
    """
    logger.info("Building post-confirmation workflow (preface → ingestion → content → publish)...")
    builder = StateGraph(AgentState)

    builder.add_node("generate_preface", _with_stop_check(generate_metadata_node))
    builder.add_node("ingestion",        _with_stop_check(perform_ingestion))
    _register_content_nodes(builder)

    builder.set_entry_point("generate_preface")
    builder.add_edge("generate_preface", "ingestion")
    builder.add_conditional_edges(
        "ingestion", route_after_ingestion,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "query_formulator",
            WorkflowDecision.FINISHED:            END,
        },
    )
    _define_content_edges(builder)

    graph = builder.compile()
    logger.info("✓ Post-confirmation workflow compiled")
    return graph


def create_workflow() -> CompiledStateGraph:
    """
    Full workflow: planner → ingestion → researcher → ... → publisher.

    Legacy workflow — runs everything in one shot without a user review gate.
    Prefer create_planning_only_workflow() + create_content_after_confirm_workflow()
    for the two-phase flow with curriculum review.
    """
    logger.info("Building full workflow (planner → ingestion → content)...")
    builder = StateGraph(AgentState)

    builder.add_node("planner",          _with_stop_check(plan_curriculum))
    builder.add_node("generate_preface", _with_stop_check(generate_metadata_node))
    builder.add_node("ingestion",        _with_stop_check(perform_ingestion))
    _register_content_nodes(builder)

    builder.set_entry_point("planner")
    builder.add_edge("planner",          "generate_preface")
    builder.add_edge("generate_preface", "ingestion")
    builder.add_conditional_edges(
        "ingestion", route_after_ingestion,
        {
            WorkflowDecision.CONTINUE_SUBSECTION: "query_formulator",
            WorkflowDecision.FINISHED:            END,
        },
    )
    _define_content_edges(builder)

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
    """
    logger.info("Building content workflow (researcher → … → publisher → END)...")
    builder = StateGraph(AgentState)
    _register_content_nodes(builder)
    _define_content_edges(builder)
    builder.set_entry_point("researcher")
    graph = builder.compile()
    logger.info("✓ Content workflow compiled")
    return graph