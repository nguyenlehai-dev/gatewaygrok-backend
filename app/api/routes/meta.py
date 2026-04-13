from sqlalchemy import case, func
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.api.deps import db_session
from app.models.api_key import ApiKey
from app.models.automation_job import AutomationJob, JobStatus
from app.models.profile import Profile, ProfileCategory
from app.models.proxy import Proxy
from app.schemas.meta import CategoryCount, MetaRead, OverviewCount, OverviewRead, ProviderMeta, QueueSummary
from app.services.automation.registry import get_job_statuses, get_job_targets, get_provider_metadata

router = APIRouter()


@router.get("/meta", response_model=MetaRead)
def get_meta():
    return MetaRead(
        categories=[member.value for member in ProfileCategory],
        job_targets=get_job_targets(),
        job_statuses=get_job_statuses(),
        providers=[ProviderMeta(**item) for item in get_provider_metadata()],
    )


@router.get("/overview", response_model=OverviewRead)
def get_overview(db: Session = Depends(db_session)):
    profile_total, profile_active = db.query(
        func.count(Profile.id),
        func.sum(case((Profile.is_active.is_(True), 1), else_=0)),
    ).one()
    proxy_total, proxy_active = db.query(
        func.count(Proxy.id),
        func.sum(case((Proxy.enabled.is_(True), 1), else_=0)),
    ).one()
    api_key_total, api_key_active = db.query(
        func.count(ApiKey.id),
        func.sum(case((ApiKey.is_active.is_(True), 1), else_=0)),
    ).one()

    queue_rows = (
        db.query(AutomationJob.status, func.count(AutomationJob.id))
        .group_by(AutomationJob.status)
        .all()
    )
    queue_map = {status.value if isinstance(status, JobStatus) else status: count for status, count in queue_rows}

    category_rows = (
        db.query(Profile.category, func.count(Profile.id))
        .group_by(Profile.category)
        .all()
    )

    return OverviewRead(
        profiles=OverviewCount(total=profile_total or 0, active=profile_active or 0),
        proxies=OverviewCount(total=proxy_total or 0, active=proxy_active or 0),
        api_keys=OverviewCount(total=api_key_total or 0, active=api_key_active or 0),
        queue=QueueSummary(
            pending=queue_map.get(JobStatus.PENDING.value, 0),
            running=queue_map.get(JobStatus.RUNNING.value, 0),
            succeeded=queue_map.get(JobStatus.SUCCEEDED.value, 0),
            failed=queue_map.get(JobStatus.FAILED.value, 0),
        ),
        categories=[
            CategoryCount(category=category.value if isinstance(category, ProfileCategory) else str(category), total=count)
            for category, count in category_rows
        ],
    )
