import logging
import time
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.site_contact_config import SiteContactConfig
from app.models.user import User, UserRole
from app.schemas.support import SupportRequestCreate, SupportRequestResponse
from app.services.email_service import send_support_request_email


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/support", tags=["support"])

_RATE_LIMIT_SECONDS = 60
_recent_requests: dict[str, float] = {}
_rate_limit_lock = Lock()


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


async def _resolve_support_recipient(db: AsyncSession) -> str:
    contact_result = await db.execute(
        select(SiteContactConfig.support_email).where(SiteContactConfig.id == 1)
    )
    support_email = str(contact_result.scalar_one_or_none() or "").strip()
    if support_email:
        return support_email

    result = await db.execute(
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
    admin_email = result.scalar_one_or_none()
    if admin_email:
        return str(admin_email)
    return ""


@router.post(
    "/requests",
    response_model=SupportRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a support request",
)
async def create_support_request(
    body: SupportRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> SupportRequestResponse:
    # A filled honeypot indicates an automated submission. Return a generic
    # success response without forwarding the message.
    if body.website:
        return SupportRequestResponse(message="Support request accepted")

    client_key = request.client.host if request.client else "unknown"
    if not _claim_request_slot(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="support_rate_limited",
        )

    recipient = await _resolve_support_recipient(db)
    if not recipient:
        _release_request_slot(client_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="support_recipient_unavailable",
        )

    try:
        sent = await send_support_request_email(
            to_email=recipient,
            sender_name=body.name,
            sender_email=str(body.email),
            subject=body.subject,
            description=body.description,
            ui_language=body.ui_language,
        )
    except Exception as exc:
        _release_request_slot(client_key)
        logger.error("Support request delivery failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="support_email_unavailable",
        ) from exc

    if not sent:
        _release_request_slot(client_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="support_email_unavailable",
        )

    return SupportRequestResponse(message="Support request sent")
