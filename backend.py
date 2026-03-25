"""
Workflow engine for AI Textbook Generator.

No Streamlit imports. Manages workflow thread execution in two phases:
  Phase A — planning:  ingestion + curriculum generation (create_planning_workflow)
  Phase B — content:   researcher → writer → reviewer → illustrator → publisher
                       (create_content_workflow, starts after user reviews curriculum)

Both phases use stream_workflow() with an injected app parameter so the
same event-emission logic covers both.
"""

import queue
import threading
from queue import Queue

from src.graph.workflow import create_workflow, create_planning_workflow, create_content_workflow
from src import stop_signal
from src.ui.events import EventType, WorkflowEvent


# ============================================================================
# Initial state builders
# ============================================================================

def build_initial_state(topic: str, **config) -> dict:
    """Construct the initial LangGraph state for the planning phase."""
    return {
        "request": topic,
        # User configuration
        "num_chapters":                config.get("num_chapters", 3),
        "enable_images":               config.get("enable_images", True),
        "content_level":               config.get("content_level", "Trung Bình"),
        "min_chars_per_section":       0,
        "max_subsections_per_chapter": config.get("max_subsections", 3),
        # Runtime — reset at workflow start
        "curriculum":               None,
        "textbook_title":           "",
        "preface_content":          "",
        "rag_context":              "",
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "revision_number":          0,
        "review_feedback":          "",
        "chapter_header_written":   False,
        "messages":                 [],
        "final_content":            "",
        "current_content":          "",
        "export_formats":           config.get("export_formats", ["Word"]),
        "final_docx_filepath":      None,
        "final_filepath":           None,
    }


def build_content_initial_state(
    planning_initial_state: dict,
    edited_curriculum,          # CurriculumOutline Pydantic object
    planner_result:    dict,    # {"textbook_title": ..., "preface_content": ...}
) -> dict:
    """
    Construct the initial state for the content-generation phase.

    Merges the original planning config with the (possibly edited) curriculum
    and the textbook_title / preface_content emitted by the Planner node.
    All progress/content buffers are reset to zero.

    Args:
        planning_initial_state: The dict passed to the planning workflow —
                                contains all user config fields.
        edited_curriculum:      CurriculumOutline object after optional user edits.
        planner_result:         Dict with keys "textbook_title" and "preface_content".

    Returns:
        Full AgentState-compatible dict ready for create_content_workflow().
    """
    return {
        **planning_initial_state,
        # Planning outputs
        "curriculum":     edited_curriculum,
        "textbook_title": planner_result.get("textbook_title", ""),
        "preface_content": planner_result.get("preface_content", ""),
        # Reset all progress / content buffers
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "current_content":          "",
        "final_content":            "",
        "revision_number":          0,
        "review_feedback":          "",
        "chapter_header_written":   False,
        "rag_context":              "",
        "messages":                 [],
        "final_filepath":           None,
        "final_docx_filepath":      None,
    }


# ============================================================================
# Streaming worker
# ============================================================================

def stream_workflow(
    initial_state:   dict,
    recursion_limit: int,
    event_q:         "queue.Queue[WorkflowEvent]",
    app=None,
) -> None:
    """
    Stream a LangGraph workflow and emit WorkflowEvents to event_q.

    Args:
        initial_state:   AgentState-compatible dict.
        recursion_limit: LangGraph recursion ceiling.
        event_q:         Queue consumed by the Streamlit drain loop.
        app:             Compiled StateGraph to run. Defaults to create_workflow()
                         (full pipeline) when None — keeps backward compatibility.
    """
    if app is None:
        app = create_workflow()

    # Cumulative state — merges all partial updates so chapter/sub indexes
    # are always current even when a node does not return them explicitly.
    cumulative: dict = dict(initial_state)

    # Pre-initialise chapter_subsection_counts from curriculum if already present.
    # This is the case for the content-only workflow which receives a pre-built
    # CurriculumOutline in initial_state (after user review).
    curriculum = initial_state.get("curriculum")
    chapter_subsection_counts: list[int] = []
    if curriculum and hasattr(curriculum, "chapters"):
        chapter_subsection_counts = [len(ch.subsections) for ch in curriculum.chapters]

    prev_stage: str = ""

    try:
        for event in app.stream(initial_state, {"recursion_limit": recursion_limit}):
            if stop_signal.is_stopped():
                event_q.put(WorkflowEvent(type=EventType.STOPPED))
                return

            for key, value in event.items():
                if isinstance(value, dict):
                    cumulative.update(value)

                chap_idx     = cumulative.get("current_chapter_index", 0)
                sub_idx      = cumulative.get("current_subsection_index", 0)
                subs_in_chap = (
                    chapter_subsection_counts[chap_idx]
                    if curriculum and chap_idx < len(chapter_subsection_counts)
                    else 0
                )

                if key == "ingestion":
                    event_q.put(WorkflowEvent(type=EventType.INGESTION_DONE))

                elif key == "planner":
                    curriculum = cumulative.get("curriculum")
                    if curriculum:
                        chapter_subsection_counts = [
                            len(ch.subsections) for ch in curriculum.chapters
                        ]
                    total_ch  = len(curriculum.chapters) if curriculum else 0
                    total_sub = sum(chapter_subsection_counts)
                    event_q.put(WorkflowEvent(
                        type=EventType.PLANNER_DONE,
                        curriculum=curriculum,
                        total_chapters=total_ch,
                        total_subsections=total_sub,
                        chapter_subsection_counts=chapter_subsection_counts,
                        textbook_title=cumulative.get("textbook_title", ""),
                        preface_content=cumulative.get("preface_content", ""),
                    ))
                elif key == "validator":
                    if cumulative.get("validation_failed"):
                        event_q.put(WorkflowEvent(
                            type=EventType.VALIDATION_FAILED,
                            validation_reason=cumulative.get("validation_reason", ""),
                            validation_suggestion=cumulative.get("validation_suggestion", ""),
                        ))
                    else:
                        # Validation passed — signal UI to show ingestion status
                        event_q.put(WorkflowEvent(type=EventType.INGESTION_START))
                elif key in ("researcher", "writer", "reviewer", "illustrator"):
                    if prev_stage and prev_stage != key:
                        event_q.put(WorkflowEvent(
                            type=EventType.CONTENT_UPDATE,
                            stage=prev_stage,
                            stage_status="done",
                            chapter_idx=chap_idx,
                            subsection_idx=sub_idx,
                            subsections_in_chapter=subs_in_chap,
                        ))
                    prev_stage = key
                    event_q.put(WorkflowEvent(
                        type=EventType.CONTENT_UPDATE,
                        stage=key,
                        stage_status="start",
                        chapter_idx=chap_idx,
                        subsection_idx=sub_idx,
                        subsections_in_chapter=subs_in_chap,
                    ))

                elif key in ("update_subsection", "update_chapter"):
                    if prev_stage:
                        event_q.put(WorkflowEvent(
                            type=EventType.CONTENT_UPDATE,
                            stage=prev_stage,
                            stage_status="done",
                            chapter_idx=chap_idx,
                            subsection_idx=sub_idx,
                            subsections_in_chapter=subs_in_chap,
                        ))
                        prev_stage = ""
                    event_q.put(WorkflowEvent(
                        type=EventType.CHECKPOINT,
                        chapter_idx=chap_idx,
                        subsection_idx=sub_idx,
                        subsections_in_chapter=subs_in_chap,
                    ))

                elif key == "publisher":
                    event_q.put(WorkflowEvent(
                        type=EventType.PUBLISHER_DONE,
                        final_filepath=cumulative.get("final_filepath"),
                        final_docx_filepath=cumulative.get("final_docx_filepath"),
                    ))

        event_q.put(WorkflowEvent(type=EventType.DONE))

    except Exception as exc:
        event_q.put(WorkflowEvent(type=EventType.ERROR, error=exc))


# ============================================================================
# Thread helpers
# ============================================================================

def _make_thread(target_app, initial_state: dict, recursion_limit: int, event_q: Queue) -> threading.Thread:
    """Internal: create and start a daemon thread for the given compiled app."""
    thread = threading.Thread(
        target=stream_workflow,
        args=(initial_state, recursion_limit, event_q),
        kwargs={"app": target_app},
        daemon=True,
    )
    thread.start()
    return thread


def start_planning_thread(initial_state: dict, recursion_limit: int, event_q: Queue) -> threading.Thread:
    """Start Phase-A: ingestion → planner → END."""
    return _make_thread(create_planning_workflow(), initial_state, recursion_limit, event_q)


def start_content_thread(initial_state: dict, recursion_limit: int, event_q: Queue) -> threading.Thread:
    """Start Phase-B: researcher → … → publisher → END."""
    return _make_thread(create_content_workflow(), initial_state, recursion_limit, event_q)


def start_workflow_thread(initial_state: dict, recursion_limit: int, event_q: Queue) -> threading.Thread:
    """Legacy full-pipeline thread (backward compatibility)."""
    return _make_thread(create_workflow(), initial_state, recursion_limit, event_q)