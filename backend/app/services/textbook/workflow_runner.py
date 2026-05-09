"""
Workflow runner with real-time progress updates.

Integrates LangGraph workflow with database progress tracking.
"""

import asyncio
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.textbook import Textbook
from app.schemas.curriculum import AgentState
from app.utils.log_config import setup_logger

logger = setup_logger(name="WorkflowRunner", logfile="logs/workflow_runner.log")


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
    else:
        core_topic_val = topic
        user_req_val = ""
    # Build initial state
    initial_state: AgentState = { #type: ignore
        "request": topic,  
        "core_topic": core_topic_val, 
        "user_requirements": user_req_val, 
        "num_chapters": num_chapters,
        "enable_images": enable_images,
        "content_level": content_level,
        "min_chars_per_section": 0,
        "max_subsections_per_chapter": max_subsections_per_chapter,
        "curriculum": None,
        "textbook_title": "",
        "preface_content": "",
        "rag_context": "",
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "revision_number": 0,
        "review_feedback": "",
        "chapter_header_written": False,
        "messages": [],
        "final_content": "",
        "current_content": "",
        "export_formats": export_formats,
        "final_docx_filepath": None,
        "final_filepath": None,
        "chapter1_content": "",
        "content_type": "technical",
        "section_summaries": [],
    }

    # Use planning-only workflow (planner → END)
    from app.services.textbook.orchestrator import create_planning_only_workflow
    app = create_planning_only_workflow()

    try:
        logger.info(f"[Workflow] Starting planning phase for: {topic}")

        if db:
            await update_progress(db, textbook_id, {
                "phase": "planning",
                "progress_value": 10.0,
                "status_text": "Bước 1/3: Đang lập dàn ý...",
                "planner_status": "active",
                "ingestion_status": "pending",
                "publisher_status": "pending",
                "topic": topic,
            })

        cumulative_state: Dict[str, Any] = dict(initial_state)

        for event in app.stream(initial_state, {"recursion_limit": 150}):
            for node_name, node_output in event.items():
                if isinstance(node_output, dict):
                    cumulative_state.update(node_output)

                if node_name == "planner" and db:
                    curriculum = cumulative_state.get("curriculum")
                    textbook_title = cumulative_state.get("textbook_title", "")  # ⭐ Get generated title

                    curriculum_data = None
                    chapter_titles = []

                    if curriculum:
                        if hasattr(curriculum, 'model_dump'):
                            curriculum_data = curriculum.model_dump()
                        elif hasattr(curriculum, 'dict'):
                            curriculum_data = curriculum.dict()
                        else:
                            curriculum_data = dict(curriculum)

                        chapters = curriculum.chapters if hasattr(curriculum, 'chapters') else curriculum.get('chapters', [])
                        chapter_titles = [
                            ch.title if hasattr(ch, 'title') else ch.get('title', f'Chương {i+1}')
                            for i, ch in enumerate(chapters)
                        ]

                    # ⭐ Update textbook title in database
                    if textbook_title:
                        result = await db.execute(select(Textbook).where(Textbook.id == textbook_id))
                        textbook_record = result.scalar_one_or_none()
                        if textbook_record:
                            textbook_record.title = textbook_title  # type: ignore
                            await db.commit()
                            logger.info(f"✓ Updated textbook title: {textbook_title}")

                    await update_progress(db, textbook_id, {
                        "phase": "reviewing",
                        "progress_value": 15.0,
                        "status_text": "Bước 1/3: Vui lòng xem xét và xác nhận cấu trúc",
                        "planner_status": "completed",
                        "ingestion_status": "pending",
                        "curriculum_data": curriculum_data,
                        "chapter_titles": chapter_titles,
                        "total_chapters": len(chapter_titles),
                        "topic": topic,
                    })

                    logger.info(f"[Workflow] Planning complete. Waiting for curriculum confirmation...")

                    return {
                        "success": True,
                        "phase": "reviewing",
                        "curriculum": curriculum_data,
                        "message": "Planning complete. Awaiting curriculum confirmation."
                    }

        return {"success": False, "error": "Planning phase did not complete"}

    except Exception as e:
        logger.error(f"[Workflow] Error: {e}", exc_info=True)

        if db:
            await update_progress(db, textbook_id, {
                "phase": "idle",
                "error_message": str(e),
                "topic": topic,
            })

        return {"success": False, "error": str(e)}


async def continue_after_curriculum_confirmation(
    textbook_id: int,
    confirmed_curriculum: Dict[str, Any],
    initial_state: AgentState,
    db: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Continue workflow after curriculum confirmation.

    Runs: ingestion → researcher → writer → ... → publisher
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

    content_state = {
        **initial_state,
        "curriculum": curriculum,
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "final_content": "",
        "current_content": "",
        "messages": [],
        "revision_number": 0,
        "chapter_header_written": False,
        "section_summaries": [],
        "rag_context": "",
        "review_feedback": "",
        "textbook_title": initial_state.get("textbook_title", ""),  # type: ignore[union-attr]
        "preface_content": "",
        "final_filepath": None,
        "final_docx_filepath": None,
        "chapter1_content": "",
    }

    # Use post-confirmation workflow (ingestion → researcher → ... → publisher)
    from app.services.textbook.orchestrator import create_content_after_confirm_workflow
    app = create_content_after_confirm_workflow()

    try:
        logger.info(
            f"[Workflow] Starting content generation for textbook {textbook_id} - "
            f"core_topic: '{core_topic}', requirements: '{user_requirements or '(none)'}'"
        )

        if db:
            await update_progress(db, textbook_id, {
                "phase": "generating",
                "progress_value": 25.0,
                "status_text": "Bước 2/3: Đang thu thập dữ liệu...",
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
            })

        cumulative_state: Dict[str, Any] = dict(content_state)

        for event in app.stream(content_state, {"recursion_limit": 200}):
            for node_name, node_output in event.items():
                if isinstance(node_output, dict):
                    cumulative_state.update(node_output)

                current_chapter = cumulative_state.get("current_chapter_index", 0)
                current_subsection = cumulative_state.get("current_subsection_index", 0)
                final_content = cumulative_state.get("final_content", "")

                if node_name == "ingestion" and db:
                    await update_progress(db, textbook_id, {
                        "phase": "generating",
                        "progress_value": 30.0,
                        "status_text": "Bước 3/3: Đang tạo nội dung...",
                        "planner_status": "completed",
                        "ingestion_status": "completed",
                        "publisher_status": "pending",
                        "curriculum_data": confirmed_curriculum,
                        "chapter_titles": [ch.title for ch in curriculum.chapters],
                        "current_chapter": 0,
                        "current_subsection": 0,
                        "total_chapters": len(curriculum.chapters),
                        "total_subsections": sum(len(ch.subsections) for ch in curriculum.chapters),
                        "topic": topic,
                    })

                elif node_name in ("researcher", "writer", "reviewer", "illustrator") and db:
                    progress = 30.0 + (current_chapter / len(curriculum.chapters)) * 60.0

                    await update_progress(db, textbook_id, {
                        "phase": "generating",
                        "progress_value": min(progress, 90.0),
                        "status_text": f"Bước 3/3: Chương {current_chapter + 1}/{len(curriculum.chapters)} - Mục {current_subsection + 1}",
                        "planner_status": "completed",
                        "ingestion_status": "completed",
                        "current_chapter": current_chapter,
                        "current_subsection": current_subsection,
                        "current_content_preview": final_content,
                        "topic": topic,
                        "sub_stages": {
                            "researcher": "done" if node_name != "researcher" else "active",
                            "writer": "done" if node_name in ("reviewer", "illustrator") else ("active" if node_name == "writer" else "pending"),
                            "reviewer": "done" if node_name == "illustrator" else ("active" if node_name == "reviewer" else "pending"),
                            "illustrator": "active" if node_name == "illustrator" else "pending",
                        }
                    })

                elif node_name == "publisher" and db:
                    await update_progress(db, textbook_id, {
                        "phase": "generating",
                        "progress_value": 95.0,
                        "status_text": "Bước 3/3: Đang xuất bản...",
                        "planner_status": "completed",
                        "ingestion_status": "completed",
                        "publisher_status": "active",
                        "topic": topic,
                    })

        pdf_path = cumulative_state.get("final_filepath")
        docx_path = cumulative_state.get("final_docx_filepath")
        title = cumulative_state.get("textbook_title", topic)

        if db:
            await update_progress(db, textbook_id, {
                "phase": "done",
                "progress_value": 100.0,
                "status_text": "Hoàn tất!",
                "planner_status": "completed",
                "ingestion_status": "completed",
                "publisher_status": "completed",
                "topic": topic,
            })

        logger.info(f"[Workflow] Content generation complete: {title}")

        return {
            "success": True,
            "title": title,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
        }

    except Exception as e:
        logger.error(f"[Workflow] Content generation error: {e}", exc_info=True)

        if db:
            await update_progress(db, textbook_id, {
                "phase": "idle",
                "error_message": str(e),
                "topic": topic,
            })

        return {"success": False, "error": str(e)}
