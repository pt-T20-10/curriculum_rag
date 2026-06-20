from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class SiteInfoUpdate(BaseModel):
    service_name_vi: str = Field(..., min_length=1, max_length=200)
    service_name_en: str = Field(..., min_length=1, max_length=200)
    operator_name: str = Field(default="", max_length=255)
    address_vi: str = Field(default="", max_length=2000)
    address_en: str = Field(default="", max_length=2000)
    support_email: EmailStr | None = None
    privacy_email: EmailStr | None = None
    phone: str = Field(default="", max_length=50)
    support_hours_vi: str = Field(default="", max_length=255)
    support_hours_en: str = Field(default="", max_length=255)
    response_time_vi: str = Field(default="", max_length=2000)
    response_time_en: str = Field(default="", max_length=2000)
    effective_date: date | None = None

    @field_validator(
        "service_name_vi",
        "service_name_en",
        "operator_name",
        "address_vi",
        "address_en",
        "phone",
        "support_hours_vi",
        "support_hours_en",
        "response_time_vi",
        "response_time_en",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("support_email", "privacy_email", mode="before")
    @classmethod
    def empty_email_to_none(cls, value: object):
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip()


class SiteInfoAdminResponse(SiteInfoUpdate):
    configured: bool
    updated_at: datetime | None = None
    updated_by: int | None = None


class SiteInfoPublicResponse(BaseModel):
    service_name: str
    operator_name: str
    address: str
    support_email: str
    privacy_email: str
    phone: str
    support_hours: str
    response_time: str
    effective_date: date | None = None
