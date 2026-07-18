"""
Textbook management endpoints.
"""

from math import ceil
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
    StructureFileParseResponse,
)
from app.security.jwt import get_current_user_id
from app.services.textbook.language import (
    localized_validation_fallback,
    normalize_language,
    progress_text,
)
from app.schemas.curriculum import (
    count_curriculum_leaf_sections,
    flatten_chapter_leaf_sections,
)
from app.services.textbook.structure_parser import (
    StructureParseError,
    parse_structure_document,
    parse_structure_markdown,
)
from app.services.textbook.page_budget import (
    allocate_page_budget,
    page_budget_enabled,
    validate_page_configuration,
)
from app.services.textbook.validator import validate_topic

router = APIRouter(prefix="/textbooks", tags=["textbooks"])


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _copy_page_and_meta_fields(source: dict, target: dict) -> None:
    for page_key in (
        "target_pages",
        "estimated_pages",
        "target_words",
        "target_chars_min",
        "target_chars_max",
        "writer_call_count",
    ):
        page_value = _clean_positive_float(source.get(page_key))
        if page_value is None:
            continue
        target[page_key] = int(round(page_value))
    for meta_key in (
        "layout_profile",
        "page_budget_mode",
        "formula_density",
        "expansion_strategy",
    ):
        meta_value = _clean_text(source.get(meta_key))
        if meta_value:
            target[meta_key] = meta_value
    bias_value = _clean_positive_float(source.get("page_fill_bias"))
    if bias_value is not None:
        target["page_fill_bias"] = round(bias_value, 3)


def _sanitize_section(section: dict, *, child: bool = False) -> dict:
    title = _clean_text(section.get("title"))
    if not title:
        raise HTTPException(
            status_code=400,
            detail=("Child subsection title cannot be empty" if child else "Subsection title cannot be empty"),
        )

    sanitized = {
        "title": title,
        "description": _clean_text(section.get("description")) or f"Content about {title}",
        "search_query": _clean_text(section.get("search_query")) or title,
        "section_type": _clean_text(section.get("section_type")) or "medium",
    }
    _copy_page_and_meta_fields(section, sanitized)

    children = section.get("children")
    if isinstance(children, list) and children:
        sanitized_children = []
        for child_section in children:
            if not isinstance(child_section, dict):
                raise HTTPException(status_code=400, detail="Invalid child subsection data")
            sanitized_children.append(_sanitize_section(child_section, child=True))
        sanitized["children"] = sanitized_children
    return sanitized


def _structure_has_children(curriculum: dict) -> bool:
    return any(
        isinstance(subsection, dict)
        and isinstance(subsection.get("children"), list)
        and len(subsection.get("children") or []) > 0
        for chapter in curriculum.get("chapters") or []
        if isinstance(chapter, dict)
        for subsection in chapter.get("subsections") or []
    )


def _missing_child_sections(curriculum: dict) -> list[str]:
    missing: list[str] = []
    for chapter_idx, chapter in enumerate(curriculum.get("chapters") or []):
        if not isinstance(chapter, dict):
            continue
        for sub_idx, subsection in enumerate(chapter.get("subsections") or []):
            if not isinstance(subsection, dict):
                continue
            children = subsection.get("children")
            if not isinstance(children, list) or not children:
                missing.append(f"{chapter_idx + 1}.{sub_idx + 1}")
    return missing


def _effective_structure_depth(curriculum: dict, requested_depth: str | None = None) -> str:
    if _structure_has_children(curriculum):
        return "level2"
    cleaned = _clean_text(requested_depth)
    if cleaned in {"level1", "level2"}:
        return cleaned
    return "level1"


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
            sanitized_subsections.append(_sanitize_section(subsection))

        sanitized_chapter = {
            "title": chapter_title,
            "subsections": sanitized_subsections,
        }
        for page_key in ("target_pages", "estimated_pages"):
            page_value = _clean_positive_float(chapter.get(page_key))
            if page_value is not None:
                sanitized_chapter[page_key] = int(round(page_value))
        sanitized_chapters.append(sanitized_chapter)

    sanitized = {
        "topic": _clean_text(curriculum.get("topic")),
        "chapters": sanitized_chapters,
    }
    structure_depth = _effective_structure_depth(curriculum, _clean_text(curriculum.get("structure_depth")))
    sanitized["structure_depth"] = structure_depth
    if structure_depth == "level2":
        missing_children = _missing_child_sections(sanitized)
        if missing_children:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Level-2 structure requires every section to contain at least "
                    f"one child subsection. Missing: {', '.join(missing_children)}"
                ),
            )
    for page_key in (
        "target_pages",
        "estimated_pages",
        "front_matter_pages",
        "body_target_pages",
        "content_intro_pages",
        "excluded_export_pages",
    ):
        page_value = _clean_positive_float(curriculum.get(page_key))
        if page_value is not None:
            sanitized[page_key] = int(round(page_value))
    for meta_key in ("layout_profile", "formula_density", "expansion_strategy"):
        meta_value = _clean_text(curriculum.get(meta_key))
        if meta_value:
            sanitized[meta_key] = meta_value
    for numeric_meta_key in ("layout_word_scale", "page_fill_bias"):
        meta_number = _clean_positive_float(curriculum.get(numeric_meta_key))
        if meta_number is not None:
            sanitized[numeric_meta_key] = round(meta_number, 3)
    chapter_titles = [chapter["title"] for chapter in sanitized_chapters]
    total_subsections = count_curriculum_leaf_sections(sanitized)
    return sanitized, chapter_titles, total_subsections


def _apply_page_budget_if_needed(
    curriculum: dict,
    *,
    target_pages: int | float | None,
    enable_images: bool,
    language: str,
    textbook_mode: str,
    formula_policy: str = "auto",
) -> tuple[dict, dict | None]:
    if target_pages is None and not page_budget_enabled(curriculum):
        return curriculum, None
    return allocate_page_budget(
        curriculum,
        target_pages=target_pages,
        enable_images=enable_images,
        language=language,
        textbook_mode=textbook_mode,
        formula_policy=formula_policy,
    )


def _page_validation_exception(
    page_validation: dict | None,
    *,
    confirmed: bool,
) -> None:
    if not page_validation:
        return
    severity = page_validation.get("severity")
    if severity == "error":
        raise HTTPException(
            status_code=400,
            detail={
                "page_validation": page_validation,
                "message": page_validation.get("ai_note") or "Invalid page plan",
            },
        )
    if severity == "warning" and not confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "page_validation_required": True,
                "page_validation": page_validation,
                "message": page_validation.get("ai_note") or "Please confirm the page estimate warning",
            },
        )


def _merge_page_validations(*validations: dict | None) -> dict | None:
    merged: dict | None = None
    rank = {"ok": 0, "warning": 1, "error": 2}
    for validation in validations:
        if not validation:
            continue
        if merged is None:
            merged = {
                **validation,
                "warnings": list(validation.get("warnings") or []),
                "errors": list(validation.get("errors") or []),
            }
            continue
        if rank.get(validation.get("severity"), 0) > rank.get(merged.get("severity"), 0):
            merged["severity"] = validation.get("severity")
            merged["ai_note"] = validation.get("ai_note") or merged.get("ai_note", "")
        for key in ("warnings", "errors"):
            for item in validation.get(key) or []:
                if item not in merged[key]:
                    merged[key].append(item)
        for key in (
            "estimated_total_pages",
            "target_pages",
            "front_matter_pages",
            "content_intro_pages",
            "excluded_export_pages",
            "layout_profile",
            "layout_word_scale",
            "page_fill_bias",
            "formula_density",
            "expansion_strategy",
        ):
            if validation.get(key) is not None:
                merged[key] = validation.get(key)
    return merged


_SECTION_META_KEYS = (
    "description",
    "search_query",
    "section_type",
    "target_words",
    "target_chars_min",
    "target_chars_max",
    "writer_call_count",
    "layout_profile",
    "page_budget_mode",
    "formula_density",
    "expansion_strategy",
    "page_fill_bias",
)


def _leaf_records(curriculum: dict) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for chapter_index, chapter in enumerate(curriculum.get("chapters") or []):
        if not isinstance(chapter, dict):
            continue
        chapter_title = _clean_text(chapter.get("title"))
        for item in flatten_chapter_leaf_sections(chapter):
            leaf = item["subsection"]
            parent = item.get("parent")
            parent_title = _clean_text(parent.get("title") if isinstance(parent, dict) else "")
            title = _clean_text(leaf.get("title") if isinstance(leaf, dict) else "")
            records.append({
                "path": (
                    chapter_index,
                    chapter_title,
                    item.get("parent_index"),
                    parent_title,
                    item.get("child_index"),
                    title,
                ),
                "leaf": leaf,
            })
    return records


def _needs_metadata_refresh(edited: dict, original: dict | None) -> bool:
    edited_records = _leaf_records(edited)
    original_records = _leaf_records(original or {})
    if len(edited_records) != len(original_records):
        return True
    original_paths = [record["path"] for record in original_records]
    for idx, record in enumerate(edited_records):
        leaf = record["leaf"]
        if idx >= len(original_paths) or record["path"] != original_paths[idx]:
            return True
        if not _clean_text(leaf.get("description")) or not _clean_text(leaf.get("search_query")):
            return True
    return False


def _preserve_unchanged_metadata(
    refreshed: dict,
    edited: dict,
    original: dict | None,
) -> dict:
    edited_records = _leaf_records(edited)
    refreshed_records = _leaf_records(refreshed)
    original_paths = [record["path"] for record in _leaf_records(original or {})]
    for idx, refreshed_record in enumerate(refreshed_records):
        if idx >= len(edited_records) or idx >= len(original_paths):
            continue
        if edited_records[idx]["path"] != original_paths[idx]:
            continue
        edited_leaf = edited_records[idx]["leaf"]
        refreshed_leaf = refreshed_record["leaf"]
        for key in _SECTION_META_KEYS:
            if key in edited_leaf:
                refreshed_leaf[key] = edited_leaf[key]
    return refreshed


def _refresh_curriculum_metadata_if_needed(
    *,
    curriculum: dict,
    original_curriculum: dict | None,
    core_topic: str,
    user_requirements: str,
    language: str,
    textbook_mode: str,
    structure_depth: str,
) -> dict:
    if not _needs_metadata_refresh(curriculum, original_curriculum):
        return curriculum
    try:
        from app.services.textbook.planner import HybridPlanner

        planner = HybridPlanner()
        enriched = planner.enrich_user_structure(
            core_topic,
            user_requirements,
            curriculum,
            language=language,
            textbook_mode=textbook_mode,
            structure_depth=structure_depth,
        )
        if not enriched:
            return curriculum
        refreshed = enriched.model_dump() if hasattr(enriched, "model_dump") else enriched.dict()
        refreshed["topic"] = curriculum.get("topic") or core_topic
        refreshed["structure_depth"] = structure_depth
        if curriculum.get("target_pages") is not None:
            refreshed["target_pages"] = curriculum.get("target_pages")
        return _preserve_unchanged_metadata(refreshed, curriculum, original_curriculum)
    except Exception:
        return curriculum


def _curriculum_page_configuration_validation(
    curriculum: dict,
    *,
    target_pages: int | float | None,
    enable_images: bool,
    language: str,
    textbook_mode: str,
) -> dict:
    chapters = curriculum.get("chapters") if isinstance(curriculum, dict) else []
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    subsection_counts = [
        count_curriculum_leaf_sections({"chapters": [chapter]})
        for chapter in chapters
        if isinstance(chapter, dict)
    ]
    total_subsections = sum(subsection_counts)
    max_subsections = max(subsection_counts) if subsection_counts else 1
    return validate_page_configuration(
        target_pages=target_pages,
        num_chapters=chapter_count,
        max_subsections_per_chapter=max_subsections,
        subsection_count=total_subsections,
        enable_images=enable_images,
        language=language,
        textbook_mode=textbook_mode,
    )


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


@router.post("/parse-structure-file", response_model=StructureFileParseResponse)
async def parse_structure_file(
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user_id),
):
    """Parse an uploaded Word/PDF outline into the manual structure editor shape."""
    del current_user_id
    filename = file.filename or ""
    if not filename.lower().endswith((".docx", ".pdf")):
        raise HTTPException(
            status_code=400,
            detail="Chỉ hỗ trợ file .docx hoặc .pdf. Vui lòng gửi file đề cương có bảng TT / Nội dung / Số trang.",
        )

    content = await file.read()
    try:
        return parse_structure_document(filename, content)
    except StructureParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    structure_depth = textbook_data.structure_depth
    source_preferences = normalize_source_preferences(
        textbook_data.source_preferences.model_dump()
    )
    initial_curriculum: dict[str, Any] | None = None
    initial_total_subsections = 0
    preflight_page_validation: dict | None = None
    page_validation: dict | None = None

    if planning_mode == "structured":
        if textbook_data.initial_structure:
            initial_curriculum = dict(textbook_data.initial_structure)
            initial_curriculum.setdefault("topic", core_topic)
        else:
            try:
                initial_curriculum = parse_structure_markdown(
                    textbook_data.initial_structure_markdown or "",
                    topic=core_topic,
                )
            except StructureParseError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        structure_depth = "level2" if _structure_has_children(initial_curriculum) else "level1"
        if structure_depth == "level2":
            missing_children = _missing_child_sections(initial_curriculum)
            if missing_children:
                if not textbook_data.fill_missing_child_subsections:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Level-2 structured outline has sections without child "
                            f"subsections: {', '.join(missing_children)}"
                        ),
                    )
                from app.services.textbook.planner import HybridPlanner

                planner = HybridPlanner()
                initial_curriculum = planner.fill_missing_child_subsections(
                    initial_structure=initial_curriculum,
                    core_topic=core_topic,
                    user_requirements=user_requirements,
                    max_child_subsections=textbook_data.max_child_subsections_per_section,
                    language=textbook_language,
                    textbook_mode=textbook_data.textbook_mode,
                )
        initial_curriculum["structure_depth"] = structure_depth

        initial_total_subsections = count_curriculum_leaf_sections(initial_curriculum)
        preflight_page_validation = _curriculum_page_configuration_validation(
            initial_curriculum,
            target_pages=textbook_data.target_pages,
            enable_images=textbook_data.enable_images,
            language=textbook_language,
            textbook_mode=textbook_data.textbook_mode,
        )
        _page_validation_exception(
            preflight_page_validation,
            confirmed=textbook_data.page_plan_confirmed,
        )
    else:
        preflight_page_validation = validate_page_configuration(
            target_pages=textbook_data.target_pages,
            num_chapters=textbook_data.num_chapters,
            max_subsections_per_chapter=(
                textbook_data.max_subsections_per_chapter
                * (
                    textbook_data.max_child_subsections_per_section
                    if structure_depth == "level2"
                    else 1
                )
            ),
            enable_images=textbook_data.enable_images,
            language=textbook_language,
            textbook_mode=textbook_data.textbook_mode,
        )
        _page_validation_exception(
            preflight_page_validation,
            confirmed=textbook_data.page_plan_confirmed,
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
        max_child_subsections_per_section=textbook_data.max_child_subsections_per_section,
        structure_depth=structure_depth,
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
            "structure_depth": structure_depth,
            "max_child_subsections_per_section": textbook_data.max_child_subsections_per_section,
            "textbook_mode": textbook_data.textbook_mode,
            "formula_policy": formula_policy,
            "formula_need": formula_need,
            "source_preferences": source_preferences,
            "target_pages": textbook_data.target_pages,
            "page_plan_confirmed": textbook_data.page_plan_confirmed,
            "curriculum_data": initial_curriculum,
            "total_chapters": len(initial_curriculum["chapters"]) if initial_curriculum else 0,
            "total_subsections": initial_total_subsections,
            "page_validation": page_validation if initial_curriculum else None,
        } if initial_curriculum else {
            "planning_mode": planning_mode,
            "structure_depth": structure_depth,
            "max_child_subsections_per_section": textbook_data.max_child_subsections_per_section,
            "textbook_mode": textbook_data.textbook_mode,
            "formula_policy": formula_policy,
            "formula_need": formula_need,
            "source_preferences": source_preferences,
            "target_pages": textbook_data.target_pages,
            "page_plan_confirmed": textbook_data.page_plan_confirmed,
            "page_validation": preflight_page_validation,
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
            Textbook.max_child_subsections_per_section,
            Textbook.enable_images,
            Textbook.language,
            Textbook.content_type,
            Textbook.structure_depth,
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
    if getattr(textbook, "max_child_subsections_per_section", None):  # type: ignore
        progress_data.setdefault("max_child_subsections_per_section", textbook.max_child_subsections_per_section)  # type: ignore
    if getattr(textbook, "structure_depth", None):  # type: ignore
        progress_data.setdefault("structure_depth", textbook.structure_depth)  # type: ignore
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

    sanitized_curriculum, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(request.curriculum)
    progress_data = dict(textbook.progress_data or {})  # type: ignore
    target_pages = (
        _clean_positive_float(sanitized_curriculum.get("target_pages"))
        or _clean_positive_float(progress_data.get("target_pages"))
    )
    _, page_validation = _apply_page_budget_if_needed(
        sanitized_curriculum,
        target_pages=target_pages,
        enable_images=bool(textbook.enable_images),  # type: ignore
        language=textbook.language,  # type: ignore
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore
        formula_policy=textbook.formula_policy or "auto",  # type: ignore
    )
    compatibility_validation = _curriculum_page_configuration_validation(
        sanitized_curriculum,
        target_pages=target_pages,
        enable_images=bool(textbook.enable_images),  # type: ignore
        language=textbook.language,  # type: ignore
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore
    )
    page_validation = _merge_page_validations(compatibility_validation, page_validation)
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
        page_validation=page_validation,
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
            "page_validation": dict(textbook.progress_data or {}).get("page_validation"),  # type: ignore
        }

    existing_progress = dict(textbook.progress_data or {})  # type: ignore
    structure_depth = (
        _clean_text(request.curriculum.get("structure_depth") if isinstance(request.curriculum, dict) else "")
        or _clean_text(existing_progress.get("structure_depth"))
        or _clean_text(getattr(textbook, "structure_depth", "level1"))
        or "level1"
    )
    refreshed_request_curriculum = _refresh_curriculum_metadata_if_needed(
        curriculum=request.curriculum,
        original_curriculum=textbook.curriculum_json,  # type: ignore[arg-type]
        core_topic=textbook.core_topic or textbook.topic,  # type: ignore[arg-type]
        user_requirements=textbook.user_requirements or "",  # type: ignore[arg-type]
        language=textbook.language,  # type: ignore[arg-type]
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore[attr-defined]
        structure_depth=structure_depth,
    )
    confirmed_curriculum, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(refreshed_request_curriculum)
    target_pages = (
        _clean_positive_float(confirmed_curriculum.get("target_pages"))
        or _clean_positive_float(existing_progress.get("target_pages"))
    )
    confirmed_curriculum, page_validation = _apply_page_budget_if_needed(
        confirmed_curriculum,
        target_pages=target_pages,
        enable_images=bool(textbook.enable_images),  # type: ignore
        language=textbook.language,  # type: ignore
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore
        formula_policy=textbook.formula_policy or "auto",  # type: ignore
    )
    compatibility_validation = _curriculum_page_configuration_validation(
        confirmed_curriculum,
        target_pages=target_pages,
        enable_images=bool(textbook.enable_images),  # type: ignore
        language=textbook.language,  # type: ignore
        textbook_mode=textbook.textbook_mode or "standard",  # type: ignore
    )
    page_validation = _merge_page_validations(compatibility_validation, page_validation)
    _page_validation_exception(
        page_validation,
        confirmed=request.page_plan_confirmed,
    )
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
        "structure_depth": structure_depth,
        "max_child_subsections_per_section": getattr(textbook, "max_child_subsections_per_section", 3), # type: ignore[attr-defined]
        "formula_policy": textbook.formula_policy or "auto", # type: ignore
        "formula_need": textbook.formula_need or "none", # type: ignore
        "credits_required": credits_required,
        "credits_charged": credits_charged,
        "is_admin_free": is_admin_free,
        "target_pages": target_pages,
        "page_plan_confirmed": request.page_plan_confirmed,
        "page_validation": page_validation,
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
        "page_validation": page_validation,
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
