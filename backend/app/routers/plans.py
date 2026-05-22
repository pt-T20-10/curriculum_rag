"""
Public plans + bank-config endpoints (no auth required).
"""

import random
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.bank_config import BankConfig
from app.models.plan import Plan
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.security.jwt import get_current_user_id

router = APIRouter()


def _plan_to_dict(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "name": plan.name,
        "price_vnd": plan.price_vnd,
        "credits": plan.credits,
        "features": [f.strip() for f in (plan.features or "").splitlines() if f.strip()],
        "is_recommended": plan.is_recommended,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
    }


def _generate_txn_id() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ---------------------------------------------------------------------------
# GET /plans — active plans list (public)
# ---------------------------------------------------------------------------

@router.get("/plans")
async def list_active_plans(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order, Plan.id)
    )
    plans = result.scalars().all()
    return [_plan_to_dict(p) for p in plans]


# ---------------------------------------------------------------------------
# GET /plans/bank-config — bank config for QR modal (public)
# ---------------------------------------------------------------------------

@router.get("/plans/bank-config")
async def get_bank_config(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(BankConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {
            "bank_name": "Vietcombank",
            "bank_id": "vietcombank",
            "account_number": "9782832044",
            "account_holder": "",
        }
    return {
        "bank_name": cfg.bank_name,
        "bank_id": cfg.bank_id,
        "account_number": cfg.account_number,
        "account_holder": cfg.account_holder,
    }


# ---------------------------------------------------------------------------
# GET /user/credits — current user balance
# ---------------------------------------------------------------------------

@router.get("/user/credits")
async def get_user_credits(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"credits": user.credits, "user_id": user_id}


# ---------------------------------------------------------------------------
# POST /transactions — create pending transaction (auth required)
# ---------------------------------------------------------------------------

@router.post("/transactions", status_code=201)
async def create_transaction(
    body: dict,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    plan_id = body.get("plan_id")
    if not plan_id:
        raise HTTPException(status_code=422, detail="plan_id is required")

    result = await db.execute(select(Plan).where(Plan.id == plan_id, Plan.is_active == True))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Generate a unique TXN ID (retry if collision)
    for _ in range(10):
        txn_id = _generate_txn_id()
        existing = await db.execute(select(Transaction).where(Transaction.txn_id == txn_id))
        if not existing.scalar_one_or_none():
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique transaction ID")

    transfer_content = f"AATG U{user_id} {txn_id}"

    txn = Transaction(
        user_id=user_id,
        plan_id=plan.id,
        amount_vnd=plan.price_vnd,
        credits=plan.credits,
        txn_id=txn_id,
        transfer_content=transfer_content,
        status=TransactionStatus.PENDING,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    return {
        "id": txn.id,
        "plan_id": txn.plan_id,
        "plan_name": plan.name,
        "amount_vnd": txn.amount_vnd,
        "credits": txn.credits,
        "txn_id": txn.txn_id,
        "transfer_content": txn.transfer_content,
        "status": txn.status,
        "created_at": txn.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /user/transactions — user's transaction history
# ---------------------------------------------------------------------------

@router.get("/user/transactions")
async def list_user_transactions(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
    )
    txns = result.scalars().all()

    # Fetch plan names
    plan_ids = list({t.plan_id for t in txns})
    plan_map: dict[int, Plan] = {}
    if plan_ids:
        plan_result = await db.execute(select(Plan).where(Plan.id.in_(plan_ids)))
        for p in plan_result.scalars().all():
            plan_map[p.id] = p

    return [
        {
            "id": t.id,
            "plan_id": t.plan_id,
            "plan_name": plan_map[t.plan_id].name if t.plan_id in plan_map else "Unknown",
            "amount_vnd": t.amount_vnd,
            "credits": t.credits,
            "txn_id": t.txn_id,
            "transfer_content": t.transfer_content,
            "status": t.status,
            "reject_reason": t.reject_reason,
            "created_at": t.created_at.isoformat(),
            "confirmed_at": t.confirmed_at.isoformat() if t.confirmed_at else None,
        }
        for t in txns
    ]
