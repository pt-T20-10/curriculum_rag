"""
Textbook management endpoints.
"""

from math import ceil
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_async_db
from app.ingestion.source_policy import normalize_source_preferences
from app.models.credit_history import CreditHistory
from app.models.textbook import Textbook, TextbookStatus
from app.models.user import User, UserRole
from app.schemas.textbook import (
    CurriculumCreditEstimateRequest,
    CurriculumCreditEstimateResponse,
    TextbookCreate,
    TextbookProgressResponse,
    TextbookResponse,
    TextbookListResponse,
    CurriculumConfirmRequest,
)
from app.security.jwt import get_current_user_id
from app.services.textbook.language import (
    localized_validation_fallback,
    normalize_language,
    progress_text,
)
from app.services.textbook.structure_parser import (
    StructureParseError,
    parse_structure_markdown,
)
from app.services.textbook.validator import validate_topic

router = APIRouter(prefix="/textbooks", tags=["textbooks"])


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


CONTENT_LEVEL_CREDIT_MULTIPLIERS: dict[str, float] = {
    "Ngắn": 0.6,
    "Trung Bình": 1.0,
    "Dài": 1.7,
    "Rất Dài": 2.5,
}
DEFAULT_CONTENT_LEVEL_CREDIT_MULTIPLIER = 1.0


def _is_free_admin(user: User | None) -> bool:
    if not user:
        return False
    return (
        user.role == UserRole.ADMIN.value  # type: ignore
        and not user.is_locked  # type: ignore
        and not user.is_deleted  # type: ignore
    )


def estimate_textbook_credits(
    total_subsections: int,
    content_level: str,
    enable_images: bool,
) -> int:
    safe_total = max(0, int(total_subsections or 0))
    level_multiplier = CONTENT_LEVEL_CREDIT_MULTIPLIERS.get(
        content_level,
        DEFAULT_CONTENT_LEVEL_CREDIT_MULTIPLIER,
    )
    subsection_units = safe_total * level_multiplier
    text_credits = ceil(subsection_units / 8)
    image_credits = ceil(safe_total / 6) if enable_images and safe_total else 0
    return max(1, text_credits + image_credits)


def _insufficient_credits_detail(
    language: str | None,
    required_credits: int,
    current_credits: int,
) -> str:
    base = localized_validation_fallback("insufficient_credits", language)
    if normalize_language(language) == "vi":
        return f"{base} Cần {required_credits} credits, hiện có {current_credits}."
    return f"{base} Required: {required_credits} credits, available: {current_credits}."


def _sanitize_confirmed_curriculum(curriculum: dict) -> tuple[dict, list[str], int]:
    chapters = curriculum.get("chapters") if isinstance(curriculum, dict) else None
    if not isinstance(chapters, list) or not chapters:
        raise HTTPException(status_code=400, detail="Curriculum must contain at least one chapter")

    sanitized_chapters = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise HTTPException(status_code=400, detail="Invalid chapter data")

        chapter_title = _clean_text(chapter.get("title"))
        if not chapter_title:
            raise HTTPException(status_code=400, detail="Chapter title cannot be empty")

        subsections = chapter.get("subsections")
        if not isinstance(subsections, list) or not subsections:
            raise HTTPException(status_code=400, detail="Each chapter must contain at least one subsection")

        sanitized_subsections = []
        for subsection in subsections:
            if not isinstance(subsection, dict):
                raise HTTPException(status_code=400, detail="Invalid subsection data")

            title = _clean_text(subsection.get("title"))
            if not title:
                raise HTTPException(status_code=400, detail="Subsection title cannot be empty")

            description = _clean_text(subsection.get("description")) or f"Content about {title}"
            search_query = _clean_text(subsection.get("search_query")) or title
            section_type = _clean_text(subsection.get("section_type")) or "medium"
            sanitized_subsections.append({
                "title": title,
                "description": description,
                "search_query": search_query,
                "section_type": section_type,
            })

        sanitized_chapters.append({
            "title": chapter_title,
            "subsections": sanitized_subsections,
        })

    sanitized = {
        "topic": _clean_text(curriculum.get("topic")),
        "chapters": sanitized_chapters,
    }
    chapter_titles = [chapter["title"] for chapter in sanitized_chapters]
    total_subsections = sum(len(chapter["subsections"]) for chapter in sanitized_chapters)
    return sanitized, chapter_titles, total_subsections


def _apply_confirmed_curriculum_counts(
    textbook: Textbook,
    confirmed_curriculum: dict,
    chapter_titles: list[str],
    total_subsections: int,
) -> int:
    chapter_count = len(chapter_titles)

    textbook.curriculum_json = confirmed_curriculum  # type: ignore
    textbook.num_chapters = chapter_count  # type: ignore
    textbook.total_chapters = chapter_count  # type: ignore
    textbook.total_subsections = total_subsections  # type: ignore
    textbook.current_chapter = 0  # type: ignore
    textbook.current_subsection = 0  # type: ignore

    return chapter_count


def _curriculum_chapter_count(curriculum: Any) -> Optional[int]:
    chapters = curriculum.get("chapters") if isinstance(curriculum, dict) else None
    if not isinstance(chapters, list) or not chapters:
        return None
    return len(chapters)


def _repair_textbook_chapter_count(textbook: Textbook) -> bool:
    chapter_count = _curriculum_chapter_count(textbook.curriculum_json)  # type: ignore
    if chapter_count is None:
        return False

    changed = False
    if textbook.num_chapters != chapter_count:  # type: ignore
        textbook.num_chapters = chapter_count  # type: ignore
        changed = True
    if textbook.total_chapters != chapter_count:  # type: ignore
        textbook.total_chapters = chapter_count  # type: ignore
        changed = True

    progress_data = dict(textbook.progress_data or {})  # type: ignore
    if progress_data and (
        progress_data.get("num_chapters") != chapter_count #type: ignore
        or progress_data.get("total_chapters") != chapter_count #type: ignore
    ):
        progress_data["num_chapters"] = chapter_count #type: ignore
        progress_data["total_chapters"] = chapter_count #type: ignore
        textbook.progress_data = progress_data  # type: ignore
        changed = True

    return changed


def _planning_draft_phase(textbook: Textbook) -> bool:
    progress_data = dict(textbook.progress_data or {})  # type: ignore
    phase = progress_data.get("phase") or "" #type: ignore
    credits_used = int(textbook.credits_used or 0)  # type: ignore
    return credits_used == 0 and (
        phase in {"", "planning", "reviewing"}
        or textbook.status == TextbookStatus.PENDING.value  # type: ignore
    )


def _revoke_textbook_task(textbook: Textbook, textbook_id: int) -> None:
    from app.utils import task_registry

    celery_task_id = (
        str(textbook.celery_task_id)  # type: ignore
        if textbook.celery_task_id  # type: ignore
        else task_registry.get(textbook_id)
    )
    if not celery_task_id:
        return

    from app.celery_app import celery_app
    celery_app.control.revoke(celery_task_id, terminate=True, signal="SIGKILL")
    task_registry.delete(textbook_id)
    textbook.celery_task_id = None  # type: ignore


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
    ui_language = normalize_language(textbook_data.ui_language)
    validation = validate_topic(
        textbook_data.topic,
        ui_language=ui_language,
        formula_policy=textbook_data.formula_policy,
        formula_confirmed=textbook_data.formula_confirmed,
    )

    if not validation:
        raise HTTPException(
            status_code=500,
            detail=localized_validation_fallback("validator_unavailable", ui_language)
        )

    if not validation.get("valid", False):
        raise HTTPException(
            status_code=400,
            detail={
                "validation_failed": True,
                "reason": validation.get(
                    "reason",
                    localized_validation_fallback("invalid_topic", ui_language),
                ),
                "suggestion": validation.get("suggestion", ""),
                "input_language": validation.get("input_language", ""),
                "requested_language": validation.get("requested_language", ""),
                "target_language": validation.get("target_language", ui_language),
                "language_source": validation.get("language_source", "ui"),
                "unsupported_language": validation.get("unsupported_language", ""),
                "unsupported_language_name_en": validation.get("unsupported_language_name_en", ""),
                "unsupported_language_name_vi": validation.get("unsupported_language_name_vi", ""),
                "formula_need": validation.get("formula_need", "none"),
                "formula_policy": validation.get("formula_policy", textbook_data.formula_policy),
                "formula_reason": validation.get("formula_reason", ""),
            }
        )

    if validation.get("formula_conflict", False):
        raise HTTPException(
            status_code=400,
            detail={
                "formula_conflict": True,
                "reason": validation.get("formula_reason", ""),
                "formula_need": validation.get("formula_need", "none"),
                "formula_policy": validation.get("formula_policy", textbook_data.formula_policy),
            },
        )

    if validation.get("formula_confirmation_required", False):
        raise HTTPException(
            status_code=409,
            detail={
                "formula_confirmation_required": True,
                "reason": validation.get("formula_reason", ""),
                "formula_need": validation.get("formula_need", "likely"),
                "formula_policy": validation.get("formula_policy", textbook_data.formula_policy),
            },
        )

    
    detected_type = validation.get("content_type", "technical")
    core_topic = validation.get("core_topic", textbook_data.topic)
    user_requirements = validation.get("user_requirements", "")
    formula_policy = validation.get("formula_policy", textbook_data.formula_policy)
    formula_need = validation.get("formula_need", "none")
    textbook_language = normalize_language(validation.get("target_language"), ui_language)
    planning_mode = textbook_data.planning_mode
    source_preferences = normalize_source_preferences(
        textbook_data.source_preferences.model_dump()
    )
    initial_curriculum: dict[str, Any] | None = None
    initial_total_subsections = 0

    if planning_mode == "structured":
        try:
            initial_curriculum = parse_structure_markdown(
                textbook_data.initial_structure_markdown or "",
                topic=core_topic,
            )
        except StructureParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        initial_total_subsections = sum(
            len(chapter.get("subsections") or [])
            for chapter in initial_curriculum.get("chapters", [])
        )
    
    # ================ CHECK CREDITS ================
    result = await db.execute(select(User).where(User.id == current_user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=400,
            detail=localized_validation_fallback("insufficient_credits", ui_language)
        )

    if not _is_free_admin(user) and user.credits < 1:  # type: ignore
        raise HTTPException(
            status_code=400,
            detail=localized_validation_fallback("insufficient_credits", ui_language)
        )

    # ================ CREATE TEXTBOOK ================
    textbook = Textbook(
        user_id=current_user_id,
        topic=textbook_data.topic, 
        core_topic=core_topic,  
        user_requirements=user_requirements,  
        title=core_topic,  # To be filled by planner
        num_chapters=(
            len(initial_curriculum["chapters"])
            if initial_curriculum
            else textbook_data.num_chapters
        ),
        content_level=textbook_data.content_level,
        max_subsections_per_chapter=(
            max(
                len(chapter.get("subsections") or [])
                for chapter in initial_curriculum["chapters"]
            )
            if initial_curriculum
            else textbook_data.max_subsections_per_chapter
        ),
        enable_images=textbook_data.enable_images,
        language=textbook_language,
        curriculum_json=initial_curriculum,
        total_chapters=len(initial_curriculum["chapters"]) if initial_curriculum else 0,
        total_subsections=initial_total_subsections,
        content_type=detected_type,
        textbook_mode=textbook_data.textbook_mode,
        formula_policy=formula_policy,
        formula_need=formula_need,
        source_preferences=source_preferences,
        status=TextbookStatus.PENDING,
        credits_used=0,
        progress_data={
            "planning_mode": planning_mode,
            "textbook_mode": textbook_data.textbook_mode,
            "formula_policy": formula_policy,
            "formula_need": formula_need,
            "source_preferences": source_preferences,
            "curriculum_data": initial_curriculum,
            "total_chapters": len(initial_curriculum["chapters"]) if initial_curriculum else 0,
            "total_subsections": initial_total_subsections,
        } if initial_curriculum else {
            "planning_mode": planning_mode,
            "textbook_mode": textbook_data.textbook_mode,
            "formula_policy": formula_policy,
            "formula_need": formula_need,
            "source_preferences": source_preferences,
        },
    )

    db.add(textbook)
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

    filters = [Textbook.user_id == current_user_id]

    if content_type:
        filters.append(Textbook.content_type == content_type)
    if status:
        filters.append(Textbook.status == status)

    count_query = select(func.count(Textbook.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Dashboard cards do not need large JSON/TEXT columns. Keep this query narrow
    # so MySQL can sort reliably on local and small Railway instances.
    query = (
        select(
            Textbook.id,
            Textbook.title,
            Textbook.topic,
            Textbook.core_topic,
            Textbook.user_requirements,
            Textbook.num_chapters,
            Textbook.content_level,
            Textbook.max_subsections_per_chapter,
            Textbook.enable_images,
            Textbook.language,
            Textbook.content_type,
            Textbook.textbook_mode,
            Textbook.formula_policy,
            Textbook.formula_need,
            Textbook.status,
            Textbook.pdf_path,
            Textbook.docx_path,
            Textbook.error_message,
            Textbook.credits_used,
            Textbook.created_at,
            Textbook.completed_at,
        )
        .where(*filters)
        .order_by(Textbook.id.desc())
        .offset(offset)
        .limit(size)
    )
    rows = (await db.execute(query)).mappings().all()
    textbooks = [dict(row) for row in rows]

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

    if _repair_textbook_chapter_count(textbook):
        await db.commit()

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

    if _repair_textbook_chapter_count(textbook):
        await db.commit()

    progress_data = dict(textbook.progress_data or {})  # type: ignore

    # Always surface DB fields so frontend doesn't show "..." while Celery task starts
    if textbook.topic:  # type: ignore
        progress_data.setdefault("topic", textbook.topic)  # type: ignore
    if textbook.core_topic:  # type: ignore
        progress_data.setdefault("core_topic", textbook.core_topic)  # type: ignore

    if textbook.curriculum_json and not progress_data.get("curriculum_data"):  # type: ignore
        progress_data["curriculum_data"] = textbook.curriculum_json  # type: ignore
    if progress_data.get("planning_mode") is None:
        progress_data["planning_mode"] = "auto"
    
   
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
    if textbook.content_level:  # type: ignore
        progress_data.setdefault("content_level", textbook.content_level)  # type: ignore
    if textbook.max_subsections_per_chapter:  # type: ignore
        progress_data.setdefault("max_subsections_per_chapter", textbook.max_subsections_per_chapter)  # type: ignore
    if textbook.enable_images is not None:  # type: ignore
        progress_data.setdefault("enable_images", textbook.enable_images)  # type: ignore
    if textbook.language:  # type: ignore
        progress_data.setdefault("language", textbook.language)  # type: ignore
    if textbook.textbook_mode:  # type: ignore
        progress_data.setdefault("textbook_mode", textbook.textbook_mode)  # type: ignore
    if getattr(textbook, "formula_policy", None):  # type: ignore
        progress_data.setdefault("formula_policy", textbook.formula_policy)  # type: ignore
    if getattr(textbook, "formula_need", None):  # type: ignore
        progress_data.setdefault("formula_need", textbook.formula_need)  # type: ignore
    progress_data.setdefault(
        "source_preferences",
        normalize_source_preferences(getattr(textbook, "source_preferences", None)),
    )

    return TextbookProgressResponse(
        id=textbook.id,  # type: ignore
        status=textbook.status,  # type: ignore
        progress_data=progress_data,  # type: ignore
    )


@router.post("/{textbook_id}/estimate-credits", response_model=CurriculumCreditEstimateResponse)
async def estimate_curriculum_credits(
    textbook_id: int,
    request: CurriculumCreditEstimateRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Textbook).where(
            Textbook.id == textbook_id,
            Textbook.user_id == current_user_id,
        )
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    user_result = await db.execute(select(User).where(User.id == current_user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    is_admin_free = _is_free_admin(user)

    _, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(request.curriculum)
    credits_required = estimate_textbook_credits(
        total_subsections=total_subsections,
        content_level=textbook.content_level,  # type: ignore
        enable_images=bool(textbook.enable_images),  # type: ignore
    )

    return CurriculumCreditEstimateResponse(
        credits_required=0 if is_admin_free else credits_required,
        total_chapters=len(chapter_titles),
        total_subsections=total_subsections,
        enable_images=bool(textbook.enable_images),  # type: ignore
        content_level=textbook.content_level,  # type: ignore
        is_admin_free=is_admin_free,
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
        ).with_for_update()
    )
    textbook = result.scalar_one_or_none()

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    user_result = await db.execute(
        select(User).where(User.id == current_user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_admin_free = _is_free_admin(user)

    progress_phase = dict(textbook.progress_data or {}).get("phase")  # type: ignore
    if progress_phase in {"generating", "done"}:
        return {
            "message": "Content generation already started",
            "textbook_id": textbook_id,
            "credits_required": 0 if is_admin_free else int(textbook.credits_used or 0),  # type: ignore
            "credits_charged": 0,
            "balance_after": user.credits,  # type: ignore
            "is_admin_free": is_admin_free,
        }

    confirmed_curriculum, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(request.curriculum)
    estimated_credits = estimate_textbook_credits(
        total_subsections=total_subsections,
        content_level=textbook.content_level,  # type: ignore
        enable_images=bool(textbook.enable_images),  # type: ignore
    )
    credits_required = 0 if is_admin_free else estimated_credits
    credits_charged = 0

    if not is_admin_free and not textbook.credits_used:  # type: ignore
        current_credits = int(user.credits or 0)  # type: ignore
        if current_credits < credits_required:
            raise HTTPException(
                status_code=400,
                detail=_insufficient_credits_detail(
                    textbook.language,  # type: ignore
                    credits_required,
                    current_credits,
                ),
            )

        user.credits = current_credits - credits_required  # type: ignore
        textbook.credits_used = credits_required  # type: ignore
        credits_charged = credits_required
        db.add(CreditHistory(
            user_id=current_user_id,
            delta=-credits_required,
            reason=f"Textbook generation #{textbook_id}",
            balance_after=user.credits,  # type: ignore
        ))
    elif is_admin_free:
        textbook.credits_used = 0  # type: ignore

    progress_data = dict(textbook.progress_data or {}) #type: ignore
    chapter_count = len(chapter_titles)
    progress_data.update({ #type: ignore
        "phase": "generating",
        "progress_value": 0.20,
        "status_text": progress_text(textbook.language, "content_generation_started"), # type: ignore
        "curriculum_data": confirmed_curriculum,
        "chapter_titles": chapter_titles,
        "num_chapters": chapter_count,
        "total_chapters": chapter_count,
        "total_subsections": total_subsections,
        "language": textbook.language, # type: ignore
        "textbook_mode": textbook.textbook_mode or "standard", # type: ignore
        "formula_policy": textbook.formula_policy or "auto", # type: ignore
        "formula_need": textbook.formula_need or "none", # type: ignore
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

    # Trigger content generation task
    from app.tasks.textbook_tasks import continue_textbook_generation_task
    from app.utils import task_registry
    task_result = continue_textbook_generation_task.delay(textbook_id, confirmed_curriculum)
    task_registry.store(textbook_id, task_result.id)
    textbook.celery_task_id = task_result.id  # type: ignore
    await db.commit()

    return {
        "message": "Content generation started",
        "textbook_id": textbook_id,
        "credits_required": credits_required,
        "credits_charged": credits_charged,
        "balance_after": user.credits,  # type: ignore
        "is_admin_free": is_admin_free,
    }


@router.post("/{textbook_id}/stop")
async def stop_generation(
    textbook_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Stop textbook generation gracefully and preserve generated content."""
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
    from app.utils import stop_signal
    stop_signal.request_stop_for(textbook_id)

    if _planning_draft_phase(textbook):
        # Planning has not spent credits or produced useful content, so it is
        # still safe to revoke and delete immediately.
        _revoke_textbook_task(textbook, textbook_id)
        await db.delete(textbook)
        await db.commit()
        return {"message": "Planning draft deleted", "deleted": True}

    # Do not terminate the running Celery task here. The worker checks the stop
    # flag before each graph node, then runs Publisher on any accumulated
    # content so the user can download a partial textbook.
    progress_data = dict(textbook.progress_data or {})  # type: ignore
    progress_data.update({  # type: ignore
        "phase": "stopping",
        "progress_value": max(float(progress_data.get("progress_value") or 0.0), 90.0),
        "status_text": "Đang dừng và xuất bản phần nội dung đã tạo...",
        "publisher_status": "active",
        "language": textbook.language,  # type: ignore
    })
    textbook.progress_data = progress_data  # type: ignore

    await db.commit()
    return {"message": "Stopping generation and publishing partial content", "deleted": False}
