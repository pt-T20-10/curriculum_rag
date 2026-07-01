from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Result from topic validation."""
    valid: bool
    reason: str = ""
    suggestion: str = ""
    content_type: str = "technical"
    core_topic: str = ""
    user_requirements: str = ""
    input_language: str = ""
    requested_language: str = ""
    target_language: str = "vi"
    language_source: str = "ui"
    unsupported_language: str = ""
    unsupported_language_name_en: str = ""
    unsupported_language_name_vi: str = ""


class TextbookCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    num_chapters: int = Field(default=3, ge=1, le=50)
    content_level: str = Field(default="Trung Bình")
    max_subsections_per_chapter: int = Field(default=3, ge=1, le=30)
    enable_images: bool = False
    ui_language: str = Field(default="vi", pattern="^(vi|en)$")
    export_formats: List[str] = Field(default_factory=lambda: ["PDF", "Word"])


class TextbookResponse(BaseModel):
    id: int
    title: str
    topic: str
    core_topic: Optional[str] = None
    user_requirements: Optional[str] = None
    num_chapters: int
    content_level: str
    max_subsections_per_chapter: int
    enable_images: bool
    language: str = "vi"
    content_type: str
    status: str
    pdf_path: Optional[str] = None
    docx_path: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TextbookListResponse(BaseModel):
    items: List[TextbookResponse]
    total: int
    page: int
    size: int
    pages: int


class ProgressData(BaseModel):
    """Real-time progress tracking data."""
    phase: str = "idle"
    progress_value: float = 0.0
    status_text: str = ""

    ingestion_status: str = "pending"
    planner_status: str = "pending"
    publisher_status: str = "pending"

    current_chapter: int = 0
    current_subsection: int = 0
    total_chapters: int = 0
    total_subsections: int = 0
    language: str = "vi"
    subsections_in_chapter: int = 0

    sub_stages: Dict[str, str] = {
        "researcher": "pending",
        "writer": "pending",
        "reviewer": "pending",
        "illustrator": "pending"
    }

    curriculum_data: Optional[Dict[str, Any]] = None
    current_content_preview: Optional[str] = None
    chapter_titles: Optional[List[str]] = None
    error_message: Optional[str] = None


class TextbookProgressResponse(BaseModel):
    id: int
    status: str
    progress_data: Optional[Dict[str, Any]] = None


class CurriculumConfirmRequest(BaseModel):
    curriculum: Dict[str, Any]


class CurriculumCreditEstimateRequest(BaseModel):
    curriculum: Dict[str, Any]


class CurriculumCreditEstimateResponse(BaseModel):
    credits_required: int
    total_chapters: int
    total_subsections: int
    enable_images: bool
    content_level: str
    is_admin_free: bool
