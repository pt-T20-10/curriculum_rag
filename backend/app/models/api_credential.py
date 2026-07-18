from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class UserApiCredential(Base):
    __tablename__ = "user_api_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, index=True)
    encrypted_value = Column(Text, nullable=False)
    last4 = Column(String(8), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_api_credentials_user_provider"),
    )


class TextbookJobSecret(Base):
    __tablename__ = "textbook_job_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    textbook_id = Column(Integer, ForeignKey("textbooks.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, index=True)
    encrypted_value = Column(Text, nullable=False)
    last4 = Column(String(8), nullable=False, default="")
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("textbook_id", "provider", name="uq_textbook_job_secrets_textbook_provider"),
    )
