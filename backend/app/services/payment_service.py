from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.schemas.payment import CreditPackage

CREDIT_PACKAGES: dict[str, CreditPackage] = {
    "basic": CreditPackage(
        name="Basic",
        amount_vnd=50_000,
        credits=5,
        description="5 lượt tạo giáo trình",
    ),
    "standard": CreditPackage(
        name="Standard",
        amount_vnd=100_000,
        credits=12,
        description="12 lượt tạo giáo trình",
    ),
    "premium": CreditPackage(
        name="Premium",
        amount_vnd=200_000,
        credits=30,
        description="30 lượt tạo giáo trình",
    ),
}


def _transfer_content(payment_id: int) -> str:
    return f"TEXTBOOK{payment_id:06d}"


async def create_payment(
    db: AsyncSession, user_id: int, package_id: str
) -> tuple[Payment, float]:
    package = CREDIT_PACKAGES.get(package_id)
    if not package:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid package"
        )

    payment = Payment(
        user_id=user_id,
        amount=package.amount_vnd,
        credits=package.credits,
        status=PaymentStatus.PENDING.value,
    )
    db.add(payment)
    await db.flush()  # Get ID before commit
    payment.transfer_content = _transfer_content(payment.id) #type: ignore
    await db.commit()
    await db.refresh(payment)
    return payment, package.amount_vnd


async def handle_sepay_webhook(
    db: AsyncSession, content: str, amount: float
) -> Optional[Payment]:
    result = await db.execute(
        select(Payment).where(
            Payment.transfer_content == content,
            Payment.status == PaymentStatus.PENDING.value,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return None

    if payment.amount != amount: #type: ignore
        payment.status = PaymentStatus.FAILED.value #type: ignore
        payment.notes = f"Amount mismatch: expected {payment.amount}, got {amount}" #type: ignore
        await db.commit()
        return payment

    payment.status = PaymentStatus.COMPLETED.value #type: ignore
    payment.completed_at = datetime.utcnow() #type: ignore

    user_result = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one_or_none()
    if user:
        user.credits += payment.credits #type: ignore

    await db.commit()
    return payment
