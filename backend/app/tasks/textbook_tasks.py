"""
Background tasks for textbook generation.

Integrates LangGraph AI workflow with Celery task queue.
"""

import asyncio
from datetime import datetime

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.textbook import Textbook, TextbookStatus
from app.utils.log_config import setup_logger
from sqlalchemy import select

logger = setup_logger(name="TextbookTasks", logfile="logs/celery_tasks.log")


@celery_app.task(bind=True, name="generate_textbook")
def generate_textbook_task(self, textbook_id: int):
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
            
            try:
                # Update status and set initial progress so frontend shows topic immediately
                textbook.status = TextbookStatus.GENERATING.value #type: ignore
                textbook.progress_data = { #type: ignore
                    "phase": "planning",
                    "progress_value": 0.05,
                    "status_text": "**Bước 1/3:** Đang lập dàn ý...",
                    "planner_status": "active",
                    "ingestion_status": "pending",
                    "publisher_status": "pending",
                    "topic": textbook.topic,
                }
                await db.commit()

                logger.info(f"[TASK] Starting planning for: {textbook.topic}")
                
                # Import workflow runner
                from app.services.textbook.workflow_runner import run_textbook_workflow
                
                # Run planning phase (stops at curriculum review)
                result = await run_textbook_workflow(
                    textbook_id=textbook.id, #type: ignore
                    topic=textbook.topic, #type: ignore
                    num_chapters=textbook.num_chapters, #type: ignore
                    content_level=textbook.content_level, #type: ignore
                    max_subsections_per_chapter=textbook.max_subsections_per_chapter, #type: ignore
                    enable_images=textbook.enable_images, #type: ignore
                    export_formats=["PDF", "Word"],
                    db=db,
                )
                
                if result.get("success"):
                    logger.info(f"[TASK] Planning complete for textbook {textbook_id}")
                    return {
                        "status": "success",
                        "phase": "reviewing",
                        "message": "Planning complete. Awaiting curriculum confirmation."
                    }
                else:
                    error_msg = result.get("error", "Unknown error")
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
            
            try:
                logger.info(f"[TASK] Starting content generation for: {textbook.topic}")
                
                # Import workflow runner
                from app.services.textbook.workflow_runner import continue_after_curriculum_confirmation
                
                # Build initial state — include title so content workflow inherits it
                initial_state = {
                    "request": textbook.topic,
                    "textbook_title": textbook.title or textbook.topic,  # preserve planner-set title
                    "core_topic": textbook.core_topic or textbook.topic,
                    "user_requirements": textbook.user_requirements or "",
                    "num_chapters": textbook.num_chapters,
                    "enable_images": textbook.enable_images,
                    "content_level": textbook.content_level, #type: ignore
                    "min_chars_per_section": 0,
                    "max_subsections_per_chapter": textbook.max_subsections_per_chapter, #type: ignore
                    "export_formats": ["PDF", "Word"],
                    "content_type": textbook.content_type, #type: ignore
                }
                
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
                    textbook.status = TextbookStatus.FAILED.value #type: ignore
                    textbook.error_message = error_msg
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