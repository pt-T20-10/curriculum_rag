from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class TextbookStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class Textbook(Base):
    __tablename__ = "textbooks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    topic = Column(Text, nullable=False)
    core_topic = Column(String(500), nullable=True)
    user_requirements = Column(Text, nullable=True)
    num_chapters = Column(Integer, default=3, nullable=False)
    content_level = Column(String(50), default="Trung Bình", nullable=False)
    max_subsections_per_chapter = Column(Integer, default=3, nullable=False)
    max_child_subsections_per_section = Column(Integer, default=3, nullable=False)
    structure_depth = Column(String(20), default="level1", nullable=False, index=True)
    language = Column(String(10), default="vi", nullable=False, index=True)
    curriculum_json = Column(JSON, nullable=True)
    total_chapters = Column(Integer, default=0)
    total_subsections = Column(Integer, default=0)
    enable_images = Column(Boolean, default=False, nullable=False)
    content_type = Column(String(50), nullable=False, default="technical", index=True)
    textbook_mode = Column(String(20), nullable=False, default="standard", index=True)
    formula_policy = Column(String(20), nullable=False, default="auto", index=True)
    formula_need = Column(String(20), nullable=False, default="none", index=True)
    source_preferences = Column(
        JSON,
        nullable=True,
        default=lambda: {
            "source_mode": "system_default",
            "selected_source_ids": [],
            "custom_urls": [],
            "custom_domains": [],
            "reference_style": "none",
            "fallback_policy": "none",
        },
    )
    source_materials = Column(JSON, nullable=True, default=list)
    status = Column(String(20), default=TextbookStatus.PENDING.value, nullable=False)
    pdf_path = Column(String(1000), nullable=True)
    docx_path = Column(String(1000), nullable=True)
    error_message = Column(Text, nullable=True)
    credits_used = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    progress_data = Column(JSON, nullable=True, default=None)
    current_chapter = Column(Integer, default=0)
    current_subsection = Column(Integer, default=0)
    task_id = Column(String(200), nullable=True)

    owner = relationship("User", back_populates="textbooks")
