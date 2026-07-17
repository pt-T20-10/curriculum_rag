"""
Workflow runner with real-time progress updates.

Integrates LangGraph workflow with database progress tracking.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.textbook import Textbook
from app.config import settings
from app.schemas.curriculum import AgentState, build_initial_state
from app.services.api_rate_limiter import (
    api_usage_context,
    get_api_usage_summary,
    reset_api_usage_summary,
)
from app.services.textbook.language import get_language_profile, progress_text
from app.services.textbook.page_budget import allocate_page_budget
from app.utils.log_config import setup_logger
from app.utils.stop_signal import WorkflowStoppedException

logger = setup_logger(name="WorkflowRunner", logfile="logs/workflow_runner.log")


def _cleanup_rag_after_export(state: Dict[str, Any]) -> None:
    if not getattr(settings, "CLEANUP_RAG_COLLECTION_AFTER_EXPORT", True):
        return

    collection_name = str(state.get("rag_collection_name") or "")
    if not collection_name:
        return

    try:
        from app.services.textbook.ingester import cleanup_rag_collection

        cleanup_rag_collection(collection_name)
    except Exception as e:
        logger.warning("RAG cleanup after export failed: %s", e)


def _validated_artifact_path(value: Any, suffix: str) -> str | None:
    """Accept only an existing, non-empty artifact of the expected type."""
    if not value:
        return None
    path = Path(str(value))
    if path.suffix.lower() != suffix or not path.is_file() or path.stat().st_size <= 0:
        return None
    return str(path)


def _context_failure_error(state: Dict[str, Any]) -> str:
    """Build a concise error for a strict RAG gate stop."""
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    subsection = int(state.get("current_subsection_index", 0) or 0) + 1
    audit = state.get("rag_source_audit") or {}
    warnings = audit.get("warnings") if isinstance(audit, dict) else None
    warning = ""
    if isinstance(warnings, list) and warnings:
        warning = f" {str(warnings[0])}"
    return (
        f"Insufficient RAG context for Chapter {chapter}.{subsection}; "
        "stopped before writing to avoid unsupported content."
        f"{warning}"
    )


def _has_publishable_content(state: Dict[str, Any]) -> bool:
    return bool(
        str(state.get("final_content") or "").strip()
        or str(state.get("current_content") or "").strip()
    )


def _publish_recoverable_content(
    state: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    """
    Best-effort export for interrupted runs.

    If the workflow stops after at least one section has been written, preserve
    that content by running the same Publisher used by the normal final node.
    """
    if not _has_publishable_content(state):
        return {}

    try:
        from app.services.textbook.publisher import publish_curriculum

        logger.warning("Emergency publishing partial textbook after interruption: %s", reason)
        publish_state: Dict[str, Any] = {
            **state,
            "messages": [],
            "emergency_publish_reason": reason,
        }
        update = publish_curriculum(publish_state)  # type: ignore[arg-type]
        if isinstance(update, dict):
            state.update(update)
    except Exception as exc:
        logger.warning("Emergency publish failed: %s", exc, exc_info=True)
        state.setdefault("export_errors", {})
        if isinstance(state["export_errors"], dict):
            state["export_errors"]["emergency_publish"] = str(exc)

    return {
        "markdown_path": _validated_artifact_path(
            state.get("final_markdown_filepath"),
            ".md",
        ),
        "pdf_path": _validated_artifact_path(
            state.get("final_pdf_filepath") or state.get("final_filepath"),
            ".pdf",
        ),
        "docx_path": _validated_artifact_path(
            state.get("final_docx_filepath"),
            ".docx",
        ),
        "export_errors": state.get("export_errors") or {},
    }


def _has_emergency_artifact(artifacts: Dict[str, Any]) -> bool:
    return bool(
        artifacts.get("markdown_path")
        or artifacts.get("pdf_path")
        or artifacts.get("docx_path")
    )


async def update_progress(
    db: AsyncSession,
    textbook_id: int,
    progress_data: Dict[str, Any]
) -> None:
    """Update textbook progress_data in database."""
    try:
        result = await db.execute(
            select(Textbook).where(Textbook.id == textbook_id)
        )
        textbook = result.scalar_one_or_none()

        if textbook:
            textbook.progress_data = progress_data  # type: ignore
            await db.commit()
            logger.info(f"Progress updated for textbook {textbook_id}: phase={progress_data.get('phase')}")
    except Exception as e:
        logger.error(f"Failed to update progress: {e}")


async def run_textbook_workflow(
    textbook_id: int,
    topic: str,
    num_chapters: int,
    content_level: str,
    max_subsections_per_chapter: int,
    enable_images: bool,
    export_formats: list,
    language: str = "vi",
    advanced_config: dict[str, Any] | None = None,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Run planning phase only — generate curriculum for user review.

    Uses planning-only workflow (planner → END).
    Ingestion happens AFTER user confirms curriculum.

    Returns:
        dict with success status and curriculum data for review
    """
    if db:
        result = await db.execute(select(Textbook).where(Textbook.id == textbook_id))
        textbook_record = result.scalar_one_or_none()
        core_topic_val = textbook_record.core_topic if textbook_record else topic
        user_req_val = textbook_record.user_requirements if textbook_record else ""
        content_type_val = textbook_record.content_type if textbook_record else "technical"
        textbook_mode_val = textbook_record.textbook_mode if textbook_record else "standard"
        formula_policy_val = textbook_record.formula_policy if textbook_record else "auto"
        formula_need_val = textbook_record.formula_need if textbook_record else "none"
        language_val = textbook_record.language if textbook_record else language
        source_preferences_val = textbook_record.source_preferences if textbook_record else {}
        progress_data_val = dict(textbook_record.progress_data or {}) if textbook_record else {}
        target_pages_val = progress_data_val.get("target_pages")
        planning_mode_val = str(
            progress_data_val.get("planning_mode")
            or ("structured" if textbook_record and textbook_record.curriculum_json else "auto")
        )
        initial_structure_val = (
            textbook_record.curriculum_json
            if textbook_record and planning_mode_val == "structured"
            else None
        )
    else:
        core_topic_val = topic
        user_req_val = ""
        content_type_val = "technical"
        textbook_mode_val = "standard"
        formula_policy_val = "auto"
        formula_need_val = "none"
        language_val = language
        source_preferences_val = {}
        target_pages_val = None
        planning_mode_val = "auto"
        initial_structure_val = None
    # Build initial state
    initial_state: AgentState = build_initial_state( # type: ignore
        request=topic,
        num_chapters=num_chapters,
        enable_images=enable_images,
        content_level=content_level,
        max_subsections_per_chapter=max_subsections_per_chapter,
        content_type=content_type_val, #type: ignore
        textbook_mode=textbook_mode_val, #type: ignore
        formula_policy=formula_policy_val, #type: ignore
        formula_need=formula_need_val, #type: ignore
        core_topic=core_topic_val, #type: ignore
        user_requirements=user_req_val, #type: ignore
        language=language_val, #type: ignore
        advanced_config=advanced_config,
        source_preferences=source_preferences_val, #type: ignore[arg-type]
        initial_curriculum_structure=initial_structure_val, #type: ignore
        planning_mode=planning_mode_val,
        export_formats=export_formats,
    )

    # Use planning-only workflow (planner → END)
    from app.services.textbook.orchestrator import create_planning_only_workflow
    app = create_planning_only_workflow()
    api_run_id = f"textbook:{textbook_id}:planning"
    reset_api_usage_summary(api_run_id)

    try:
        logger.info(f"[Workflow] Starting planning phase for: {topic}")

        if db:
            await update_progress(db, textbook_id, {
                "phase": "planning",
                "progress_value": 10.0,
                "status_text": progress_text(language_val, "planning_started"), #type: ignore
                "planner_status": "active",
                "ingestion_status": "pending",
                "publisher_status": "pending",
                "topic": topic,
                "language": language_val,
                "planning_mode": planning_mode_val,
                "textbook_mode": textbook_mode_val,
                "source_preferences": source_preferences_val,
            })

        cumulative_state: Dict[str, Any] = dict(initial_state)

        with api_usage_context(run_id=api_run_id, textbook_id=textbook_id, phase="planning"):
            event_stream = app.stream(
                initial_state,
                {"recursion_limit": settings.PLANNING_WORKFLOW_RECURSION_LIMIT},
            )
            for event in event_stream:
                for node_name, node_output in event.items():
                    if isinstance(node_output, dict):
                        cumulative_state.update(node_output)

                    if node_name == "planner" and db:
                        curriculum = cumulative_state.get("curriculum")
                        textbook_title = cumulative_state.get("textbook_title", "")  # ⭐ Get generated title

                        curriculum_data = None
                        chapter_titles = []
                        page_validation = None

                        if curriculum:
                            profile = get_language_profile(language_val) #type: ignore
                            if hasattr(curriculum, 'model_dump'):
                                curriculum_data = curriculum.model_dump()
                            elif hasattr(curriculum, 'dict'):
                                curriculum_data = curriculum.dict()
                            else:
                                curriculum_data = dict(curriculum)

                            chapters = curriculum.chapters if hasattr(curriculum, 'chapters') else curriculum.get('chapters', [])
                            chapter_titles = [
                                ch.title if hasattr(ch, 'title') else ch.get(
                                    'title',
                                    f"{profile.chapter_label.title()} {i+1}",
                                )
                                for i, ch in enumerate(chapters)
                            ]
                            if target_pages_val:
                                curriculum_data, page_validation = allocate_page_budget(
                                    curriculum_data,
                                    target_pages=target_pages_val,
                                    enable_images=enable_images,
                                    language=language_val,  # type: ignore[arg-type]
                                    textbook_mode=textbook_mode_val,  # type: ignore[arg-type]
                                    formula_policy=formula_policy_val,  # type: ignore[arg-type]
                                )
                        # ⭐ Update textbook title in database
                        if textbook_title:
                            result = await db.execute(select(Textbook).where(Textbook.id == textbook_id))
                            textbook_record = result.scalar_one_or_none()
                            if textbook_record:
                                textbook_record.title = textbook_title  # type: ignore
                                await db.commit()
                                logger.info(f"✓ Updated textbook title: {textbook_title}")

                        api_usage = get_api_usage_summary(api_run_id)
                        review_phase = "reviewing"
                        review_status_key = "review_curriculum"
                        await update_progress(db, textbook_id, {
                            "phase": review_phase,
                            "progress_value": 15.0,
                            "status_text": progress_text(language_val, review_status_key), #type: ignore
                            "planner_status": "completed",
                            "ingestion_status": "pending",
                            "curriculum_data": curriculum_data,
                            "chapter_titles": chapter_titles,
                            "total_chapters": len(chapter_titles),
                            "topic": topic,
                            "language": language_val,
                            "planning_mode": planning_mode_val,
                            "textbook_mode": textbook_mode_val,
                            "target_pages": target_pages_val,
                            "page_validation": page_validation,
                            "api_usage_summary": api_usage,
                        })

                        logger.info("[Workflow] Planning complete. Waiting for curriculum confirmation...")
                        logger.info("[Workflow] API usage summary: %s", api_usage)

                        return {
                            "success": True,
                            "phase": review_phase,
                            "planning_mode": planning_mode_val,
                            "curriculum": curriculum_data,
                            "api_usage_summary": api_usage,
                            "message": "Planning complete. Awaiting curriculum confirmation."
                        }

        return {
            "success": False,
            "error": "Planning phase did not complete",
            "api_usage_summary": get_api_usage_summary(api_run_id),
        }

    except WorkflowStoppedException:
        logger.info("[Workflow] Planning stopped by user request")
        return {
            "success": False,
            "error": "stopped_by_user",
            "api_usage_summary": get_api_usage_summary(api_run_id),
        }

    except Exception as e:
        logger.error(f"[Workflow] Error: {e}", exc_info=True)

        if db:
            await update_progress(db, textbook_id, {
                "phase": "idle",
                "error_message": str(e),
                "topic": topic,
            })

        return {
            "success": False,
            "error": str(e),
            "api_usage_summary": get_api_usage_summary(api_run_id),
        }


async def continue_after_curriculum_confirmation(
    textbook_id: int,
    confirmed_curriculum: Dict[str, Any],
    initial_state: AgentState,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Continue workflow after curriculum confirmation.

    Runs: ingestion → CRAG retrieval/evaluation → writer → ... → publisher
    Curriculum already confirmed and in state.

    Args:
        textbook_id: Database ID
        confirmed_curriculum: User-confirmed curriculum dict
        initial_state: Base state with topic, settings, etc.
        db: Database session

    Returns:
        dict with success status and file paths
    """

    from app.schemas.curriculum import CurriculumOutline

    try:
        curriculum = CurriculumOutline(**confirmed_curriculum)
    except Exception as e:
        logger.error(f"Failed to parse curriculum: {e}")
        return {"success": False, "error": f"Invalid curriculum: {e}"}

    # ⭐ Extract topic info from initial_state
    topic = initial_state.get("request", "")  # type: ignore[union-attr]
    core_topic = initial_state.get("core_topic", topic)  # type: ignore[union-attr]
    user_requirements = initial_state.get("user_requirements", "")  # type: ignore[union-attr]
    planning_mode = str(initial_state.get("planning_mode", "auto"))  # type: ignore[union-attr]
    textbook_mode = str(initial_state.get("textbook_mode", "standard"))  # type: ignore[union-attr]
    target_pages = confirmed_curriculum.get("target_pages") if isinstance(confirmed_curriculum, dict) else None
    rag_collection_name = f"dynamic_context_{textbook_id}_{int(time.time())}"
    # Content-generation nodes that participate in the CRAG loop.
    _CRAG_NODES = (
                        "query_formulator", "retriever_node",
                        "context_evaluator", "targeted_rag_recovery", "content_writer",
                        "reviewer", "illustrator",
                    )

    content_state = {
        **initial_state,
        "curriculum":               curriculum,
        "current_chapter_index":    0,
        "current_subsection_index": 0,
        "final_content":            "",
        "current_content":          "",
        "messages":                 [],
        "revision_number":          0,
        "chapter_header_written":   False,
        "section_summaries":        [],
        "rag_context":              "",
        "rag_collection_name":      rag_collection_name,
        "rag_source_audit":         {},
        "rag_best_effort_context":  "",
        "rag_best_effort_audit":    {},
        "rag_best_effort_score":    0.0,
        "review_feedback":          "",
        "textbook_title":           initial_state.get("textbook_title", ""),  # type: ignore[union-attr]
        "preface_content":          "",   # generated by generate_preface_node
        "final_filepath":           None,
        "final_markdown_filepath":  None,
        "final_pdf_filepath":       None,
        "partial_markdown_filepath": None,
        "final_docx_filepath":      None,
        "export_errors":            {},
        # CRAG pipeline fields — reset for clean start
        "retrieval_query":          "",
        "context_quality":          "sufficient",
        "web_supplement_context":   "",
        "rejection_type":           None,
        "used_rag_queries":         [],
        "rag_retrieval_attempts":   0,
        "rag_recovery_attempted":    False,
        "curriculum_confirmed":     True,
    }

    # Use post-confirmation workflow (ingestion → CRAG retrieval/evaluation → ... → publisher)
    from app.services.textbook.orchestrator import create_content_after_confirm_workflow
    app = create_content_after_confirm_workflow()
    api_run_id = f"textbook:{textbook_id}:content"
    reset_api_usage_summary(api_run_id)

    try:
        logger.info(
            f"[Workflow] Starting content generation for textbook {textbook_id} - "
            f"core_topic: '{core_topic}', requirements: '{user_requirements or '(none)'}'"
        )

        if db:
            await update_progress(db, textbook_id, {
                "phase": "generating",
                "progress_value": 25.0,
                "status_text": progress_text(initial_state.get("language", "vi"), "collecting_data"),
                "planner_status": "completed",
                "ingestion_status": "active",
                "publisher_status": "pending",
                "curriculum_data": confirmed_curriculum,
                "chapter_titles": [
                    ch.title for ch in curriculum.chapters
                ],
                "current_chapter": 0,
                "current_subsection": 0,
                "total_chapters": len(curriculum.chapters),
                "total_subsections": sum(len(ch.subsections) for ch in curriculum.chapters),
                "topic": topic,
                "language": initial_state.get("language", "vi"),
                "planning_mode": planning_mode,
                "textbook_mode": textbook_mode,
                "target_pages": target_pages,
            })

        cumulative_state: Dict[str, Any] = dict(content_state)
        _ingestion_failed: bool = False
        _publisher_started: bool = False

        def _source_audit_progress() -> Dict[str, Any]:
            source_audit = cumulative_state.get("rag_source_audit")
            return {"source_audit": source_audit} if source_audit else {}

        def _stream_events():
            with api_usage_context(
                run_id=api_run_id,
                textbook_id=textbook_id,
                phase="content",
            ):
                yield from app.stream(
                    content_state,
                    {"recursion_limit": settings.CONTENT_WORKFLOW_RECURSION_LIMIT},
                )

        for event in _stream_events():
            for node_name, node_output in event.items():
                if isinstance(node_output, dict):
                    cumulative_state.update(node_output)

                current_chapter = cumulative_state.get("current_chapter_index", 0)
                current_subsection = cumulative_state.get("current_subsection_index", 0)
                final_content = cumulative_state.get("final_content", "")
                if node_name == "publisher":
                    _publisher_started = True

                if node_name == "ingestion" and db:
                    ingestion_messages = cumulative_state.get("messages", [])
                    ingestion_failed = any(
                        isinstance(m, str) and m.startswith("✗ Ingestion failed")
                        for m in ingestion_messages[-5:]
                    )

                    if ingestion_failed:
                        _ingestion_failed = True
                        failed_msg = next(
                            (m for m in reversed(ingestion_messages[-5:])
                             if isinstance(m, str) and m.startswith("✗")),
                            "Ingestion failed: unknown reason"
                        )
                        await update_progress(db, textbook_id, {
                            "phase":          "idle",
                            "progress_value": 0.0,
                            "status_text":    progress_text(initial_state.get("language", "vi"), "ingestion_error", error=failed_msg),
                            "error_message":  failed_msg,
                            "topic":          topic,
                            "language":       initial_state.get("language", "vi"),
                            "planning_mode":  planning_mode,
                            "textbook_mode":  textbook_mode,
                            "target_pages": target_pages,
                        })
                        logger.error(f"[Workflow] Ingestion failed: {failed_msg}")
                    else:
                        await update_progress(db, textbook_id, {
                            "phase":          "generating",
                            "progress_value": 30.0,
                            "status_text":    progress_text(initial_state.get("language", "vi"), "generating_content"),
                            "planner_status":   "completed",
                            "ingestion_status": "completed",
                            "publisher_status": "pending",
                            "curriculum_data":  confirmed_curriculum,
                            "chapter_titles":   [ch.title for ch in curriculum.chapters],
                            "current_chapter":    0,
                            "current_subsection": 0,
                            "total_chapters":     len(curriculum.chapters),
                            "total_subsections":  sum(
                                len(ch.subsections) for ch in curriculum.chapters
                            ),
                            "topic": topic,
                            "language": initial_state.get("language", "vi"),
                            "planning_mode": planning_mode,
                            "textbook_mode": textbook_mode,
                            "target_pages": target_pages,
                        })

                elif node_name in _CRAG_NODES and db:
                    progress = 30.0 + (current_chapter / len(curriculum.chapters)) * 60.0
                    # Convert 0-based indices to 1-based for frontend display
                    display_chapter    = current_chapter + 1
                    display_subsection = current_subsection + 1

                    await update_progress(db, textbook_id, {
                        "phase": "generating",
                        "progress_value": min(progress, 90.0),
                        "status_text": progress_text(
                            initial_state.get("language", "vi"),
                            "generating_section",
                            chapter=display_chapter,
                            total_chapters=len(curriculum.chapters),
                            subsection=display_subsection,
                        ),
                        "planner_status":   "completed",
                        "ingestion_status": "completed",
                        "current_chapter":      display_chapter,
                        "current_subsection":   display_subsection,
                        "current_content_preview": cumulative_state.get("final_content", ""),
                        "topic": topic,
                        "language": initial_state.get("language", "vi"),
                        "planning_mode": planning_mode,
                        "textbook_mode": textbook_mode,
                        "target_pages": target_pages,
                        "sub_stages": {
                            "retriever":  "active" if node_name in ("query_formulator", "retriever_node", "context_evaluator") else "done",
                            "writer":     "active" if node_name == "content_writer"  else ("done" if node_name in ("reviewer", "illustrator") else "pending"),
                            "reviewer":   "active" if node_name == "reviewer"         else ("done" if node_name == "illustrator" else "pending"),
                            "illustrator":"active" if node_name == "illustrator"      else "pending",
                        },
                        **_source_audit_progress(),
                    })

                elif node_name == "publisher" and db:
                    await update_progress(db, textbook_id, {
                        "phase": "generating",
                        "progress_value": 95.0,
                        "status_text": progress_text(initial_state.get("language", "vi"), "publishing"),
                        "planner_status": "completed",
                        "ingestion_status": "completed",
                        "publisher_status": "active",
                        "topic": topic,
                        "language": initial_state.get("language", "vi"),
                        "planning_mode": planning_mode,
                        "textbook_mode": textbook_mode,
                        **_source_audit_progress(),
                    })

        api_usage = get_api_usage_summary(api_run_id)
        logger.info("[Workflow] API usage summary: %s", api_usage)

        # Guard: if ingestion failed, error state was already written inside the loop.
        # Do NOT overwrite it with a success state.
        if _ingestion_failed:
            logger.error("[Workflow] Aborting post-loop: ingestion failed, no content generated")
            _cleanup_rag_after_export(cumulative_state)
            return {
                "success": False,
                "error": "Ingestion failed: no search results found",
                "partial_markdown_path": cumulative_state.get("partial_markdown_filepath"),
                "api_usage_summary": api_usage,
            }

        if (
            not _publisher_started
            and cumulative_state.get("context_quality") == "insufficient"
        ):
            error = _context_failure_error(cumulative_state)
            emergency = _publish_recoverable_content(cumulative_state, error)
            if db:
                await update_progress(db, textbook_id, {
                    "phase": "done" if _has_emergency_artifact(emergency) else "idle",
                    "progress_value": 100.0 if _has_emergency_artifact(emergency) else 30.0,
                    "status_text": (
                        f"{error} Đã xuất bản phần nội dung đã tạo."
                        if _has_emergency_artifact(emergency)
                        else error
                    ),
                    "planner_status": "completed",
                    "ingestion_status": "completed",
                    "publisher_status": "completed" if _has_emergency_artifact(emergency) else "pending",
                    "error_message": error,
                    "partial_markdown_filepath": cumulative_state.get("partial_markdown_filepath"),
                    "pdf_path": emergency.get("pdf_path"),
                    "docx_path": emergency.get("docx_path"),
                    "markdown_path": emergency.get("markdown_path"),
                    "stopped_early": True,
                    "topic": topic,
                    "language": initial_state.get("language", "vi"),
                    "textbook_mode": textbook_mode,
                    **_source_audit_progress(),
                })
            logger.error("[Workflow] Content generation stopped: %s", error)
            _cleanup_rag_after_export(cumulative_state)
            if _has_emergency_artifact(emergency):
                return {
                    "success": True,
                    "stopped_early": True,
                    "error": error,
                    "title": cumulative_state.get("textbook_title", topic),
                    "pdf_path": emergency.get("pdf_path"),
                    "docx_path": emergency.get("docx_path"),
                    "markdown_path": emergency.get("markdown_path"),
                    "partial_markdown_path": cumulative_state.get("partial_markdown_filepath"),
                    "source_audit": cumulative_state.get("rag_source_audit") or {},
                    "api_usage_summary": api_usage,
                }
            return {
                "success": False,
                "error": error,
                "title": cumulative_state.get("textbook_title", topic),
                "partial_markdown_path": cumulative_state.get("partial_markdown_filepath"),
                "source_audit": cumulative_state.get("rag_source_audit") or {},
                "api_usage_summary": api_usage,
            }

        pdf_path = _validated_artifact_path(
            cumulative_state.get("final_pdf_filepath")
            or cumulative_state.get("final_filepath"),
            ".pdf",
        )
        docx_path = _validated_artifact_path(
            cumulative_state.get("final_docx_filepath"),
            ".docx",
        )
        title = cumulative_state.get("textbook_title", topic)
        requested_formats = set(cumulative_state.get("export_formats") or ["PDF", "Word"])
        missing_exports = []
        if "PDF" in requested_formats and not pdf_path:
            missing_exports.append("PDF")
        if "Word" in requested_formats and not docx_path:
            missing_exports.append("DOCX")

        if missing_exports:
            export_errors = cumulative_state.get("export_errors") or {}
            details = "; ".join(
                f"{name.upper()}: {message}"
                for name, message in export_errors.items()
            )
            error = f"Required export(s) missing: {', '.join(missing_exports)}"
            if details:
                error = f"{error}. {details}"
            if db:
                await update_progress(db, textbook_id, {
                    "phase": "idle",
                    "progress_value": 95.0,
                    "status_text": error,
                    "planner_status": "completed",
                    "ingestion_status": "completed",
                    "publisher_status": "error",
                    "error_message": error,
                    "partial_markdown_filepath": cumulative_state.get("partial_markdown_filepath"),
                    "topic": topic,
                    "language": initial_state.get("language", "vi"),
                    "textbook_mode": textbook_mode,
                    **_source_audit_progress(),
                })
            logger.error("[Workflow] Content export failed: %s", error)
            _cleanup_rag_after_export(cumulative_state)
            return {
                "success": False,
                "error": error,
                "title": title,
                "pdf_path": pdf_path,
                "docx_path": docx_path,
                "partial_markdown_path": cumulative_state.get("partial_markdown_filepath"),
                "api_usage_summary": api_usage,
            }

        if db:
            await update_progress(db, textbook_id, {
                "phase": "done",
                "progress_value": 100.0,
                "status_text": progress_text(initial_state.get("language", "vi"), "done"),
                "planner_status": "completed",
                "ingestion_status": "completed",
                "publisher_status": "completed",
                "topic": topic,
                "language": initial_state.get("language", "vi"),
                "textbook_mode": textbook_mode,
                **_source_audit_progress(),
            })

        logger.info(f"[Workflow] Content generation complete: {title}")

        _cleanup_rag_after_export(cumulative_state)

        return {
            "success": True,
            "title": title,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
            "api_usage_summary": api_usage,
        }

    except WorkflowStoppedException:
        logger.info("[Workflow] Content generation stopped by user request")
        cleanup_state = locals().get("cumulative_state") or locals().get("content_state") or {}
        emergency = _publish_recoverable_content(cleanup_state, "stopped_by_user")
        if db and _has_emergency_artifact(emergency):
            await update_progress(db, textbook_id, {
                "phase": "done",
                "progress_value": 100.0,
                "status_text": "Đã dừng và xuất bản phần nội dung đã tạo.",
                "planner_status": "completed",
                "ingestion_status": "completed",
                "publisher_status": "completed",
                "pdf_path": emergency.get("pdf_path"),
                "docx_path": emergency.get("docx_path"),
                "markdown_path": emergency.get("markdown_path"),
                "stopped_early": True,
                "topic": topic,
                "language": initial_state.get("language", "vi"),
                "textbook_mode": textbook_mode,
            })
        _cleanup_rag_after_export(cleanup_state)
        partial_path = None
        try:
            partial_path = locals().get("cumulative_state", {}).get("partial_markdown_filepath")
        except Exception:
            partial_path = None
        if _has_emergency_artifact(emergency):
            return {
                "success": True,
                "stopped_early": True,
                "error": "stopped_by_user",
                "title": cleanup_state.get("textbook_title", topic),
                "pdf_path": emergency.get("pdf_path"),
                "docx_path": emergency.get("docx_path"),
                "markdown_path": emergency.get("markdown_path"),
                "partial_markdown_path": partial_path,
                "api_usage_summary": get_api_usage_summary(api_run_id),
            }
        return {
            "success": False,
            "error": "stopped_by_user",
            "partial_markdown_path": partial_path,
            "api_usage_summary": get_api_usage_summary(api_run_id),
        }

    except Exception as e:
        logger.error(f"[Workflow] Content generation error: {e}", exc_info=True)
        cleanup_state = locals().get("cumulative_state") or locals().get("content_state") or {}
        emergency = _publish_recoverable_content(cleanup_state, str(e))
        _cleanup_rag_after_export(cleanup_state)

        if db:
            await update_progress(db, textbook_id, {
                "phase": "done" if _has_emergency_artifact(emergency) else "idle",
                "progress_value": 100.0 if _has_emergency_artifact(emergency) else 0.0,
                "status_text": (
                    "Pipeline gặp lỗi, nhưng đã xuất bản phần nội dung đã tạo."
                    if _has_emergency_artifact(emergency)
                    else str(e)
                ),
                "error_message": str(e),
                "publisher_status": "completed" if _has_emergency_artifact(emergency) else "error",
                "pdf_path": emergency.get("pdf_path"),
                "docx_path": emergency.get("docx_path"),
                "markdown_path": emergency.get("markdown_path"),
                "partial_export": _has_emergency_artifact(emergency),
                "topic": topic,
                "language": initial_state.get("language", "vi"),
                "textbook_mode": textbook_mode,
            })

        partial_path = None
        try:
            partial_path = locals().get("cumulative_state", {}).get("partial_markdown_filepath")
        except Exception:
            partial_path = None
        if _has_emergency_artifact(emergency):
            return {
                "success": True,
                "partial_export": True,
                "error": str(e),
                "title": cleanup_state.get("textbook_title", topic),
                "pdf_path": emergency.get("pdf_path"),
                "docx_path": emergency.get("docx_path"),
                "markdown_path": emergency.get("markdown_path"),
                "partial_markdown_path": partial_path,
                "api_usage_summary": get_api_usage_summary(api_run_id),
            }
        return {
            "success": False,
            "error": str(e),
            "partial_markdown_path": partial_path,
            "api_usage_summary": get_api_usage_summary(api_run_id),
        }
