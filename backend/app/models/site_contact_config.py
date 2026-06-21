from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteContactConfig(Base):
    __tablename__ = "site_contact_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, autoincrement=False)
    service_name_vi: Mapped[str] = mapped_column(String(200), nullable=False)
    service_name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    address_vi: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    support_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    privacy_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    support_hours_vi: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    support_hours_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    response_time_vi: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_time_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
