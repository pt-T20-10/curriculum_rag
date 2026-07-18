from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


CredentialProvider = Literal["openai", "serper"]
CredentialUsage = Literal["saved", "one_time", "system"]
TextbookGenerationMode = Literal["user_provided_api_keys", "system_credit_billing"]


class CredentialState(BaseModel):
    configured: bool = False
    last4: str = ""
    updated_at: Optional[datetime] = None


class ByokStatusResponse(BaseModel):
    generation_mode: TextbookGenerationMode
    generation_mode_label: str
    openai: CredentialState
    serper: CredentialState


class ByokCredentialUpdate(BaseModel):
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    serper_api_key: Optional[str] = Field(default=None, max_length=500)


class ByokCredentialUpdateResponse(ByokStatusResponse):
    message: str


class ByokValidateRequest(BaseModel):
    credential_usage: CredentialUsage = "one_time"
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    serper_api_key: Optional[str] = Field(default=None, max_length=500)


class ByokValidateResponse(BaseModel):
    openai_valid: bool
    serper_valid: Optional[bool] = None
    openai_error: str = ""
    serper_error: str = ""
    message: str = ""


class TextbookModelSelection(BaseModel):
    main_model: Optional[str] = None
    support_model: Optional[str] = None
    embedding_model: Optional[str] = None
    image_model: Optional[str] = None
    image_validation_model: Optional[str] = None

    def to_runtime_overrides(self) -> Dict[str, str]:
        mapping = {
            "main_model": "LLM_MODEL_PREMIUM",
            "support_model": "LLM_MODEL_CHEAP",
            "embedding_model": "OPENAI_EMBEDDING_MODEL",
            "image_model": "IMAGE_MODEL_DEFAULT",
            "image_validation_model": "IMAGE_VALIDATION_MODEL",
        }
        return {
            config_key: value
            for field_name, config_key in mapping.items()
            if (value := getattr(self, field_name)) is not None and str(value).strip()
        }
