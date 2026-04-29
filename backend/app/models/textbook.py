from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
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
    num_chapters = Column(Integer, default=3, nullable=False)
    min_words_per_section = Column(Integer, default=500, nullable=False)
    enable_images = Column(Boolean, default=False, nullable=False)
    content_type = Column(
        String(50), 
        nullable=False, 
        default="technical",
        index=True  # For filtering/stats
    )
    status = Column(String(20), default=TextbookStatus.PENDING.value, nullable=False)
    pdf_path = Column(String(1000), nullable=True)
    docx_path = Column(String(1000), nullable=True)
    error_message = Column(Text, nullable=True)
    credits_used = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="textbooks")
