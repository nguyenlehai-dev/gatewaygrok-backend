import enum
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, generate_uuid


class ProfileCategory(str, enum.Enum):
    GROK = "grok"
    FLOW = "flow"
    DREAMINA = "dreamina"


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"
    __table_args__ = (
        Index("ix_profiles_category_active", "category", "is_active"),
        Index("ix_profiles_proxy_id", "proxy_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    category: Mapped[ProfileCategory] = mapped_column(Enum(ProfileCategory), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    proxy_id: Mapped[str] = mapped_column(String(36), ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True)
    cookie_file: Mapped[str] = mapped_column(String(255), nullable=True)
    cache_dir: Mapped[str] = mapped_column(String(255), nullable=False)
    user_data_dir: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=True)
    antidetect: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    proxy = relationship("Proxy", back_populates="profiles")
    jobs = relationship("AutomationJob", back_populates="profile", cascade="all, delete-orphan")
