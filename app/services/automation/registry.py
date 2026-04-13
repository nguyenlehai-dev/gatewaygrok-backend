from app.models.automation_job import JobStatus, JobTarget
from app.models.profile import ProfileCategory
from app.services.automation.dreamina import dreamina_provider
from app.services.automation.flow import flow_provider
from app.services.automation.grok import grok_provider


providers = {
    ProfileCategory.GROK: grok_provider,
    ProfileCategory.FLOW: flow_provider,
    ProfileCategory.DREAMINA: dreamina_provider,
}


def get_provider(category: ProfileCategory):
    return providers.get(category)


def get_provider_metadata() -> list[dict]:
    return [
        providers[category].capability_payload(category.value)
        for category in (ProfileCategory.GROK, ProfileCategory.FLOW, ProfileCategory.DREAMINA)
    ]


def get_job_targets() -> list[str]:
    return [member.value for member in JobTarget]


def get_job_statuses() -> list[str]:
    return [member.value for member in JobStatus]
