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

logger = setup_logger(name="TextbookTasks", logfile="backend/logs/celery_tasks.log")


@celery_app.task(bind=True, name="generate_textbook")
def generate_textbook_task(self, textbook_id: int):
    """
    Generate textbook using AI workflow.
    
    Workflow (Option 2 - Single-shot):
    1. Fetch textbook from database
    2. Run complete LangGraph workflow:
       - Ingestion (web crawl)
       - Planner (curriculum outline)
       - Researcher (RAG retrieval)
       - Writer (content generation)
       - Reviewer (quality check)
       - Illustrator (images if enabled)
       - Publisher (export PDF/DOCX)
    3. Update database with results
    
    No preview, no confirmation - fully automated.
    
    Args:
        textbook_id: Database ID of textbook to generate
        
    Returns:
        dict with status and result info
    """
    
    async def _run_generation():
        """Async wrapper for database and workflow operations."""
        
        async with AsyncSessionLocal() as db:
            # ===============================================================
            # STEP 1: Fetch textbook from database
            # ===============================================================
            
            result = await db.execute(
                select(Textbook).where(Textbook.id == textbook_id)
            )
            textbook = result.scalar_one_or_none()
            
            if not textbook:
                logger.error(f"[TASK] Textbook {textbook_id} not found")
                return {"status": "error", "message": "Textbook not found"}
            
            # ===============================================================
            # HELPER: Status update function
            # ===============================================================
            
            async def update_status(status: str, error: str = None): #type: ignore
                """Update textbook status in database."""
                textbook.status = status #type: ignore
                if error:
                    textbook.error_message = error #type: ignore
                await db.commit()
                logger.info(f"[TASK] Textbook {textbook_id} → {status}")
            
            try:
                # ===========================================================
                # STEP 2: Update status to GENERATING
                # ===========================================================
                
                await update_status(TextbookStatus.GENERATING.value)
                logger.info(f"[TASK] Starting generation for: {textbook.topic}")
                logger.info(f"[TASK] Chapters: {textbook.num_chapters}, Images: {textbook.enable_images}")
                
                # ===========================================================
                # STEP 3: Run AI workflow
                # ===========================================================
                
                # Import here to avoid circular imports
                from app.services.textbook.workflow_runner import run_textbook_workflow
                
                # Execute workflow
                result = await run_textbook_workflow(
                    textbook_id=textbook.id, #type: ignore
                    topic=textbook.topic, #type: ignore
                    num_chapters=textbook.num_chapters, #type: ignore 
                    min_words_per_section=textbook.min_words_per_section, #type: ignore
                    enable_images=textbook.enable_images, #type: ignore
                    content_type=textbook.content_type, #type: ignore
                    content_level="Trung Bình",  
                    export_formats=["PDF", "Word"],
                )
                
                # ===========================================================
                # STEP 4: Process workflow result
                # ===========================================================
                
                if result.get("success"):
                    # Success - update database with results
                    textbook.status = TextbookStatus.COMPLETED.value #type: ignore
                    textbook.title = result.get("title", textbook.topic) #type: ignore
                    textbook.pdf_path = result.get("pdf_path") #type: ignore
                    textbook.docx_path = result.get("docx_path") #type: ignore 
                    textbook.completed_at = datetime.utcnow() #type: ignore
                    textbook.error_message = None  # Clear any previous errors #type: ignore
                    
                    await db.commit()
                    
                    logger.info(f"[TASK] ✓ Textbook {textbook_id} completed successfully")
                    logger.info(f"[TASK]   Title: {textbook.title}")
                    logger.info(f"[TASK]   PDF: {textbook.pdf_path}")
                    
                    return {
                        "status": "success",
                        "textbook_id": textbook_id,
                        "title": textbook.title,
                        "pdf_path": textbook.pdf_path,
                    }
                    
                else:
                    # Workflow failed - mark as failed with error
                    error_msg = result.get("error", "Unknown workflow error")
                    await update_status(TextbookStatus.FAILED.value, error_msg)
                    
                    logger.error(f"[TASK] ✗ Textbook {textbook_id} failed: {error_msg}")
                    
                    return {
                        "status": "error",
                        "textbook_id": textbook_id,
                        "error": error_msg,
                    }
                    
            except Exception as e:
                # Unexpected exception - mark as failed
                error_msg = str(e)
                await update_status(TextbookStatus.FAILED.value, error_msg)
                
                logger.error(f"[TASK] ✗ Textbook {textbook_id} exception: {error_msg}")
                logger.exception("Full traceback:")
                
                return {
                    "status": "error",
                    "textbook_id": textbook_id,
                    "error": error_msg,
                }
    
    # ===================================================================
    # Run async function in sync Celery context
    # ===================================================================
    
    try:
        return asyncio.run(_run_generation())
    except Exception as e:
        logger.error(f"[TASK] Asyncio error for textbook {textbook_id}: {e}")
        logger.exception("Full traceback:")
        return {
            "status": "error",
            "textbook_id": textbook_id,
            "error": f"Task execution error: {str(e)}"
        }