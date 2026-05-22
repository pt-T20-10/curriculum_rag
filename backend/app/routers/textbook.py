"""
Textbook management endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_async_db
from app.models.textbook import Textbook, TextbookStatus
from app.models.user import User
from app.schemas.textbook import (
    TextbookCreate,
    TextbookProgressResponse,
    TextbookResponse,
    TextbookListResponse,
    CurriculumConfirmRequest,
)
from app.security.jwt import get_current_user_id
from app.services.textbook.validator import validate_topic

router = APIRouter(prefix="/textbooks", tags=["textbooks"])


@router.post("/", response_model=TextbookResponse, status_code=201)
async def create_textbook(
    textbook_data: TextbookCreate,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Create new textbook with topic validation.

    Flow:
    1. Validate topic → detect content_type + extract core_topic + user_requirements
    2. If invalid → return 400 (credits NOT deducted)
    3. If valid → check credits → create → trigger planning task
    """

    # ================ VALIDATE TOPIC ================
    validation = validate_topic(textbook_data.topic)

    if not validation:
        raise HTTPException(
            status_code=500,
            detail="Topic validation service unavailable. Please try again."
        )

    if not validation.get("valid", False):
        raise HTTPException(
            status_code=400,
            detail={
                "validation_failed": True,
                "reason": validation.get("reason", "Chủ đề không hợp lệ"),
                "suggestion": validation.get("suggestion", ""),
            }
        )

    
    detected_type = validation.get("content_type", "technical")
    core_topic = validation.get("core_topic", textbook_data.topic)
    user_requirements = validation.get("user_requirements", "")
    
    # ================ CHECK CREDITS ================
    result = await db.execute(select(User).where(User.id == current_user_id))
    user = result.scalar_one_or_none()

    if not user or user.credits < 1:  # type: ignore
        raise HTTPException(
            status_code=400,
            detail="Insufficient credits. Please top up to create textbooks."
        )

    # ================ CREATE TEXTBOOK ================
    textbook = Textbook(
        user_id=current_user_id,
        topic=textbook_data.topic, 
        core_topic=core_topic,  
        user_requirements=user_requirements,  
        title=core_topic,  # To be filled by planner
        num_chapters=textbook_data.num_chapters,
        content_level=textbook_data.content_level,
        max_subsections_per_chapter=textbook_data.max_subsections_per_chapter,
        enable_images=textbook_data.enable_images,
        content_type=detected_type,
        status=TextbookStatus.PENDING,
        credits_used=1,
    )

    db.add(textbook)
    user.credits -= 1  # type: ignore
    await db.commit()
    await db.refresh(textbook)

    # ================ TRIGGER PLANNING TASK ================
    from app.tasks.textbook_tasks import generate_textbook_task
    from app.utils import task_registry
    task_result = generate_textbook_task.delay(textbook.id)
    task_registry.store(textbook.id, task_result.id)  # type: ignore
    textbook.celery_task_id = task_result.id  # type: ignore
    await db.commit()

    return textbook


@router.get("/", response_model=TextbookListResponse)
async def list_textbooks(
    content_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 10,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """List user's textbooks with filtering and pagination."""
    size = min(size, 50)
    offset = (page - 1) * size

    query = select(Textbook).where(Textbook.user_id == current_user_id)

    if content_type:
        query = query.where(Textbook.content_type == content_type)
    if status:
        query = query.where(Textbook.status == status)

    query = query.order_by(Textbook.created_at.desc())

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    textbooks = result.scalars().all()

    pages = (total + size - 1) // size if total > 0 else 0  # type: ignore

    return {
        "items": textbooks,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
    }


@router.get("/{textbook_id}", response_model=TextbookResponse)
async def get_textbook(
    textbook_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Get single textbook by ID."""
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    return textbook


@router.delete("/{textbook_id}", status_code=204)
async def delete_textbook(
    textbook_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Delete textbook."""
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    await db.delete(textbook)
    await db.commit()
    return None


@router.get("/{textbook_id}/progress", response_model=TextbookProgressResponse)
async def get_textbook_progress(
    textbook_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get real-time progress for textbook generation.

    Polled by frontend every 2 seconds. Returns progress_data only —
    does NOT trigger any Celery tasks.
    """
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")


    progress_data = dict(textbook.progress_data or {})  # type: ignore

    # Always surface DB fields so frontend doesn't show "..." while Celery task starts
    if textbook.topic:  # type: ignore
        progress_data.setdefault("topic", textbook.topic)  # type: ignore
    if textbook.core_topic:  # type: ignore
        progress_data.setdefault("core_topic", textbook.core_topic)  # type: ignore

    if textbook.curriculum_json and not progress_data.get("curriculum_data"):  # type: ignore
        progress_data["curriculum_data"] = textbook.curriculum_json  # type: ignore
    
   
        progress_data.setdefault("current_chapter", textbook.current_chapter)  # type: ignore
    if textbook.current_subsection is not None:  # type: ignore
        progress_data.setdefault("current_subsection", textbook.current_subsection)  # type: ignore
    if textbook.total_chapters is not None:  # type: ignore
        progress_data.setdefault("total_chapters", textbook.total_chapters)  # type: ignore
    if textbook.total_subsections is not None:  # type: ignore
        progress_data.setdefault("total_subsections", textbook.total_subsections)  # type: ignore
    
    # ⭐ ADD: Include pdf_path, docx_path, title for completed textbooks
    if textbook.pdf_path:  # type: ignore
        progress_data["pdf_path"] = textbook.pdf_path  # type: ignore
    if textbook.docx_path:  # type: ignore
        progress_data["docx_path"] = textbook.docx_path  # type: ignore
    if textbook.title:  # type: ignore
        progress_data["title"] = textbook.title  # type: ignore
    if textbook.num_chapters:  # type: ignore
        progress_data.setdefault("num_chapters", textbook.num_chapters)  # type: ignore
    
    return TextbookProgressResponse(
        id=textbook.id,  # type: ignore
        status=textbook.status,  # type: ignore
        progress_data=progress_data,  # type: ignore
    )


@router.post("/{textbook_id}/confirm-curriculum")
async def confirm_curriculum(
    textbook_id: int,
    request: CurriculumConfirmRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Confirm edited curriculum and start content generation.

    Receives user-confirmed curriculum, updates progress_data,
    then triggers the content generation Celery task.
    """
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    chapters = request.curriculum.get("chapters", [])
    chapter_titles = [
        ch.get("title", f"Chương {i + 1}")
        for i, ch in enumerate(chapters)
    ]
    total_subsections = sum(len(ch.get("subsections", [])) for ch in chapters)


    progress_data = dict(textbook.progress_data or {}) #type: ignore
    progress_data.update({ #type: ignore
        "phase": "generating",
        "progress_value": 0.20,
        "status_text": "Bước 3/4: Đang tạo nội dung giáo trình...",
        "curriculum_data": request.curriculum,
        "chapter_titles": chapter_titles,
        "total_chapters": len(chapter_titles),
        "total_subsections": total_subsections,
    })

    textbook.progress_data = progress_data  # type: ignore
    
  
    textbook.curriculum_json = request.curriculum  # type: ignore
    textbook.total_chapters = len(chapter_titles)  # type: ignore
    textbook.total_subsections = total_subsections  # type: ignore
    textbook.current_chapter = 0  # type: ignore
    textbook.current_subsection = 0  # type: ignore
   
    
    await db.commit()

    # Trigger content generation task
    from app.tasks.textbook_tasks import continue_textbook_generation_task
    from app.utils import task_registry
    task_result = continue_textbook_generation_task.delay(textbook_id, request.curriculum)
    task_registry.store(textbook_id, task_result.id)
    textbook.celery_task_id = task_result.id  # type: ignore
    await db.commit()

    return {"message": "Content generation started", "textbook_id": textbook_id}


@router.post("/{textbook_id}/stop")
async def stop_generation(
    textbook_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Stop textbook generation — signals the Celery task and revokes it."""
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    # 1. Set Redis stop flag — worker checks this before each LangGraph node
    from app.utils import stop_signal, task_registry
    stop_signal.request_stop_for(textbook_id)

    # 2. Revoke the Celery task — prefer DB-stored ID, fall back to registry
    celery_task_id = str(textbook.celery_task_id) if textbook.celery_task_id else task_registry.get(textbook_id)  # type: ignore
    if celery_task_id:
        from app.celery_app import celery_app
        celery_app.control.revoke(celery_task_id, terminate=True, signal="SIGKILL")
        task_registry.delete(textbook_id)
        textbook.celery_task_id = None  # type: ignore

    # 3. Update DB status
    textbook.status = "failed"  # type: ignore
    textbook.error_message = "Generation stopped by user"  # type: ignore
    textbook.progress_data = {  # type: ignore
        "phase": "idle",
        "progress_value": 0.0,
        "status_text": "Đã dừng theo yêu cầu",
    }

    await db.commit()
    return {"message": "Generation stopped"}