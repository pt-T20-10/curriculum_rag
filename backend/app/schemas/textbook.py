from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TextbookCreate(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    num_chapters: int = Field(default=3, ge=1, le=10)
    min_words_per_section: int = Field(default=500, ge=100, le=5000)
    enable_images: bool = False
    


class TextbookResponse(BaseModel):
    id: int
    title: str
    topic: str
    num_chapters: int
    min_words_per_section: int  
    enable_images: bool 
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