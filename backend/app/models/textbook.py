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
    topic = Column(String(500), nullable=False)
    core_topic = Column(String(500), nullable=True)
    user_requirements = Column(String(1000), nullable=True)
    num_chapters = Column(Integer, default=3, nullable=False)
    content_level = Column(String(50), default="Trung Bình", nullable=False)
    max_subsections_per_chapter = Column(Integer, default=3, nullable=False)
    curriculum_json = Column(JSON, nullable=True)
    total_chapters = Column(Integer, default=0)
    total_subsections = Column(Integer, default=0)
    enable_images = Column(Boolean, default=False, nullable=False)
    content_type = Column(String(50), nullable=False, default="technical", index=True)
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
    celery_task_id = Column(String(200), nullable=True)

    owner = relationship("User", back_populates="textbooks")
