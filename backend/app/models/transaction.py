from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class TransactionStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    amount_vnd = Column(Integer, nullable=False)
    credits = Column(Integer, nullable=False)
    txn_id = Column(String(10), nullable=False, unique=True, index=True)  # random 6-char
    transfer_content = Column(String(200), nullable=False, index=True)
    status = Column(String(20), default=TransactionStatus.PENDING, nullable=False, index=True)
    reject_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by = Column(Integer, nullable=True)  # admin user_id
