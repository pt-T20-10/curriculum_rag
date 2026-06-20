from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


DeletionReason = Literal[
    "",
    "no_longer_use",
    "privacy_concerns",
    "switching_service",
    "poor_experience",
    "other",
]


class AccountDeletionRequestCreate(BaseModel):
    email: EmailStr
    reason: DeletionReason = ""
    notes: str = Field(default="", max_length=2000)
    ui_language: Literal["vi", "en"] = "vi"
    website: str = Field(default="", max_length=200)

    @field_validator("notes")
    @classmethod
    def trim_notes(cls, value: str) -> str:
        return value.strip()


class AccountDeletionRequestResponse(BaseModel):
    message: str
