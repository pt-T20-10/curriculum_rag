"""
Advanced Settings API — per-user overrides and system-wide admin defaults.

Endpoints:
  GET  /config/registry                     — parameter definitions
  GET  /config/effective                    — merged effective config for current user
  GET  /config/user/advanced                — current user's saved overrides
  POST /config/user/advanced                — save / update user overrides
  DELETE /config/user/advanced              — reset all user overrides to defaults
  GET  /config/admin/system                 — system-level config (admin only)
  PUT  /config/admin/system                 — update system defaults (admin only)
  GET  /config/admin/system/audit           — audit log (admin only)
  GET  /config/admin/system/overrides       — per-param override counts (admin only)
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.config_registry import (
    PARAMETER_GROUPS,
    PARAMETER_REGISTRY,
    get_admin_registry,
    get_defaults,
    get_user_registry,
)
from app.database import get_async_db
from app.models.config import ConfigAuditLog, SystemConfig, UserConfig
from app.models.user import User, UserRole
from app.security.jwt import get_current_user_id, require_admin
from app.services.deployment_profile import detect_deployment_profile
from app.services.runtime_config import MASKED_VALUE, invalidate_runtime_config_cache

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode(value: Any) -> str:
    """JSON-encode a value for DB storage."""
    return json.dumps(value)


def _decode(raw: str) -> Any:
    """JSON-decode a value from DB storage."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _mask_sensitive_raw(key: str, raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    entry = PARAMETER_REGISTRY.get(key, {})
    if not entry.get("sensitive"):
        return raw
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        decoded = raw
    return MASKED_VALUE if decoded else raw


def _build_admin_system_config(
    admin_registry: Dict[str, Dict[str, Any]],
    system_overrides: Dict[str, Any],
    reveal_sensitive: bool = False,
    reveal_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Build admin-visible system config, optionally revealing sensitive values."""
    config: Dict[str, Any] = {}
    for key, entry in admin_registry.items():
        try:
            base_value = getattr(settings, key, entry["default"])
        except Exception:
            base_value = entry["default"]

        value = system_overrides.get(key, base_value)
        reveal_this_key = reveal_sensitive and (reveal_key is None or reveal_key == key)
        config[key] = MASKED_VALUE if (entry.get("sensitive") and value and not reveal_this_key) else value

    return config


def _coerce(key: str, value: Any) -> Any:
    """Coerce a raw value to the declared type for a registry parameter."""
    entry = PARAMETER_REGISTRY.get(key)
    if entry is None:
        return value
    typ = entry["type"]
    try:
        if typ == "int":
            return int(value)
        if typ == "float":
            return float(value)
        if typ == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        return value
    except (ValueError, TypeError):
        return value


def _validate(key: str, value: Any) -> Optional[str]:
    """Return an error string if value is out of bounds, else None."""
    entry = PARAMETER_REGISTRY.get(key)
    if entry is None:
        return f"Unknown parameter: {key}"

    if entry.get("choices") and value not in entry["choices"]:
        return f"Invalid choice for {key}: must be one of {entry['choices']}"

    mn = entry.get("min")
    mx = entry.get("max")
    if mn is not None and value < mn:
        return f"{key} must be >= {mn}"
    if mx is not None and value > mx:
        return f"{key} must be <= {mx}"
    return None


async def _load_system_config(db: AsyncSession) -> Dict[str, Any]:
    """Load all system-level overrides from DB as a flat dict."""
    rows = await db.execute(select(SystemConfig))
    return {row.key: _decode(row.value) for row in rows.scalars().all()}


async def _load_user_config(db: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Load all user-level overrides from DB as a flat dict."""
    rows = await db.execute(select(UserConfig).where(UserConfig.user_id == user_id))
    return {row.key: _decode(row.value) for row in rows.scalars().all()}


def _merge_config(
    user_id: int,
    system_overrides: Dict[str, Any],
    user_overrides: Dict[str, Any],
    include_admin_only: bool = False,
) -> Dict[str, Any]:
    """
    Merge: user > system > config.py defaults
    Returns only parameters visible to the given caller.
    """
    base = {}
    for key, entry in PARAMETER_REGISTRY.items():
        if not include_admin_only and entry.get("admin_only"):
            continue
        default = entry["default"]
        # Try to read from config.py at runtime
        try:
            base[key] = getattr(settings, key, default)
        except Exception:
            base[key] = default

    system = {k: v for k, v in system_overrides.items() if k in PARAMETER_REGISTRY}
    user = {k: v for k, v in user_overrides.items() if k in PARAMETER_REGISTRY}

    return {**base, **system, **user}


async def _require_admin_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.role != UserRole.ADMIN.value:  # type: ignore
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if user.is_deleted or user.is_locked:  # type: ignore
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is locked")
    return user


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ParameterEntry(BaseModel):
    key: str
    label: str
    description: str
    group: str
    type: str
    default: Any
    user_editable: bool
    admin_only: bool
    sensitive: bool
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[List[str]] = None
    multiline: bool = False


class RegistryResponse(BaseModel):
    parameters: Dict[str, ParameterEntry]
    groups: Dict[str, Dict[str, str]]


class EffectiveConfigResponse(BaseModel):
    effective: Dict[str, Any]
    system_overrides: List[str]
    user_overrides: List[str]


class UserAdvancedConfigResponse(BaseModel):
    overrides: Dict[str, Any]
    updated_at: Optional[datetime] = None


class SaveOverridesRequest(BaseModel):
    overrides: Dict[str, Any]


class SystemConfigResponse(BaseModel):
    config: Dict[str, Any]


class SystemConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]


class AuditLogEntry(BaseModel):
    id: int
    admin_id: Optional[int]
    admin_email: Optional[str]
    key: str
    old_value: Optional[str]
    new_value: str
    created_at: datetime


class OverrideCountItem(BaseModel):
    key: str
    label: str
    override_count: int


class SetupStatusItem(BaseModel):
    key: str
    label: str
    group: str
    severity: str
    source: str
    message: str


class SetupConfiguredItem(BaseModel):
    key: str
    label: str
    group: str
    source: str
    masked: bool


class DeploymentProfileResponse(BaseModel):
    key: str
    severity: str
    title: str
    summary: str
    recommended_action: str
    max_parallel_jobs: int
    settings: Dict[str, Any]
    signature: str


class AdminSetupStatusResponse(BaseModel):
    is_ready: bool
    generation_mode: str
    missing_required: List[SetupStatusItem]
    warnings: List[SetupStatusItem]
    configured_from_env: List[SetupConfiguredItem]
    configured_from_db: List[SetupConfiguredItem]
    deployment_profile: DeploymentProfileResponse


SETUP_ALWAYS_REQUIRED = [
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "EMAIL_FROM",
]


def _setup_label(admin_registry: Dict[str, Dict[str, Any]], key: str) -> str:
    return str(admin_registry.get(key, {}).get("label") or key)


def _setup_group(admin_registry: Dict[str, Dict[str, Any]], key: str) -> str:
    return str(admin_registry.get(key, {}).get("group") or "api_keys")


def _setup_is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == "" or value == MASKED_VALUE


def _setup_source(key: str, system_overrides: Dict[str, Any]) -> tuple[str, Any]:
    db_value = system_overrides.get(key)
    if not _setup_is_missing(db_value):
        return "database", db_value
    return "env", getattr(settings, key, None)


def _setup_item(
    admin_registry: Dict[str, Dict[str, Any]],
    key: str,
    severity: str,
    source: str,
    message: str,
) -> SetupStatusItem:
    return SetupStatusItem(
        key=key,
        label=_setup_label(admin_registry, key),
        group=_setup_group(admin_registry, key),
        severity=severity,
        source=source,
        message=message,
    )


def _configured_item(
    admin_registry: Dict[str, Dict[str, Any]],
    key: str,
    source: str,
) -> SetupConfiguredItem:
    entry = admin_registry.get(key, {})
    return SetupConfiguredItem(
        key=key,
        label=_setup_label(admin_registry, key),
        group=_setup_group(admin_registry, key),
        source=source,
        masked=bool(entry.get("sensitive")),
    )


def _setup_has_any_key(
    keys: list[str],
    system_overrides: Dict[str, Any],
) -> tuple[bool, list[tuple[str, str]]]:
    configured: list[tuple[str, str]] = []
    for key in keys:
        source, value = _setup_source(key, system_overrides)
        if not _setup_is_missing(value):
            configured.append((key, source))
    return bool(configured), configured


def _inspect_any_key(
    admin_registry: Dict[str, Dict[str, Any]],
    system_overrides: Dict[str, Any],
    *,
    keys: list[str],
    missing_key: str,
    severity: str,
    message: str,
    tracked_keys: set[str],
    missing_required: List[SetupStatusItem],
    warnings: List[SetupStatusItem],
    configured_from_env: List[SetupConfiguredItem],
    configured_from_db: List[SetupConfiguredItem],
) -> None:
    tracked_keys.update(keys)
    has_value, configured = _setup_has_any_key(keys, system_overrides)
    if not has_value:
        target = missing_required if severity == "required" else warnings
        target.append(_setup_item(admin_registry, missing_key, severity, "missing", message))
        return
    for key, source in configured:
        if source == "database":
            configured_from_db.append(_configured_item(admin_registry, key, source))
        else:
            configured_from_env.append(_configured_item(admin_registry, key, source))


def _build_admin_setup_status(
    admin_registry: Dict[str, Dict[str, Any]],
    system_overrides: Dict[str, Any],
) -> AdminSetupStatusResponse:
    missing_required: List[SetupStatusItem] = []
    warnings: List[SetupStatusItem] = []
    configured_from_env: List[SetupConfiguredItem] = []
    configured_from_db: List[SetupConfiguredItem] = []
    tracked_keys: set[str] = set()

    def inspect_key(key: str, severity: str, message: str) -> None:
        source, value = _setup_source(key, system_overrides)
        tracked_keys.add(key)
        if _setup_is_missing(value):
            target = missing_required if severity == "required" else warnings
            target.append(_setup_item(admin_registry, key, severity, "missing", message))
        elif source == "database":
            configured_from_db.append(_configured_item(admin_registry, key, source))
        else:
            configured_from_env.append(_configured_item(admin_registry, key, source))

    for key in SETUP_ALWAYS_REQUIRED:
        inspect_key(
            key,
            "required",
            "Cần cấu hình email để gửi xác nhận đăng ký, đổi mật khẩu và thông báo hệ thống.",
        )

    generation_mode_source, generation_mode_value = _setup_source("TEXTBOOK_GENERATION_MODE", system_overrides)
    generation_mode = str(generation_mode_value or settings.TEXTBOOK_GENERATION_MODE)
    tracked_keys.add("TEXTBOOK_GENERATION_MODE")
    if generation_mode_source == "database":
        configured_from_db.append(_configured_item(admin_registry, "TEXTBOOK_GENERATION_MODE", "database"))
    else:
        configured_from_env.append(_configured_item(admin_registry, "TEXTBOOK_GENERATION_MODE", "env"))

    if generation_mode == "system_credit_billing":
        _inspect_any_key(
            admin_registry,
            system_overrides,
            keys=["OPENAI_API_KEYS", "OPENAI_API_KEY"],
            missing_key="OPENAI_API_KEYS",
            severity="required",
            message="Chế độ nạp tiền bằng credit hệ thống cần ít nhất một OpenAI API key để tạo giáo trình.",
            tracked_keys=tracked_keys,
            missing_required=missing_required,
            warnings=warnings,
            configured_from_env=configured_from_env,
            configured_from_db=configured_from_db,
        )
        inspect_key(
            "SEPAY_ACCOUNT_NUMBER",
            "required",
            "Cần số tài khoản SePay/tài khoản nhận tiền để màn hình nạp tiền hoạt động đúng.",
        )
        _inspect_any_key(
            admin_registry,
            system_overrides,
            keys=["SERPER_API_KEYS", "SERPER_API_KEY"],
            missing_key="SERPER_API_KEYS",
            severity="warning",
            message="Thiếu Serper API key thì ảnh/search thực tế sẽ giảm chất lượng.",
            tracked_keys=tracked_keys,
            missing_required=missing_required,
            warnings=warnings,
            configured_from_env=configured_from_env,
            configured_from_db=configured_from_db,
        )
        inspect_key(
            "SEPAY_API_KEY",
            "warning",
            "Thiếu SePay API key thì các thao tác tích hợp SePay tự động có thể không hoạt động.",
        )
    else:
        _inspect_any_key(
            admin_registry,
            system_overrides,
            keys=["OPENAI_API_KEYS", "OPENAI_API_KEY"],
            missing_key="OPENAI_API_KEYS",
            severity="warning",
            message="Tùy chọn: cần key này nếu Admin muốn tạo giáo trình bằng API key hệ thống.",
            tracked_keys=tracked_keys,
            missing_required=missing_required,
            warnings=warnings,
            configured_from_env=configured_from_env,
            configured_from_db=configured_from_db,
        )
        _inspect_any_key(
            admin_registry,
            system_overrides,
            keys=["SERPER_API_KEYS", "SERPER_API_KEY"],
            missing_key="SERPER_API_KEYS",
            severity="warning",
            message="Tùy chọn: giúp Admin dùng API key hệ thống có ảnh/search thực tế tốt hơn.",
            tracked_keys=tracked_keys,
            missing_required=missing_required,
            warnings=warnings,
            configured_from_env=configured_from_env,
            configured_from_db=configured_from_db,
        )

    google_keys = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"]
    google_values = {key: _setup_source(key, system_overrides) for key in google_keys}
    if any(not _setup_is_missing(value) for _, value in google_values.values()):
        for key, (source, value) in google_values.items():
            tracked_keys.add(key)
            if _setup_is_missing(value):
                warnings.append(_setup_item(
                    admin_registry,
                    key,
                    "warning",
                    "missing",
                    "Đăng nhập Google đang được cấu hình dở; cần đủ Client ID, Client Secret và Redirect URI.",
                ))
            elif source == "database":
                configured_from_db.append(_configured_item(admin_registry, key, source))
            else:
                configured_from_env.append(_configured_item(admin_registry, key, source))

    def dedupe(items: List[Any]) -> List[Any]:
        seen: set[tuple[str, str]] = set()
        result = []
        for item in items:
            marker = (item.key, getattr(item, "source", ""))
            if marker in seen:
                continue
            seen.add(marker)
            result.append(item)
        return result

    return AdminSetupStatusResponse(
        is_ready=len(missing_required) == 0,
        generation_mode=generation_mode,
        missing_required=dedupe(missing_required),
        warnings=dedupe(warnings),
        configured_from_env=dedupe(configured_from_env),
        configured_from_db=dedupe(configured_from_db),
        deployment_profile=detect_deployment_profile(system_overrides),
    )


# ---------------------------------------------------------------------------
# GET /config/registry
# ---------------------------------------------------------------------------

@router.get("/config/registry", response_model=RegistryResponse, summary="Parameter registry")
async def get_registry(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Return parameter definitions. Admins see all; regular users see only user_editable params."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    is_admin = user and user.role == UserRole.ADMIN.value and not user.is_locked  # type: ignore

    registry = get_admin_registry() if is_admin else get_user_registry() #type: ignore
    parameters = {}
    for key, entry in registry.items():
        parameters[key] = ParameterEntry(
            key=key,
            label=entry["label"],
            description=entry["description"],
            group=entry["group"],
            type=entry["type"],
            default=entry["default"],
            user_editable=entry["user_editable"],
            admin_only=entry.get("admin_only", False),
            sensitive=entry.get("sensitive", False),
            min=entry.get("min"),
            max=entry.get("max"),
            choices=entry.get("choices"),
            multiline=bool(entry.get("multiline")),
        )

    return RegistryResponse(parameters=parameters, groups=PARAMETER_GROUPS)


# ---------------------------------------------------------------------------
# GET /config/effective
# ---------------------------------------------------------------------------

@router.get("/config/effective", response_model=EffectiveConfigResponse, summary="Effective config for current user")
async def get_effective_config(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    is_admin = user and user.role == UserRole.ADMIN.value and not user.is_locked  # type: ignore

    system_overrides = await _load_system_config(db)
    user_overrides = await _load_user_config(db, user_id)
    effective = _merge_config(user_id, system_overrides, user_overrides, include_admin_only=bool(is_admin))

    # Mask sensitive values
    for key in list(effective.keys()):
        entry = PARAMETER_REGISTRY.get(key, {})
        if entry.get("sensitive") and effective[key]:
            effective[key] = "••••••••"

    return EffectiveConfigResponse(
        effective=effective,
        system_overrides=list(system_overrides.keys()),
        user_overrides=list(user_overrides.keys()),
    )


# ---------------------------------------------------------------------------
# GET /config/user/advanced
# ---------------------------------------------------------------------------

@router.get("/config/user/advanced", response_model=UserAdvancedConfigResponse, summary="User's saved overrides")
async def get_user_overrides(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    rows_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id).order_by(UserConfig.updated_at.desc())
    )
    rows = rows_result.scalars().all()
    overrides = {row.key: _decode(row.value) for row in rows}
    latest = rows[0].updated_at if rows else None
    return UserAdvancedConfigResponse(overrides=overrides, updated_at=latest)


# ---------------------------------------------------------------------------
# POST /config/user/advanced
# ---------------------------------------------------------------------------

@router.post("/config/user/advanced", response_model=UserAdvancedConfigResponse, summary="Save user overrides")
async def save_user_overrides(
    body: SaveOverridesRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    user_registry = get_user_registry()
    errors: Dict[str, str] = {}

    for key, raw_value in body.overrides.items():
        if key not in user_registry:
            errors[key] = "Unknown or non-editable parameter"
            continue
        value = _coerce(key, raw_value)
        err = _validate(key, value)
        if err:
            errors[key] = err

    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    for key, raw_value in body.overrides.items():
        if key not in user_registry:
            continue
        value = _coerce(key, raw_value)
        existing = await db.execute(
            select(UserConfig).where(UserConfig.user_id == user_id, UserConfig.key == key)
        )
        row = existing.scalar_one_or_none()
        if row:
            row.value = _encode(value)  # type: ignore
        else:
            db.add(UserConfig(user_id=user_id, key=key, value=_encode(value)))

    await db.commit()

    rows_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id).order_by(UserConfig.updated_at.desc())
    )
    rows = rows_result.scalars().all()
    return UserAdvancedConfigResponse(
        overrides={row.key: _decode(row.value) for row in rows},
        updated_at=rows[0].updated_at if rows else None,
    )


# ---------------------------------------------------------------------------
# DELETE /config/user/advanced
# ---------------------------------------------------------------------------

@router.delete("/config/user/advanced", summary="Reset all user overrides to defaults")
async def reset_user_overrides(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    await db.execute(delete(UserConfig).where(UserConfig.user_id == user_id))
    await db.commit()
    return {"message": "All user overrides have been reset to defaults."}


# ---------------------------------------------------------------------------
# GET /config/admin/system
# ---------------------------------------------------------------------------

@router.get("/config/admin/system", response_model=SystemConfigResponse, summary="System-level config (admin only)")
async def get_system_config(
    reveal_sensitive: bool = Query(
        False,
        description="Return raw sensitive values for admins instead of masked placeholders.",
    ),
    reveal_key: Optional[str] = Query(
        None,
        description="When revealing sensitive values, reveal only this parameter key.",
    ),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_admin_user(db, admin_id)
    system_overrides = await _load_system_config(db)
    admin_registry = get_admin_registry()

    if reveal_key is not None and reveal_key not in admin_registry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown parameter: {reveal_key}")

    return SystemConfigResponse(
        config=_build_admin_system_config(
            admin_registry,
            system_overrides,
            reveal_sensitive=reveal_sensitive,
            reveal_key=reveal_key,
        )
    )


@router.get(
    "/config/admin/setup-status",
    response_model=AdminSetupStatusResponse,
    summary="Admin setup checklist status",
)
async def get_admin_setup_status(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_admin_user(db, admin_id)
    system_overrides = await _load_system_config(db)
    admin_registry = get_admin_registry()
    return _build_admin_setup_status(admin_registry, system_overrides)


# ---------------------------------------------------------------------------
# PUT /config/admin/system
# ---------------------------------------------------------------------------

@router.put("/config/admin/system", response_model=SystemConfigResponse, summary="Update system defaults (admin only)")
async def update_system_config(
    body: SystemConfigUpdateRequest,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_admin_user(db, admin_id)
    admin_registry = get_admin_registry()
    errors: Dict[str, str] = {}

    for key, raw_value in body.updates.items():
        if key not in admin_registry:
            errors[key] = "Unknown parameter"
            continue
        entry = admin_registry[key]
        if entry.get("sensitive"):
            if raw_value == MASKED_VALUE:
                continue
            # Allow updating sensitive params. They are masked by default and
            # revealed only when an admin explicitly requests it.
            continue
        value = _coerce(key, raw_value)
        err = _validate(key, value)
        if err:
            errors[key] = err

    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    for key, raw_value in body.updates.items():
        if key not in admin_registry:
            continue
        entry = admin_registry[key]
        if entry.get("sensitive") and raw_value == MASKED_VALUE:
            continue
        value = _coerce(key, raw_value)

        # Get old value for audit log
        existing = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = existing.scalar_one_or_none()
        old_raw = row.value if row else None

        # Skip no-op (value unchanged relative to current DB value or base default)
        try:
            base_value = getattr(settings, key, admin_registry[key]["default"])
        except Exception:
            base_value = admin_registry[key]["default"]
        current_effective = _decode(old_raw) if old_raw is not None else base_value
        if current_effective == value:
            continue

        # Upsert SystemConfig
        if row:
            row.value = _encode(value)  # type: ignore
            row.updated_by = admin_id  # type: ignore
        else:
            db.add(SystemConfig(key=key, value=_encode(value), updated_by=admin_id))

        # Append audit log
        if entry.get("sensitive"):
            audit_old = _mask_sensitive_raw(key, old_raw)
            audit_new = MASKED_VALUE if value else _encode(value)
        else:
            audit_old = old_raw
            audit_new = _encode(value)

        db.add(ConfigAuditLog(
            admin_id=admin_id,
            key=key,
            old_value=audit_old,
            new_value=audit_new,
        ))

    await db.commit()
    invalidate_runtime_config_cache()

    # Return fresh state
    system_overrides = await _load_system_config(db)
    return SystemConfigResponse(config=_build_admin_system_config(admin_registry, system_overrides))


# ---------------------------------------------------------------------------
# GET /config/admin/system/audit
# ---------------------------------------------------------------------------

@router.get("/config/admin/system/audit", response_model=List[AuditLogEntry], summary="Config audit log (admin only)")
async def get_audit_log(
    limit: int = 20,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_admin_user(db, admin_id)

    rows_result = await db.execute(
        select(ConfigAuditLog, User.email)
        .outerjoin(User, User.id == ConfigAuditLog.admin_id)
        .order_by(ConfigAuditLog.created_at.desc())
        .limit(limit)
    )
    entries = []
    for log_row, admin_email in rows_result.all():
        entries.append(AuditLogEntry(
            id=log_row.id,
            admin_id=log_row.admin_id,
            admin_email=admin_email,
            key=log_row.key,
            old_value=_mask_sensitive_raw(log_row.key, log_row.old_value),
            new_value=_mask_sensitive_raw(log_row.key, log_row.new_value) or "",
            created_at=log_row.created_at,
        ))
    return entries


# ---------------------------------------------------------------------------
# GET /config/admin/system/overrides
# ---------------------------------------------------------------------------

@router.get("/config/admin/system/overrides", response_model=List[OverrideCountItem], summary="Per-param override counts (admin only)")
async def get_override_counts(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _require_admin_user(db, admin_id)

    rows_result = await db.execute(
        select(UserConfig.key, func.count(UserConfig.user_id.distinct()).label("cnt"))
        .group_by(UserConfig.key)
    )
    counts = {row.key: row.cnt for row in rows_result.all()}

    items = []
    for key, entry in get_admin_registry().items():
        items.append(OverrideCountItem(
            key=key,
            label=entry["label"],
            override_count=counts.get(key, 0),
        ))
    return items
