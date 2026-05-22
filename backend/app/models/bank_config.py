from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class BankConfig(Base):
    __tablename__ = "bank_config"

    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String(100), nullable=False, default="Vietcombank")
    bank_id = Column(String(50), nullable=False, default="vietcombank")  # VietQR bank ID
    account_number = Column(String(50), nullable=False, default="9782832044")
    account_holder = Column(String(200), nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
