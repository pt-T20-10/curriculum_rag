from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class SupportRequestCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=10, max_length=5000)
    ui_language: Literal["vi", "en"] = "vi"
    website: str = Field(default="", max_length=200)

    @field_validator("name", "subject")
    @classmethod
    def normalize_single_line_fields(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise ValueError("Field must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Description must not be blank")
        return normalized


class SupportRequestResponse(BaseModel):
    message: str
