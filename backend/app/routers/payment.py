from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.payment import Payment
from app.schemas.payment import CreditPackage, PaymentCreate, PaymentResponse, SePayWebhook
from app.security.jwt import get_current_user_id
from app.services.payment_service import (
    CREDIT_PACKAGES,
    create_payment,
    handle_sepay_webhook,
)
from app.config import settings

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/packages", response_model=dict[str, CreditPackage])
async def list_packages():
    return CREDIT_PACKAGES


@router.post("/create", response_model=dict)
async def initiate_payment(
    payload: PaymentCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    payment, amount_vnd = await create_payment(db, user_id, payload.package_id)
    return {
        "payment_id": payment.id,
        "amount_vnd": amount_vnd,
        "transfer_content": payment.transfer_content,
        "bank_account": settings.SEPAY_ACCOUNT_NUMBER,
    }


@router.post("/webhook/sepay")
async def sepay_webhook(payload: SePayWebhook, db: AsyncSession = Depends(get_async_db)):
    payment = await handle_sepay_webhook(db, payload.content, payload.transferAmount)
    if not payment:
        return {"status": "ignored"}
    return {"status": "ok", "payment_id": payment.id}


@router.get("/history", response_model=List[PaymentResponse])
async def payment_history(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
    )
    return result.scalars().all()
