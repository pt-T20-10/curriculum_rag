from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.config_registry import (
    IMAGE_MODEL_CHOICES,
    LLM_MODEL_CHOICES,
    OPENAI_EMBEDDING_MODEL_CHOICES,
)
from app.models.api_credential import TextbookJobSecret, UserApiCredential
from app.schemas.byok import TextbookModelSelection
from app.services.runtime_config import RuntimeConfigError, get_api_key, get_runtime_config

USER_PROVIDED_API_KEYS = "user_provided_api_keys"
SYSTEM_CREDIT_BILLING = "system_credit_billing"
GENERATION_MODE_LABELS = {
    USER_PROVIDED_API_KEYS: "Người dùng tự nhập API key",
    SYSTEM_CREDIT_BILLING: "Nạp tiền bằng credit hệ thống",
}
PROVIDERS = {"openai", "serper"}


class ByokConfigurationError(RuntimeError):
    pass


class ByokCredentialError(ValueError):
    pass


def generation_mode() -> str:
    raw = str(
        get_runtime_config("TEXTBOOK_GENERATION_MODE", required=False)
        or settings.TEXTBOOK_GENERATION_MODE
        or SYSTEM_CREDIT_BILLING
    ).strip()
    return raw if raw in GENERATION_MODE_LABELS else SYSTEM_CREDIT_BILLING


def generation_mode_label(mode: str | None = None) -> str:
    return GENERATION_MODE_LABELS.get(mode or generation_mode(), GENERATION_MODE_LABELS[SYSTEM_CREDIT_BILLING])


def user_keys_required() -> bool:
    return generation_mode() == USER_PROVIDED_API_KEYS


def _fernet() -> Fernet:
    key = str(settings.BYOK_ENCRYPTION_KEY or "").strip()
    if not key:
        raise ByokConfigurationError("BYOK_ENCRYPTION_KEY is required to store user API keys.")
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise ByokConfigurationError("BYOK_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.strip().encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ByokConfigurationError("Stored API key cannot be decrypted with the current BYOK_ENCRYPTION_KEY.") from exc


def secret_last4(value: str) -> str:
    cleaned = str(value or "").strip()
    return cleaned[-4:] if len(cleaned) >= 4 else cleaned


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in PROVIDERS:
        raise ByokCredentialError("Unsupported credential provider.")
    return normalized


async def credential_state(db: AsyncSession, user_id: int, provider: str) -> dict[str, Any]:
    normalized = normalize_provider(provider)
    row = await db.scalar(
        select(UserApiCredential).where(
            UserApiCredential.user_id == user_id,
            UserApiCredential.provider == normalized,
        )
    )
    if not row:
        return {"configured": False, "last4": "", "updated_at": None}
    return {
        "configured": True,
        "last4": row.last4 or "",
        "updated_at": row.updated_at,
    }


async def saved_key(db: AsyncSession, user_id: int, provider: str) -> str:
    normalized = normalize_provider(provider)
    row = await db.scalar(
        select(UserApiCredential).where(
            UserApiCredential.user_id == user_id,
            UserApiCredential.provider == normalized,
        )
    )
    return decrypt_secret(row.encrypted_value) if row else ""


async def upsert_user_key(db: AsyncSession, user_id: int, provider: str, value: str) -> None:
    normalized = normalize_provider(provider)
    cleaned = str(value or "").strip()
    if not cleaned:
        return
    row = await db.scalar(
        select(UserApiCredential).where(
            UserApiCredential.user_id == user_id,
            UserApiCredential.provider == normalized,
        )
    )
    encrypted_value = encrypt_secret(cleaned)
    if row:
        row.encrypted_value = encrypted_value  # type: ignore[assignment]
        row.last4 = secret_last4(cleaned)  # type: ignore[assignment]
        row.updated_at = datetime.utcnow()  # type: ignore[assignment]
    else:
        db.add(UserApiCredential(
            user_id=user_id,
            provider=normalized,
            encrypted_value=encrypted_value,
            last4=secret_last4(cleaned),
        ))


async def delete_user_key(db: AsyncSession, user_id: int, provider: str) -> None:
    await db.execute(
        delete(UserApiCredential).where(
            UserApiCredential.user_id == user_id,
            UserApiCredential.provider == normalize_provider(provider),
        )
    )


async def resolve_request_keys(
    db: AsyncSession,
    user_id: int,
    *,
    credential_usage: str,
    openai_api_key: str | None,
    serper_api_key: str | None,
    allow_system_credentials: bool = False,
    skip_serper: bool = False,
) -> dict[str, str]:
    if credential_usage == "system":
        if not allow_system_credentials:
            raise ByokCredentialError("Chỉ admin mới được sử dụng API key hệ thống.")
        try:
            openai = get_api_key("OPENAI_API_KEY", required=True)
            serper = get_api_key("SERPER_API_KEY", required=False)
        except RuntimeConfigError as exc:
            raise ByokCredentialError("API key hệ thống chưa được cấu hình đầy đủ.") from exc
    elif credential_usage == "one_time":
        openai = str(openai_api_key or "").strip()
        serper = str(serper_api_key or "").strip()
    else:
        openai = await saved_key(db, user_id, "openai")
        serper = await saved_key(db, user_id, "serper")
        if openai_api_key:
            openai = str(openai_api_key).strip()
        if serper_api_key:
            serper = str(serper_api_key).strip()

    if user_keys_required() and not openai:
        raise ByokCredentialError("Vui lòng nhập OpenAI API key trước khi tạo giáo trình.")
    keys = {"OPENAI_API_KEY": openai}
    if skip_serper:
        serper = ""
    if serper:
        keys["SERPER_API_KEY"] = serper
    return keys


def validate_model_selection(selection: TextbookModelSelection | None) -> dict[str, str]:
    selection = selection or TextbookModelSelection()
    overrides = selection.to_runtime_overrides()
    allowed = {
        "LLM_MODEL_PREMIUM": set(LLM_MODEL_CHOICES),
        "LLM_MODEL_CHEAP": set(LLM_MODEL_CHOICES),
        "OPENAI_EMBEDDING_MODEL": set(OPENAI_EMBEDDING_MODEL_CHOICES),
        "IMAGE_MODEL_DEFAULT": set(IMAGE_MODEL_CHOICES),
        "IMAGE_VALIDATION_MODEL": set(LLM_MODEL_CHOICES),
    }
    for key, value in overrides.items():
        if value not in allowed.get(key, set()):
            raise ByokCredentialError(f"Model không được hỗ trợ: {value}")
    if "IMAGE_MODEL_DEFAULT" in overrides:
        overrides["IMAGE_MODEL_PREMIUM"] = overrides["IMAGE_MODEL_DEFAULT"]
    return overrides


async def replace_job_secrets(
    db: AsyncSession,
    textbook_id: int,
    keys: dict[str, str],
    *,
    ttl_days: int = 14,
) -> None:
    await db.execute(delete(TextbookJobSecret).where(TextbookJobSecret.textbook_id == textbook_id))
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)
    for config_key, value in keys.items():
        provider = "openai" if config_key == "OPENAI_API_KEY" else "serper"
        if not value:
            continue
        db.add(TextbookJobSecret(
            textbook_id=textbook_id,
            provider=provider,
            encrypted_value=encrypt_secret(value),
            last4=secret_last4(value),
            expires_at=expires_at,
        ))


async def load_job_runtime_overrides(db: AsyncSession, textbook_id: int) -> dict[str, str]:
    rows = await db.execute(
        select(TextbookJobSecret).where(TextbookJobSecret.textbook_id == textbook_id)
    )
    overrides: dict[str, str] = {}
    for row in rows.scalars().all():
        provider = normalize_provider(row.provider)
        key = "OPENAI_API_KEY" if provider == "openai" else "SERPER_API_KEY"
        overrides[key] = decrypt_secret(row.encrypted_value)
    return overrides


async def delete_job_secrets(db: AsyncSession, textbook_id: int) -> None:
    await db.execute(delete(TextbookJobSecret).where(TextbookJobSecret.textbook_id == textbook_id))
