"""
Background tasks for textbook generation.

Integrates LangGraph AI workflow with Celery task queue.
"""

import asyncio
from datetime import datetime

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.credit_history import CreditHistory
from app.models.textbook import Textbook, TextbookStatus
from app.models.user import User
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


async def _prepare_structured_content_generation(
    db,
    textbook: Textbook,
    curriculum: dict,
) -> tuple[dict, dict]:
    from app.routers.textbook import (
        _apply_confirmed_curriculum_counts,
        _insufficient_credits_detail,
        _is_free_admin,
        _sanitize_confirmed_curriculum,
        estimate_textbook_credits,
    )

    user_result = await db.execute(
        select(User).where(User.id == textbook.user_id).with_for_update()  # type: ignore[arg-type]
    )
    user = user_result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}, {}

    is_admin_free = _is_free_admin(user)
    confirmed_curriculum, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(
        curriculum
    )
    estimated_credits = estimate_textbook_credits(
        total_subsections=total_subsections,
        content_level=textbook.content_level,  # type: ignore[arg-type]
        enable_images=bool(textbook.enable_images),
    )
    credits_required = 0 if is_admin_free else estimated_credits
    credits_charged = 0

    if not is_admin_free and not textbook.credits_used:  # type: ignore
        current_credits = int(user.credits or 0)  # type: ignore
        if current_credits < credits_required:
            detail = _insufficient_credits_detail(
                textbook.language,  # type: ignore[arg-type]
                credits_required,
                current_credits,
            )
            progress_data = dict(textbook.progress_data or {})  # type: ignore
            progress_data.update({
                "phase": "idle",
                "progress_value": 15.0,
                "status_text": detail,
                "error_message": detail,
                "planner_status": "completed",
                "planning_mode": "structured",
                "textbook_mode": textbook.textbook_mode or "standard",  # type: ignore[attr-defined]
                "curriculum_data": confirmed_curriculum,
            })
            textbook.progress_data = progress_data  # type: ignore
            textbook.status = TextbookStatus.FAILED.value  # type: ignore
            textbook.error_message = detail  # type: ignore
            await db.commit()
            return {"success": False, "error": detail}, {}

        user.credits = current_credits - credits_required  # type: ignore
        textbook.credits_used = credits_required  # type: ignore
        credits_charged = credits_required
        db.add(CreditHistory(
            user_id=textbook.user_id,  # type: ignore[arg-type]
            delta=-credits_required,
            reason=f"Textbook generation #{textbook.id}",
            balance_after=user.credits,  # type: ignore[arg-type]
        ))
    elif is_admin_free:
        textbook.credits_used = 0  # type: ignore

    chapter_count = len(chapter_titles)
    progress_data = dict(textbook.progress_data or {})  # type: ignore
    progress_data.update({
        "phase": "generating",
        "progress_value": 20.0,
        "status_text": progress_text(textbook.language, "content_generation_started"),  # type: ignore[arg-type]
        "planner_status": "completed",
        "ingestion_status": "pending",
        "publisher_status": "pending",
        "curriculum_data": confirmed_curriculum,
        "chapter_titles": chapter_titles,
        "num_chapters": chapter_count,
        "total_chapters": chapter_count,
        "total_subsections": total_subsections,
        "language": textbook.language,  # type: ignore[arg-type]
        "planning_mode": "structured",
        "textbook_mode": textbook.textbook_mode or "standard",  # type: ignore[attr-defined]
        "credits_required": credits_required,
        "credits_charged": credits_charged,
        "is_admin_free": is_admin_free,
    })
    textbook.progress_data = progress_data  # type: ignore
    _apply_confirmed_curriculum_counts(
        textbook,
        confirmed_curriculum,
        chapter_titles,
        total_subsections,
    )
    await db.commit()
    return {
        "success": True,
        "credits_required": credits_required,
        "credits_charged": credits_charged,
        "is_admin_free": is_admin_free,
    }, confirmed_curriculum


async def _run_content_generation_for_textbook(
    db,
    textbook: Textbook,
    confirmed_curriculum: dict,
    planning_mode: str = "auto",
):
    logger.info(f"[TASK] Starting content generation for: {textbook.topic}")

    from app.schemas.curriculum import build_initial_state
    from app.services.textbook.workflow_runner import continue_after_curriculum_confirmation

    advanced_config = await load_effective_config(db, textbook.user_id)  # type: ignore[arg-type]
    initial_state = build_initial_state(
        request=textbook.topic,  # type: ignore[arg-type]
        num_chapters=textbook.num_chapters,  # type: ignore[arg-type]
        enable_images=textbook.enable_images,  # type: ignore[arg-type]
        content_level=textbook.content_level,  # type: ignore[arg-type]
        max_subsections_per_chapter=textbook.max_subsections_per_chapter,  # type: ignore[arg-type]
        content_type=textbook.content_type,  # type: ignore[arg-type]
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore[attr-defined]
        core_topic=textbook.core_topic or textbook.topic,  # type: ignore[arg-type]
        user_requirements=textbook.user_requirements or "",  # type: ignore[arg-type]
        language=textbook.language,  # type: ignore[arg-type]
        advanced_config=advanced_config,
        source_preferences=textbook.source_preferences or {},  # type: ignore[arg-type]
        planning_mode=planning_mode,
        export_formats=["PDF", "Word"],
    )
    initial_state["textbook_title"] = textbook.title or textbook.topic  # type: ignore
    initial_state["curriculum_confirmed"] = True

    await update_textbook_progress(
        db,
        textbook.id,  # type: ignore[arg-type]
        current_chapter=0,
        current_subsection=0,
    )

    result = await continue_after_curriculum_confirmation(
        textbook_id=textbook.id,  # type: ignore[arg-type]
        confirmed_curriculum=confirmed_curriculum,
        initial_state=initial_state,  # type: ignore[arg-type]
        db=db,
    )

    if result.get("success"):
        textbook.status = TextbookStatus.COMPLETED.value  # type: ignore
        if result.get("title"):
            textbook.title = result.get("title")  # type: ignore
        textbook.pdf_path = result.get("pdf_path")  # type: ignore
        textbook.docx_path = result.get("docx_path")  # type: ignore
        textbook.completed_at = datetime.utcnow()  # type: ignore
        if result.get("stopped_early"):
            textbook.error_message = "Generation stopped by user; partial export saved"  # type: ignore
        elif result.get("partial_export"):
            textbook.error_message = str(result.get("error") or "Partial export saved after pipeline error")  # type: ignore
        else:
            textbook.error_message = None  # type: ignore

        await db.commit()
        logger.info("[TASK] ✓ Content generation complete")
        return {
            "status": "stopped_published" if result.get("stopped_early") else "success",
            "title": textbook.title,
            "pdf_path": textbook.pdf_path,
            "docx_path": textbook.docx_path,
            "api_usage_summary": result.get("api_usage_summary"),
            "partial_export": bool(result.get("partial_export") or result.get("stopped_early")),
        }

    error_msg = result.get("error", "Unknown error")
    if error_msg == "stopped_by_user":
        logger.info("[TASK] Task ended: stopped by user")
        return {"status": "stopped"}
    textbook.status = TextbookStatus.FAILED.value  # type: ignore
    textbook.error_message = error_msg  # type: ignore
    textbook.pdf_path = result.get("pdf_path")  # type: ignore
    textbook.docx_path = result.get("docx_path")  # type: ignore
    textbook.completed_at = None  # type: ignore
    await db.commit()

    logger.error(f"[TASK] Content generation failed: {error_msg}")
    return {"status": "error", "error": error_msg}

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
                existing_progress = dict(textbook.progress_data or {})  # type: ignore
                planning_mode = str(
                    existing_progress.get("planning_mode")
                    or ("structured" if textbook.curriculum_json else "auto")  # type: ignore
                )
                # Update status and set initial progress so frontend shows topic immediately
                textbook.status = TextbookStatus.GENERATING.value #type: ignore
                textbook.progress_data = { #type: ignore
                    **existing_progress,
                    "phase": "planning",
                    "progress_value": 5.0,
                    "status_text": progress_text(textbook.language, "planning_started"), # type: ignore
                    "planner_status": "active",
                    "ingestion_status": "pending",
                    "publisher_status": "pending",
                    "topic": textbook.topic,
                    "language": textbook.language,
                    "planning_mode": planning_mode,
                    "textbook_mode": textbook.textbook_mode or "standard",
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

                    if planning_mode == "structured":
                        if not curriculum:
                            raise ValueError("Structured planner did not return a curriculum")
                        charge_result, confirmed_curriculum = await _prepare_structured_content_generation(
                            db,
                            textbook,
                            curriculum,
                        )
                        if not charge_result.get("success"):
                            return {
                                "status": "error",
                                "phase": "idle",
                                "error": charge_result.get("error"),
                            }
                        return await _run_content_generation_for_textbook(
                            db,
                            textbook,
                            confirmed_curriculum,
                            planning_mode="structured",
                        )
                    
                    logger.info(f"[TASK] Planning complete for textbook {textbook_id}")
                    return {
                        "status": "success",
                        "phase": "reviewing",
                        "api_usage_summary": result.get("api_usage_summary"),
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
                    textbook_mode        = textbook.textbook_mode or "standard",  # type: ignore
                    core_topic           = textbook.core_topic or textbook.topic,       # type: ignore
                    user_requirements    = textbook.user_requirements or "",            # type: ignore
                    language             = textbook.language,      # type: ignore
                    advanced_config       = advanced_config,
                    source_preferences    = textbook.source_preferences or {},  # type: ignore[arg-type]
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
                    if result.get("stopped_early"):
                        textbook.error_message = "Generation stopped by user; partial export saved" #type: ignore
                    elif result.get("partial_export"):
                        textbook.error_message = str(result.get("error") or "Partial export saved after pipeline error") #type: ignore
                    else:
                        textbook.error_message = None #type: ignore

                    await db.commit()

                    logger.info(f"[TASK] ✓ Content generation complete")
                    return {
                        "status": "stopped_published" if result.get("stopped_early") else "success",
                        "title": textbook.title,
                        "pdf_path": textbook.pdf_path,
                        "docx_path": textbook.docx_path,
                        "api_usage_summary": result.get("api_usage_summary"),
                        "partial_export": bool(result.get("partial_export") or result.get("stopped_early")),
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
