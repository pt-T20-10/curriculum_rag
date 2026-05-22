"""
Admin API — requires role='admin' and is_locked=False.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.bank_config import BankConfig
from app.models.credit_history import CreditHistory
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.models.textbook import Textbook, TextbookStatus
from app.models.transaction import Transaction, TransactionStatus
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


# ---------------------------------------------------------------------------
# Bank config
# ---------------------------------------------------------------------------

class BankConfigUpdate(BaseModel):
    bank_name: str
    bank_id: str
    account_number: str
    account_holder: str


@router.get("/bank-config")
async def admin_get_bank_config(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    result = await db.execute(select(BankConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {"bank_name": "Vietcombank", "bank_id": "vietcombank", "account_number": "9782832044", "account_holder": ""}
    return {"bank_name": cfg.bank_name, "bank_id": cfg.bank_id, "account_number": cfg.account_number, "account_holder": cfg.account_holder}


@router.put("/bank-config")
async def admin_update_bank_config(
    body: BankConfigUpdate,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    result = await db.execute(select(BankConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = BankConfig()
        db.add(cfg)
    cfg.bank_name = body.bank_name  # type: ignore
    cfg.bank_id = body.bank_id  # type: ignore
    cfg.account_number = body.account_number  # type: ignore
    cfg.account_holder = body.account_holder  # type: ignore
    await db.commit()
    return {"message": "Bank config updated"}


# ---------------------------------------------------------------------------
# Plans management
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    name: str
    price_vnd: int
    credits: int
    features: Optional[str] = ""
    is_recommended: bool = False
    is_active: bool = True
    sort_order: int = 0


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    price_vnd: Optional[int] = None
    credits: Optional[int] = None
    features: Optional[str] = None
    is_recommended: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


def _plan_dict(p: Plan) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "price_vnd": p.price_vnd,
        "credits": p.credits,
        "features": p.features or "",
        "is_recommended": p.is_recommended,
        "is_active": p.is_active,
        "sort_order": p.sort_order,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.get("/plans")
async def admin_list_plans(
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    result = await db.execute(select(Plan).order_by(Plan.sort_order, Plan.id))
    return [_plan_dict(p) for p in result.scalars().all()]


@router.post("/plans", status_code=201)
async def admin_create_plan(
    body: PlanCreate,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    plan = Plan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.put("/plans/{plan_id}")
async def admin_update_plan(
    plan_id: int,
    body: PlanUpdate,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.delete("/plans/{plan_id}", status_code=200)
async def admin_delete_plan(
    plan_id: int,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.is_active = False  # type: ignore
    await db.commit()
    return {"message": "Plan deactivated"}


# ---------------------------------------------------------------------------
# Transactions management (admin)
# ---------------------------------------------------------------------------

def _txn_dict(t: Transaction, user: Optional[User], plan: Optional[Plan]) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "user_email": user.email if user else None,
        "user_name": user.full_name if user else None,
        "plan_id": t.plan_id,
        "plan_name": plan.name if plan else None,
        "amount_vnd": t.amount_vnd,
        "credits": t.credits,
        "txn_id": t.txn_id,
        "transfer_content": t.transfer_content,
        "status": t.status,
        "reject_reason": t.reject_reason,
        "created_at": t.created_at.isoformat(),
        "confirmed_at": t.confirmed_at.isoformat() if t.confirmed_at else None,
        "confirmed_by": t.confirmed_by,
    }


@router.get("/transactions")
async def admin_list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    query = select(Transaction)
    if status_filter:
        query = query.where(Transaction.status == status_filter)

    query = query.order_by(
        (Transaction.status == TransactionStatus.PENDING).desc(),
        Transaction.created_at.desc(),
    )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    txns = result.scalars().all()

    user_ids = list({t.user_id for t in txns})
    plan_ids = list({t.plan_id for t in txns})
    user_map: dict[int, User] = {}
    plan_map: dict[int, Plan] = {}
    if user_ids:
        ur = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in ur.scalars().all():
            user_map[u.id] = u  # type: ignore
    if plan_ids:
        pr = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
        for p in pr.scalars().all():
            plan_map[p.id] = p  # type: ignore

    items = [_txn_dict(t, user_map.get(t.user_id), plan_map.get(t.plan_id)) for t in txns]  # type: ignore
    return {"items": items, "total": total, "page": page, "page_size": page_size}


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/transactions/{txn_id}/confirm")
async def admin_confirm_transaction(
    txn_id: int,
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status != TransactionStatus.PENDING:  # type: ignore
        raise HTTPException(status_code=400, detail=f"Transaction is already {txn.status}")

    user_result = await db.execute(select(User).where(User.id == txn.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        txn.status = TransactionStatus.CONFIRMED  # type: ignore
        txn.confirmed_at = datetime.utcnow()  # type: ignore
        txn.confirmed_by = admin_id  # type: ignore

        user.credits = (user.credits or 0) + txn.credits  # type: ignore

        history = CreditHistory(
            user_id=user.id,
            delta=txn.credits,
            reason=f"Top-up via transaction #{txn.id}",
            balance_after=user.credits,
        )
        db.add(history)
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to confirm transaction")

    return {"message": "Transaction confirmed, credits added", "new_balance": user.credits}


@router.post("/transactions/{txn_id}/reject")
async def admin_reject_transaction(
    txn_id: int,
    body: RejectRequest = RejectRequest(),
    admin_id: int = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await _get_admin_user(db, admin_id)

    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status != TransactionStatus.PENDING:  # type: ignore
        raise HTTPException(status_code=400, detail=f"Transaction is already {txn.status}")

    txn.status = TransactionStatus.REJECTED  # type: ignore
    txn.reject_reason = body.reason  # type: ignore
    await db.commit()

    return {"message": "Transaction rejected"}
