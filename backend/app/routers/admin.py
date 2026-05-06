"""
Admin API — requires role='admin' and is_locked=False.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.payment import Payment, PaymentStatus
from app.models.textbook import Textbook, TextbookStatus
from app.models.user import User, UserRole
from app.security.jwt import require_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper — load & verify admin from DB
# ---------------------------------------------------------------------------

async def _get_admin_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.role != UserRole.ADMIN.value: #type: ignore
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if user.is_locked: #type: ignore
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is locked")
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AdminUserItem(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    is_active: bool
    is_locked: bool
    locked_at: Optional[datetime]
    credits: int
    auth_provider: str
    created_at: datetime
    textbook_count: int = 0

    class Config:
        from_attributes = True


class AdminTextbookItem(BaseModel):
    id: int
    title: str
    topic: str
    status: str
    num_chapters: int
    content_level: str
    credits_used: int
    created_at: datetime
    completed_at: Optional[datetime]
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None

    class Config:
        from_attributes = True


class LockRequest(BaseModel):
    reason: Optional[str] = None


class StatsOverview(BaseModel):
    total_users: int
    total_textbooks: int
    textbooks_this_month: int
    active_users: int
    completed_textbooks: int
    failed_textbooks: int
    total_revenue: float
    revenue_this_month: float
    total_credits_sold: int
    pending_payments: int


# ---------------------------------------------------------------------------
# Stats endpoints
# ---------------------------------------------------------------------------

@router.get("/stats/overview", response_model=StatsOverview)
async def get_stats_overview(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_textbooks = (await db.execute(select(func.count(Textbook.id)))).scalar_one()

    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    textbooks_this_month = (
        await db.execute(
            select(func.count(Textbook.id)).where(Textbook.created_at >= month_start)
        )
    ).scalar_one()

    active_users = (
        await db.execute(select(func.count(User.id)).where(User.is_active == True))
    ).scalar_one()

    completed_textbooks = (
        await db.execute(
            select(func.count(Textbook.id)).where(
                Textbook.status == TextbookStatus.COMPLETED.value
            )
        )
    ).scalar_one()

    failed_textbooks = (
        await db.execute(
            select(func.count(Textbook.id)).where(
                Textbook.status == TextbookStatus.FAILED.value
            )
        )
    ).scalar_one()

    total_revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.COMPLETED.value
            )
        )
    ).scalar_one()

    revenue_this_month = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.COMPLETED.value,
                Payment.completed_at >= month_start,
            )
        )
    ).scalar_one()

    total_credits_sold = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.credits), 0)).where(
                Payment.status == PaymentStatus.COMPLETED.value
            )
        )
    ).scalar_one()

    pending_payments = (
        await db.execute(
            select(func.count(Payment.id)).where(
                Payment.status == PaymentStatus.PENDING.value
            )
        )
    ).scalar_one()

    return StatsOverview(
        total_users=total_users,
        total_textbooks=total_textbooks,
        textbooks_this_month=textbooks_this_month,
        active_users=active_users,
        completed_textbooks=completed_textbooks,
        failed_textbooks=failed_textbooks,
        total_revenue=float(total_revenue),
        revenue_this_month=float(revenue_this_month),
        total_credits_sold=int(total_credits_sold),
        pending_payments=int(pending_payments),
    )


@router.get("/stats/generation-trends")
async def get_generation_trends(
    days: int = Query(30, ge=1, le=90),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Returns daily textbook creation counts for the last N days."""
    await _get_admin_user(db, admin_id)

    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(Textbook.created_at).label("date"),
            func.count(Textbook.id).label("count"),
        )
        .where(Textbook.created_at >= cutoff)
        .group_by(func.date(Textbook.created_at))
        .order_by(func.date(Textbook.created_at))
    )
    rows = result.all()
    return [{"date": str(r.date), "count": r.count} for r in rows]


@router.get("/stats/top-topics")
async def get_top_topics(
    limit: int = Query(5, ge=1, le=20),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    result = await db.execute(
        select(Textbook.topic, func.count(Textbook.id).label("count"))
        .group_by(Textbook.topic)
        .order_by(func.count(Textbook.id).desc())
        .limit(limit)
    )
    rows = result.all()
    return [{"topic": r.topic, "count": r.count} for r in rows]


@router.get("/stats/payment-trends")
async def get_payment_trends(
    days: int = Query(30, ge=1, le=90),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Returns daily completed payment revenue for the last N days."""
    await _get_admin_user(db, admin_id)

    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(Payment.completed_at).label("date"),
            func.coalesce(func.sum(Payment.amount), 0).label("revenue"),
            func.count(Payment.id).label("count"),
        )
        .where(
            Payment.status == PaymentStatus.COMPLETED.value,
            Payment.completed_at >= cutoff,
        )
        .group_by(func.date(Payment.completed_at))
        .order_by(func.date(Payment.completed_at))
    )
    rows = result.all()
    return [{"date": str(r.date), "revenue": float(r.revenue), "count": r.count} for r in rows]


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_locked: Optional[bool] = Query(None),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    query = select(User)
    if search:
        like = f"%{search}%"
        query = query.where(
            (User.email.like(like)) | (User.full_name.like(like))
        )
    if role:
        query = query.where(User.role == role)
    if is_locked is not None:
        query = query.where(User.is_locked == is_locked)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

    query = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    users = result.scalars().all()

    # Fetch textbook counts in one query
    user_ids = [u.id for u in users]
    counts: dict[int, int] = {}
    if user_ids:
        cnt_result = await db.execute(
            select(Textbook.user_id, func.count(Textbook.id).label("cnt"))
            .where(Textbook.user_id.in_(user_ids))
            .group_by(Textbook.user_id)
        )
        counts = {row.user_id: row.cnt for row in cnt_result.all()}

    items = [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "avatar_url": u.avatar_url,
            "role": u.role,
            "is_active": u.is_active,
            "is_locked": u.is_locked,
            "locked_at": u.locked_at.isoformat() if u.locked_at else None, #type: ignore
            "credits": u.credits,
            "auth_provider": u.auth_provider,
            "created_at": u.created_at.isoformat(),
            "textbook_count": counts.get(u.id, 0), #type: ignore
        }
        for u in users
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/users/{user_id}/lock", status_code=200)
async def lock_user(
    user_id: int,
    body: LockRequest = LockRequest(),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    admin = await _get_admin_user(db, admin_id)

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id: #type: ignore
        raise HTTPException(status_code=400, detail="Cannot lock your own account")
    if target.role == UserRole.ADMIN.value: #type: ignore
        raise HTTPException(status_code=400, detail="Cannot lock another admin")

    target.is_locked = True #type: ignore
    target.locked_at = datetime.utcnow() #type: ignore
    target.locked_by = admin_id #type: ignore
    await db.commit()

    return {"message": f"User {target.email} locked successfully"}


@router.post("/users/{user_id}/unlock", status_code=200)
async def unlock_user(
    user_id: int,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_locked = False #type: ignore
    target.locked_at = None #type: ignore
    target.locked_by = None #type: ignore
    await db.commit()

    return {"message": f"User {target.email} unlocked successfully"}


@router.put("/users/{user_id}/role", status_code=200)
async def change_user_role(
    user_id: int,
    role: str = Query(..., regex="^(user|admin)$"),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    admin = await _get_admin_user(db, admin_id)

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id: #type: ignore
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    target.role = role #type: ignore
    await db.commit()

    return {"message": f"User {target.email} role changed to {role}"}


# ---------------------------------------------------------------------------
# Textbook management
# ---------------------------------------------------------------------------

@router.get("/textbooks")
async def list_textbooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    query = select(Textbook)
    if search:
        like = f"%{search}%"
        query = query.where(
            (Textbook.title.like(like)) | (Textbook.topic.like(like))
        )
    if status_filter:
        query = query.where(Textbook.status == status_filter)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

    query = query.order_by(Textbook.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    textbooks = result.scalars().all()

    # Fetch owners
    owner_ids = list({t.user_id for t in textbooks})
    owner_map: dict[int, User] = {}
    if owner_ids:
        owner_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
        for u in owner_result.scalars().all():
            owner_map[u.id] = u #type: ignore

    items = [
        {
            "id": t.id,
            "title": t.title,
            "topic": t.topic,
            "status": t.status,
            "num_chapters": t.num_chapters,
            "content_level": t.content_level,
            "credits_used": t.credits_used,
            "created_at": t.created_at.isoformat(),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None, #type: ignore
            "owner_email": owner_map[t.user_id].email if t.user_id in owner_map  else None, #type: ignore
            "owner_name": owner_map[t.user_id].full_name if t.user_id in owner_map else None, #type: ignore
        }
        for t in textbooks
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}
