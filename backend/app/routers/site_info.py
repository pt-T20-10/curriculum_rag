from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.site_contact_config import SiteContactConfig
from app.models.user import User, UserRole
from app.schemas.site_info import (
    SiteInfoAdminResponse,
    SiteInfoPublicResponse,
    SiteInfoUpdate,
)
from app.security.jwt import require_admin


router = APIRouter(tags=["site-info"])

DEFAULT_SITE_INFO = {
    "service_name_vi": "AATG",
    "service_name_en": "AATG",
    "operator_name": "",
    "address_vi": "",
    "address_en": "",
    "support_email": "",
    "privacy_email": "",
    "phone": "",
    "support_hours_vi": "Thứ Hai - Thứ Sáu, 08:00 - 17:00 (GMT+7)",
    "support_hours_en": "Monday - Friday, 08:00 - 17:00 (GMT+7)",
    "response_time_vi": "Chúng tôi phản hồi trong thời gian hợp lý tùy theo mức độ phức tạp của yêu cầu.",
    "response_time_en": "We respond within a reasonable time based on the complexity of the request.",
    "effective_date": date(2026, 6, 20),
}


async def _get_config(db: AsyncSession) -> SiteContactConfig | None:
    result = await db.execute(
        select(SiteContactConfig).where(SiteContactConfig.id == 1)
    )
    return result.scalar_one_or_none()


async def _require_admin_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if user.is_deleted or user.is_locked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is locked")
    return user


def _admin_payload(config: SiteContactConfig | None) -> SiteInfoAdminResponse:
    if not config:
        return SiteInfoAdminResponse(
            configured=False,
            updated_at=None,
            updated_by=None,
            **DEFAULT_SITE_INFO,
        )
    return SiteInfoAdminResponse(
        configured=True,
        service_name_vi=config.service_name_vi,
        service_name_en=config.service_name_en,
        operator_name=config.operator_name,
        address_vi=config.address_vi,
        address_en=config.address_en,
        support_email=config.support_email or None,
        privacy_email=config.privacy_email or None,
        phone=config.phone,
        support_hours_vi=config.support_hours_vi,
        support_hours_en=config.support_hours_en,
        response_time_vi=config.response_time_vi,
        response_time_en=config.response_time_en,
        effective_date=config.effective_date,
        updated_at=config.updated_at,
        updated_by=config.updated_by,
    )


@router.get("/site-info", response_model=SiteInfoPublicResponse)
async def get_public_site_info(
    language: Literal["vi", "en"] = Query("en"),
    db: AsyncSession = Depends(get_async_db),
) -> SiteInfoPublicResponse:
    config = await _get_config(db)
    source = _admin_payload(config)
    suffix = "en" if language == "en" else "vi"
    return SiteInfoPublicResponse(
        service_name=getattr(source, f"service_name_{suffix}"),
        operator_name=source.operator_name,
        address=getattr(source, f"address_{suffix}"),
        support_email=str(source.support_email or ""),
        privacy_email=str(source.privacy_email or ""),
        phone=source.phone,
        support_hours=getattr(source, f"support_hours_{suffix}"),
        response_time=getattr(source, f"response_time_{suffix}"),
        effective_date=source.effective_date,
    )


@router.get("/admin/site-info", response_model=SiteInfoAdminResponse)
async def get_admin_site_info(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> SiteInfoAdminResponse:
    await _require_admin_user(db, admin_id)
    return _admin_payload(await _get_config(db))


@router.put("/admin/site-info", response_model=SiteInfoAdminResponse)
async def update_admin_site_info(
    body: SiteInfoUpdate,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
) -> SiteInfoAdminResponse:
    await _require_admin_user(db, admin_id)
    config = await _get_config(db)
    if not config:
        config = SiteContactConfig(id=1)
        db.add(config)

    values = body.model_dump()
    values["support_email"] = str(body.support_email or "")
    values["privacy_email"] = str(body.privacy_email or "")
    for key, value in values.items():
        setattr(config, key, value)
    config.updated_by = admin_id

    await db.commit()
    await db.refresh(config)
    return _admin_payload(config)
