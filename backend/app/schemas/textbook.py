from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.ingestion.source_policy import (
    default_source_preferences,
    normalize_domain,
    normalize_url,
    source_catalog,
)
from app.schemas.byok import CredentialUsage, TextbookModelSelection


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
    formula_need: Literal["none", "likely", "essential"] = "none"
    formula_policy: Literal["auto", "include", "exclude"] = "auto"
    formula_intent_present: bool = False
    formula_confirmation_required: bool = False
    formula_conflict: bool = False
    formula_reason: str = ""


class SourcePreferences(BaseModel):
    source_mode: Literal["system_default", "custom_hybrid", "custom_only"] = "system_default"
    selected_source_ids: List[str] = Field(default_factory=list, max_length=20)
    custom_urls: List[str] = Field(default_factory=list, max_length=30)
    custom_domains: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("selected_source_ids")
    @classmethod
    def validate_source_ids(cls, value: List[str]) -> List[str]:
        valid_ids = {item["id"] for item in source_catalog()}
        normalized: List[str] = []
        for raw_id in value or []:
            source_id = str(raw_id or "").strip()
            if not source_id:
                continue
            if source_id not in valid_ids:
                raise ValueError(f"Unknown source id: {source_id}")
            if source_id not in normalized:
                normalized.append(source_id)
        return normalized

    @field_validator("custom_urls")
    @classmethod
    def validate_custom_urls(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for raw_url in value or []:
            url = normalize_url(raw_url)
            if url not in normalized:
                normalized.append(url)
        return normalized

    @field_validator("custom_domains")
    @classmethod
    def validate_custom_domains(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        for raw_domain in value or []:
            domain = normalize_domain(raw_domain)
            if domain not in normalized:
                normalized.append(domain)
        return normalized


class TextbookCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2500)
    num_chapters: int = Field(default=3, ge=1, le=50)
    content_level: str = Field(default="Trung Bình")
    max_subsections_per_chapter: int = Field(default=3, ge=1, le=30)
    max_child_subsections_per_section: int = Field(default=3, ge=1, le=20)
    target_pages: int = Field(
        ...,
        ge=5,
        le=2000,
        description="Desired content pages only, from preface through chapters; excludes cover, TOC, and figure-list pages.",
    )
    page_plan_confirmed: bool = False
    enable_images: bool = False
    ui_language: str = Field(default="vi", pattern="^(vi|en)$")
    export_formats: List[str] = Field(default_factory=lambda: ["PDF", "Word"])
    planning_mode: Literal["auto", "structured"] = "auto"
    structure_depth: Literal["level1", "level2"] = "level1"
    fill_missing_child_subsections: bool = False
    textbook_mode: Literal["standard", "practice"] = "standard"
    formula_policy: Literal["auto", "include", "exclude"] = "auto"
    formula_confirmed: bool = False
    credential_usage: CredentialUsage = "saved"
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    serper_api_key: Optional[str] = Field(default=None, max_length=500)
    skip_serper_api_key: bool = False
    model_selection: TextbookModelSelection = Field(default_factory=TextbookModelSelection)
    source_preferences: SourcePreferences = Field(default_factory=SourcePreferences)
    initial_structure: Optional[Dict[str, Any]] = None
    initial_structure_markdown: Optional[str] = Field(default=None, max_length=20000)


class TextbookResponse(BaseModel):
    id: int
    title: str
    topic: str
    core_topic: Optional[str] = None
    user_requirements: Optional[str] = None
    num_chapters: int
    content_level: str
    max_subsections_per_chapter: int
    max_child_subsections_per_section: int = 3
    enable_images: bool
    language: str = "vi"
    content_type: str
    structure_depth: str = "level1"
    textbook_mode: str = "standard"
    formula_policy: str = "auto"
    formula_need: str = "none"
    source_preferences: Optional[Dict[str, Any]] = Field(default_factory=default_source_preferences)
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
    formula_policy: str = "auto"
    formula_need: str = "none"
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
    page_plan_confirmed: bool = False
    credential_usage: CredentialUsage = "saved"
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    serper_api_key: Optional[str] = Field(default=None, max_length=500)
    skip_serper_api_key: bool = False
    model_selection: TextbookModelSelection = Field(default_factory=TextbookModelSelection)


class CurriculumCreditEstimateRequest(BaseModel):
    curriculum: Dict[str, Any]


class CurriculumCreditEstimateResponse(BaseModel):
    credits_required: int
    total_chapters: int
    total_subsections: int
    enable_images: bool
    content_level: str
    is_admin_free: bool
    page_validation: Optional[Dict[str, Any]] = None


class StructureFileParseResponse(BaseModel):
    topic: str = ""
    target_pages: Optional[int] = None
    structure_depth: Literal["level1", "level2"] = "level1"
    curriculum: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)
    unparsed_items: List[str] = Field(default_factory=list)
    source_format: str
