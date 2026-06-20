import logging
import time
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.site_contact_config import SiteContactConfig
from app.models.user import User, UserRole
from app.schemas.account_deletion import (
    AccountDeletionRequestCreate,
    AccountDeletionRequestResponse,
)
from app.security.jwt import verify_token
from app.services.email_service import send_account_deletion_request_email


logger = logging.getLogger(__name__)
router = APIRouter(tags=["account-deletion"])
optional_security = HTTPBearer(auto_error=False)

_RATE_LIMIT_SECONDS = 60
_recent_requests: dict[str, float] = {}
_rate_limit_lock = Lock()

_REASON_LABELS = {
    "vi": {
        "": "Không cung cấp",
        "no_longer_use": "Không còn sử dụng dịch vụ",
        "privacy_concerns": "Lo ngại về quyền riêng tư",
        "switching_service": "Chuyển sang dịch vụ khác",
        "poor_experience": "Trải nghiệm không tốt",
        "other": "Lý do khác",
    },
    "en": {
        "": "Not provided",
        "no_longer_use": "No longer using the service",
        "privacy_concerns": "Privacy concerns",
        "switching_service": "Switching to another service",
        "poor_experience": "Poor experience",
        "other": "Other",
    },
}


def _claim_request_slot(client_key: str) -> bool:
    now = time.monotonic()
    with _rate_limit_lock:
        if len(_recent_requests) > 1000:
            cutoff = now - _RATE_LIMIT_SECONDS
            stale_keys = [key for key, sent_at in _recent_requests.items() if sent_at < cutoff]
            for key in stale_keys:
                _recent_requests.pop(key, None)

        last_request = _recent_requests.get(client_key)
        if last_request is not None and now - last_request < _RATE_LIMIT_SECONDS:
            return False
        _recent_requests[client_key] = now
        return True


def _release_request_slot(client_key: str) -> None:
    with _rate_limit_lock:
        _recent_requests.pop(client_key, None)


async def _authenticated_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User | None:
    if not credentials:
        return None
    payload = verify_token(credentials.credentials)
    if not payload or payload.get("sub") is None:
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def _resolve_deletion_recipient(db: AsyncSession) -> str:
    contact_result = await db.execute(
        select(
            SiteContactConfig.privacy_email,
            SiteContactConfig.support_email,
        ).where(SiteContactConfig.id == 1)
    )
    contact = contact_result.first()
    if contact:
        privacy_email = str(contact.privacy_email or "").strip()
        support_email = str(contact.support_email or "").strip()
        if privacy_email:
            return privacy_email
        if support_email:
            return support_email

    admin_result = await db.execute(
        select(User.email)
        .where(
            User.role == UserRole.ADMIN.value,
            User.is_active.is_(True),
            User.is_locked.is_(False),
            User.is_deleted.is_(False),
        )
        .order_by(User.id.asc())
        .limit(1)
    )
    return str(admin_result.scalar_one_or_none() or "").strip()


@router.post(
    "/account-deletion-requests",
    response_model=AccountDeletionRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an account deletion request",
)
async def create_account_deletion_request(
    body: AccountDeletionRequestCreate,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: AsyncSession = Depends(get_async_db),
) -> AccountDeletionRequestResponse:
    if body.website:
        return AccountDeletionRequestResponse(message="Account deletion request accepted")

    client_key = request.client.host if request.client else "unknown"
    if not _claim_request_slot(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="account_deletion_rate_limited",
        )

    user = await _authenticated_user(credentials, db)
    account_email = user.email if user else str(body.email)
    user_id = int(user.id) if user else None
    recipient = await _resolve_deletion_recipient(db)
    if not recipient:
        _release_request_slot(client_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account_deletion_recipient_unavailable",
        )

    reason_label = _REASON_LABELS[body.ui_language][body.reason]
    try:
        sent = await send_account_deletion_request_email(
            to_email=recipient,
            account_email=account_email,
            user_id=user_id,
            reason=reason_label,
            notes=body.notes,
            ui_language=body.ui_language,
            authenticated=user is not None,
        )
    except Exception as exc:
        _release_request_slot(client_key)
        logger.error("Account deletion request delivery failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account_deletion_email_unavailable",
        ) from exc

    if not sent:
        _release_request_slot(client_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account_deletion_email_unavailable",
        )

    return AccountDeletionRequestResponse(message="Account deletion request accepted")
