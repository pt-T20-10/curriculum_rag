"""
Textbook management endpoints.

Phase 2.2: Pre-validation + content_type detection.
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
    TextbookResponse,
    TextbookListResponse
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
    1. Validate topic → detect content_type
    2. If invalid → return 400 (credits NOT deducted)
    3. If valid → check credits → create → trigger task
    
    Returns:
        201: Textbook created with detected content_type
        400: Invalid topic or insufficient credits
    """
    
   # ================ VALIDATE TOPIC ================
    validation = validate_topic(textbook_data.topic)

   
    if not validation:  # Validator returned None or empty
        raise HTTPException(
            status_code=500,
            detail="Topic validation service unavailable. Please try again."
        )

    
    if not validation.get("valid", False): 
        reason = validation.get("reason", "Không thể xác thực topic")
        suggestion = validation.get("suggestion", "")
        error_msg = f"{reason}. Gợi ý: {suggestion}" if suggestion else reason
        
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid topic",
                "message": error_msg,
                "suggestions": suggestion.split(" | ") if suggestion else []
            }
        )

    # Extract detected content_type
    detected_type = validation.get("content_type", "technical")
    
    # ================ CHECK CREDITS ================
    result = await db.execute(select(User).where(User.id == current_user_id))
    user = result.scalar_one_or_none()
    
    if not user or user.credits < 1: #type: ignore
        raise HTTPException(
            status_code=400,
            detail="Insufficient credits. Please top up to create textbooks."
        )
    
    # ================ CREATE TEXTBOOK ================
    textbook = Textbook(
        user_id=current_user_id,
        topic=textbook_data.topic,
        title=textbook_data.topic,  # AI will update this
        num_chapters=textbook_data.num_chapters,
        min_words_per_section=textbook_data.min_words_per_section,
        enable_images=textbook_data.enable_images,
        content_type=detected_type,  # ⭐ Save detected type
        status=TextbookStatus.PENDING,
        credits_used=1,
    )
    
    db.add(textbook)
    
    # Deduct credit
    user.credits -= 1 #type: ignore
    
    await db.commit()
    await db.refresh(textbook)
    
    # ================ TRIGGER TASK ================
    from app.tasks.textbook_tasks import generate_textbook_task
    generate_textbook_task.delay(textbook.id)
    
    return textbook


@router.get("/", response_model=TextbookListResponse)
async def list_textbooks(
    content_type: Optional[str] = None,  # Filter by type
    status: Optional[str] = None,         # Filter by status
    page: int = 1,
    size: int = 10,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """
    List user's textbooks with filtering.
    
    Query params:
        content_type: Filter by type (scholarly/technical/practical/lifestyle)
        status: Filter by status (pending/generating/completed/failed)
        page: Page number (default: 1)
        size: Items per page (default: 10, max: 50)
    """
    
    # Validate size
    size = min(size, 50)
    offset = (page - 1) * size
    
    # Build query
    query = select(Textbook).where(Textbook.user_id == current_user_id)
    
    # Apply filters
    if content_type:
        query = query.where(Textbook.content_type == content_type)
    if status:
        query = query.where(Textbook.status == status)
    
    # Order by newest first
    query = query.order_by(Textbook.created_at.desc())
    
    # Count total matching items
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Paginate
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    textbooks = result.scalars().all()
    
    # Calculate total pages
    pages = (total + size - 1) // size if total > 0 else 0 #type: ignore
    
    return {
        "items": textbooks,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
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
            Textbook.user_id == current_user_id
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
            Textbook.user_id == current_user_id
        )
    )
    textbook = result.scalar_one_or_none()
    
    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")
    
    await db.delete(textbook)
    await db.commit()
    
    return None