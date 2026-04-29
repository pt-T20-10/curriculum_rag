"""
Workflow engine for AI Textbook Generator.

No Streamlit imports. Manages workflow thread execution across three phases:
  Phase A    — planning:   validator + ingestion + curriculum generation
  Phase B1   — chapter1:  researcher → … → update_chapter (Chapter 1 only)
  Phase B2   — remaining: researcher → … → publisher (Chapter 2 onwards)

All phases share stream_workflow() with an injected app parameter.
"""

import queue
import threading
from queue import Queue
from backend.app.services.textbook.ingester import set_ingestion_callback
from backend.app.services.textbook.orchestrator import (
    create_workflow,
    create_planning_workflow,
    create_content_workflow,
    create_chapter1_workflow,
    create_remaining_workflow,
)
from backend.app.utils import stop_signal
from streamlit_app.ui.events import EventType, WorkflowEvent


# ============================================================================
# Initial state builders
# ============================================================================

def build_initial_state(topic: str, **config) -> dict:
    """Construct the initial LangGraph state for the planning phase."""
    return {
        "request": topic,
        "num_chapters":                config.get("num_chapters", 3),
        "enable_images":               config.get("enable_images", True),
        "content_level":               config.get("content_level", "Trung Bình"),
        "min_chars_per_section":       0,
        "max_subsections_per_chapter": config.get("max_subsections", 3),
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
        "validation_failed":        False,
        "validation_reason":        "",
        "validation_suggestion":    "",
        "chapter1_content":         "",
        "content_type":             "",     
        "section_summaries":        [], 
    }


def build_content_initial_state(
    planning_initial_state: dict,
    edited_curriculum,
    planner_result: dict,
) -> dict:
    """
    Construct the initial state for the Chapter-1 content generation phase.

    Merges planning config with edited curriculum and planner outputs.
    All progress/content buffers reset to zero.

    Args:
        planning_initial_state: Dict from the planning workflow.
        edited_curriculum:      CurriculumOutline after optional user edits.
        planner_result:         Dict with textbook_title and preface_content.

    Returns:
        AgentState-compatible dict for create_chapter1_workflow().
    """
    return {
        **planning_initial_state,
        "curriculum":               edited_curriculum,
        "textbook_title":           planner_result.get("textbook_title", ""),
        "preface_content":          planner_result.get("preface_content", ""),
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "current_content":          "",
        "final_content":            "",
        "chapter1_content":         "",
        "revision_number":          0,
        "review_feedback":          "",
        "chapter_header_written":   False,
        "rag_context":              "",
        "messages":                 [],
        "final_filepath":           None,
        "final_docx_filepath":      None,
        "section_summaries":        [], 
    }


def build_remaining_state(content_initial_state: dict, chapter1_content: str) -> dict:
    """
    Construct the initial state for the remaining-chapters generation phase.

    Picks up where Chapter 1 left off:
      - current_chapter_index = 1  (advanced by update_chapter checkpoint)
      - final_content = chapter1_content  (Chapter 1 accumulated content)

    Args:
        content_initial_state: State dict used to start Chapter 1 generation.
        chapter1_content:      Accumulated markdown of Chapter 1.

    Returns:
        AgentState-compatible dict for create_remaining_workflow().
    """
    return {
        **content_initial_state,
        "current_chapter_index":    1,
        "current_subsection_index": 0,
        "current_content":          "",
        "final_content":            chapter1_content,
        "chapter1_content":         chapter1_content,
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
        app:             Compiled StateGraph. Defaults to create_workflow().
    """
    if app is None:
        app = create_workflow()

    
    def _ingestion_progress(message: str) -> None:
        print(f"[DEBUG BACKEND] putting event to queue: {message}", flush=True)
        event_q.put(WorkflowEvent(
            type=EventType.INGESTION_PROGRESS,
            progress_message=message,
        ))

    set_ingestion_callback(_ingestion_progress) 
    cumulative: dict = dict(initial_state)

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

                if key == "validator":
                    if cumulative.get("validation_failed"):
                        event_q.put(WorkflowEvent(
                            type=EventType.VALIDATION_FAILED,
                            validation_reason=cumulative.get("validation_reason", ""),
                            validation_suggestion=cumulative.get("validation_suggestion", ""),
                        ))
                    else:
                        # Validation passed — signal UI to show ingestion progress
                        event_q.put(WorkflowEvent(type=EventType.INGESTION_START))

                elif key == "ingestion":
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

                    # Phase 5: emit preview event when Chapter 1 snapshot is set.
                    # append_and_update_chapter() writes chapter1_content when
                    # current_chapter_index was 0 before advancing.
                    ch1_snap = cumulative.get("chapter1_content", "")
                    if key == "update_chapter" and ch1_snap:
                        event_q.put(WorkflowEvent(
                            type=EventType.CHAPTER1_PREVIEW,
                            chapter1_content=ch1_snap,
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

def _make_thread(
    target_app,
    initial_state:   dict,
    recursion_limit: int,
    event_q:         Queue,
) -> threading.Thread:
    """Create and start a daemon thread running stream_workflow."""
    thread = threading.Thread(
        target=stream_workflow,
        args=(initial_state, recursion_limit, event_q),
        kwargs={"app": target_app},
        daemon=True,
    )
    thread.start()
    return thread


def start_planning_thread(
    initial_state: dict, recursion_limit: int, event_q: Queue
) -> threading.Thread:
    """Start Phase-A: validator → ingestion → planner → END."""
    return _make_thread(create_planning_workflow(), initial_state, recursion_limit, event_q)


def start_chapter1_thread(
    initial_state: dict, recursion_limit: int, event_q: Queue
) -> threading.Thread:
    """Start Phase-B1: researcher → Chapter 1 loop → update_chapter → END."""
    return _make_thread(create_chapter1_workflow(), initial_state, recursion_limit, event_q)


def start_remaining_thread(
    initial_state: dict, recursion_limit: int, event_q: Queue
) -> threading.Thread:
    """Start Phase-B2: researcher → remaining chapters → publisher → END."""
    return _make_thread(create_remaining_workflow(), initial_state, recursion_limit, event_q)


def start_content_thread(
    initial_state: dict, recursion_limit: int, event_q: Queue
) -> threading.Thread:
    """Legacy: full content loop without Chapter 1 preview gate."""
    return _make_thread(create_content_workflow(), initial_state, recursion_limit, event_q)


def start_workflow_thread(
    initial_state: dict, recursion_limit: int, event_q: Queue
) -> threading.Thread:
    """Legacy full-pipeline thread (backward compatibility)."""
    return _make_thread(create_workflow(), initial_state, recursion_limit, event_q)