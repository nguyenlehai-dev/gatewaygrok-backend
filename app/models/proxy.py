from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, generate_uuid


class Proxy(Base, TimestampMixin):
    __tablename__ = "proxies"
    __table_args__ = (
        Index("ix_proxies_enabled_kind", "enabled", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    server: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=True)
    password: Mapped[str] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="http")
    country: Mapped[str] = mapped_column(String(16), nullable=True)
    sticky_session: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    profiles = relationship("Profile", back_populates="proxy")
