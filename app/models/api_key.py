from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, generate_uuid


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_active_prefix", "is_active", "key_prefix"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_categories: Mapped[str] = mapped_column(Text(), nullable=True)
    notes: Mapped[str] = mapped_column(Text(), nullable=True)
