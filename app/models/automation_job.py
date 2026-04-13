import enum

from sqlalchemy import Enum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, generate_uuid


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobTarget(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class AutomationJob(Base, TimestampMixin):
    __tablename__ = "automation_jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_profile_status", "profile_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    target: Mapped[JobTarget] = mapped_column(Enum(JobTarget), nullable=False)
    prompt: Mapped[str] = mapped_column(Text(), nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text(), nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    provider_payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str] = mapped_column(Text(), nullable=True)

    profile = relationship("Profile", back_populates="jobs")
