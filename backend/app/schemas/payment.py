from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CreditPackage(BaseModel):
    name: str
    amount_vnd: float
    credits: int
    description: str


class PaymentCreate(BaseModel):
    package_id: str


class PaymentResponse(BaseModel):
    id: int
    amount: float
    credits: int
    status: str
    transfer_content: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SePayWebhook(BaseModel):
    id: int
    gateway: str
    transactionDate: str
    accountNumber: str
    subAccount: Optional[str] = None
    code: Optional[str] = None
    content: str
    transferType: str
    description: Optional[str] = None
    transferAmount: float
    referenceCode: Optional[str] = None
    accumulated: Optional[float] = None
