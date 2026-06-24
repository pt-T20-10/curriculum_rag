"""
Background tasks for textbook generation.

Integrates LangGraph AI workflow with Celery task queue.
"""

import asyncio
from datetime import datetime

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.textbook import Textbook, TextbookStatus
from app.services.config_service import load_effective_config
from app.services.textbook.language import progress_text
from app.utils.log_config import setup_logger
from sqlalchemy import select

logger = setup_logger(name="TextbookTasks", logfile="logs/celery_tasks.log")


async def update_textbook_progress(db, textbook_id: int, **kwargs):
    result = await db.execute(select(Textbook).where(Textbook.id == textbook_id))
    textbook = result.scalar_one_or_none()
    if not textbook:
        return None
    for key, value in kwargs.items():
        if hasattr(textbook, key):
            setattr(textbook, key, value)
    if "current_chapter" in kwargs or "current_subsection" in kwargs:
        ch = getattr(textbook, "current_chapter", 0) or 0
        sub = getattr(textbook, "current_subsection", 0) or 0
        total_ch = getattr(textbook, "total_chapters", 0) or 0
        if textbook.progress_data:
            progress_data = dict(textbook.progress_data)
            progress_data["status_text"] = progress_text(
                getattr(textbook, "language", "vi"),
                "chapter_progress",
                chapter=ch,
                total_chapters=total_ch,
                subsection=sub,
            )
            progress_data["current_chapter"] = ch
            progress_data["current_subsection"] = sub
            progress_data["language"] = getattr(textbook, "language", "vi")
            textbook.progress_data = progress_data
    await db.commit()
    return textbook

@celery_app.task(bind=True, name="generate_textbook")
def generate_textbook_task(self, textbook_id: int):
    from app.utils import stop_signal
    stop_signal.clear_for(textbook_id)
    stop_signal.set_current(textbook_id)  # bind to this worker thread
    """
    Generate textbook using AI workflow.
    
    New workflow (simplified):
    1. Planning phase (ingestion + planner)
    2. STOP - wait for user curriculum confirmation
    3. Content generation (triggered separately after confirmation)
    
    This task only runs Phase 1 (planning).
    Phase 2 is triggered by confirm_curriculum API endpoint.
    
    Args:
        textbook_id: Database ID of textbook to generate
        
    Returns:
        dict with status and result info
    """
    
    async def _run_planning():
        """Run planning phase only."""
        
        async with AsyncSessionLocal() as db:
            # Get textbook
            result = await db.execute(
                select(Textbook).where(Textbook.id == textbook_id)
            )
            textbook = result.scalar_one_or_none()
            
            if not textbook:
                logger.error(f"[TASK] Textbook {textbook_id} not found")
                return {"status": "error", "message": "Textbook not found"}

            # Guard: if broker re-queued this task after SIGKILL, DB already says 'failed'
            if textbook.status == TextbookStatus.FAILED.value:  # type: ignore
                logger.info(f"[TASK] Textbook {textbook_id} already failed/stopped — aborting re-queue")
                return {"status": "stopped"}

            try:
                # Update status and set initial progress so frontend shows topic immediately
                textbook.status = TextbookStatus.GENERATING.value #type: ignore
                textbook.progress_data = { #type: ignore
                    "phase": "planning",
                    "progress_value": 5.0,
                    "status_text": progress_text(textbook.language, "planning_started"), # type: ignore
                    "planner_status": "active",
                    "ingestion_status": "pending",
                    "publisher_status": "pending",
                    "topic": textbook.topic,
                    "language": textbook.language,
                }
                await db.commit()

                logger.info(f"[TASK] Starting planning for: {textbook.topic}")
                
                # Import workflow runner
                from app.services.textbook.workflow_runner import run_textbook_workflow
                advanced_config = await load_effective_config(db, textbook.user_id)  # type: ignore[arg-type]
                
                # Run planning phase (stops at curriculum review)
                result = await run_textbook_workflow(
                    textbook_id=textbook.id, #type: ignore
                    topic=textbook.topic, #type: ignore
                    num_chapters=textbook.num_chapters, #type: ignore
                    content_level=textbook.content_level, #type: ignore
                    max_subsections_per_chapter=textbook.max_subsections_per_chapter, #type: ignore
                    enable_images=textbook.enable_images, #type: ignore
                    export_formats=["PDF", "Word"],
                    language=textbook.language, # type: ignore
                    advanced_config=advanced_config,
                    db=db,
                )
                
                if result.get("success"):
                    # ⭐ Save curriculum to dedicated field
                    curriculum = result.get("curriculum")
                    if curriculum:
                        await update_textbook_progress(
                            db, textbook_id,
                            curriculum_json=curriculum,
                            total_chapters=len(curriculum.get("chapters", [])),
                            total_subsections=sum(
                                len(ch.get("subsections", [])) 
                                for ch in curriculum.get("chapters", [])
                            )
                        )
                    
                    logger.info(f"[TASK] Planning complete for textbook {textbook_id}")
                    return {
                        "status": "success",
                        "phase": "reviewing",
                        "message": "Planning complete. Awaiting curriculum confirmation."
                    }
                else:
                    error_msg = result.get("error", "Unknown error")
                    if error_msg == "stopped_by_user":
                        logger.info(f"[TASK] Planning ended: stopped by user")
                        return {"status": "stopped"}
                    textbook.status = TextbookStatus.FAILED.value #type: ignore
                    textbook.error_message = error_msg
                    await db.commit()

                    logger.error(f"[TASK] Planning failed: {error_msg}")
                    return {"status": "error", "error": error_msg}
                    
            except Exception as e:
                textbook.status = TextbookStatus.FAILED.value #type: ignore
                textbook.error_message = str(e) #type: ignore
                await db.commit()
                
                logger.error(f"[TASK] Exception: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    try:
        return asyncio.run(_run_planning())
    except Exception as e:
        logger.error(f"[TASK] Asyncio error: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


    
@celery_app.task(bind=True, name="continue_textbook_generation")
def continue_textbook_generation_task(self, textbook_id: int, confirmed_curriculum: dict):
    from app.utils import stop_signal
    stop_signal.clear_for(textbook_id)
    stop_signal.set_current(textbook_id)  # bind to this worker thread
    """
    Continue textbook generation after curriculum confirmation.
    
    Runs content generation (all chapters) + publishing.
    Triggered by /confirm-curriculum API endpoint.
    
    Args:
        textbook_id: Database ID
        confirmed_curriculum: User-confirmed curriculum dict
        
    Returns:
        dict with status and file paths
    """
    
    async def _run_content_generation():
        """Run content generation phase."""
        
        async with AsyncSessionLocal() as db:
            # Get textbook
            result = await db.execute(
                select(Textbook).where(Textbook.id == textbook_id)
            )
            textbook = result.scalar_one_or_none()
            
            if not textbook:
                logger.error(f"[TASK] Textbook {textbook_id} not found")
                return {"status": "error", "message": "Textbook not found"}

            # Guard: if broker re-queued this task after SIGKILL, DB already says 'failed'
            if textbook.status == TextbookStatus.FAILED.value:  # type: ignore
                logger.info(f"[TASK] Textbook {textbook_id} already failed/stopped — aborting re-queue")
                return {"status": "stopped"}

            try:
                logger.info(f"[TASK] Starting content generation for: {textbook.topic}")
                
                # Import workflow runner
                from app.services.textbook.workflow_runner import continue_after_curriculum_confirmation
                
                from app.schemas.curriculum import build_initial_state
                advanced_config = await load_effective_config(db, textbook.user_id)  # type: ignore[arg-type]
                initial_state = build_initial_state(
                    request              = textbook.topic,         # type: ignore
                    num_chapters         = textbook.num_chapters,  # type: ignore
                    enable_images        = textbook.enable_images, # type: ignore
                    content_level        = textbook.content_level, # type: ignore
                    max_subsections_per_chapter = textbook.max_subsections_per_chapter, # type: ignore
                    content_type         = textbook.content_type,  # type: ignore
                    core_topic           = textbook.core_topic or textbook.topic,       # type: ignore
                    user_requirements    = textbook.user_requirements or "",            # type: ignore
                    language             = textbook.language,      # type: ignore
                    advanced_config       = advanced_config,
                    export_formats       = ["PDF", "Word"],
                )
                # Preserve planner-generated title from Phase 1
                initial_state["textbook_title"] = textbook.title or textbook.topic     # type: ignore
                # Mark curriculum as confirmed — user explicitly approved via UI
                initial_state["curriculum_confirmed"] = True
                
             
                await update_textbook_progress(
                    db, textbook_id,
                    current_chapter=0,
                    current_subsection=0
                )
                
                # Run content generation
                result = await continue_after_curriculum_confirmation(
                    textbook_id=textbook.id, #type: ignore
                    confirmed_curriculum=confirmed_curriculum,
                    initial_state=initial_state, #type: ignore
                    db=db,
                )
                
                if result.get("success"):
                    # Update database — only overwrite title if result has a non-empty one
                    textbook.status = TextbookStatus.COMPLETED.value #type: ignore
                    if result.get("title"):
                        textbook.title = result.get("title") #type: ignore
                    textbook.pdf_path = result.get("pdf_path") #type: ignore
                    textbook.docx_path = result.get("docx_path") #type: ignore
                    textbook.completed_at = datetime.utcnow() #type: ignore
                    textbook.error_message = None #type: ignore

                    await db.commit()

                    logger.info(f"[TASK] ✓ Content generation complete")
                    return {
                        "status": "success",
                        "title": textbook.title,
                        "pdf_path": textbook.pdf_path,
                    }
                else:
                    error_msg = result.get("error", "Unknown error")
                    if error_msg == "stopped_by_user":
                        # Stop endpoint already set status='failed' — don't overwrite
                        logger.info(f"[TASK] Task ended: stopped by user")
                        return {"status": "stopped"}
                    textbook.status = TextbookStatus.FAILED.value #type: ignore
                    textbook.error_message = error_msg
                    # Preserve any valid partial artifact (for example DOCX)
                    # without ever mislabelling it as PDF.
                    textbook.pdf_path = result.get("pdf_path") #type: ignore
                    textbook.docx_path = result.get("docx_path") #type: ignore
                    textbook.completed_at = None #type: ignore
                    await db.commit()

                    logger.error(f"[TASK] Content generation failed: {error_msg}")
                    return {"status": "error", "error": error_msg}
                    
            except Exception as e:
                textbook.status = TextbookStatus.FAILED.value #type: ignore
                textbook.error_message = str(e) #type: ignore
                await db.commit()
                
                logger.error(f"[TASK] Exception: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    try:
        return asyncio.run(_run_content_generation())
    except Exception as e:
        logger.error(f"[TASK] Asyncio error: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
