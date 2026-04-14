import asyncio

from sqlalchemy.orm import joinedload

from app.db.session import SessionLocal
from app.models.automation_job import AutomationJob, JobStatus
from app.models.profile import Profile
from app.schemas.setting import AutomationSettings
from app.services.automation.registry import providers
from app.services.settings_service import settings_service


class JobRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.global_concurrency = 1
        self.profile_semaphores: dict[str, asyncio.Semaphore] = {}
        self.profile_limits: dict[str, int] = {}
        self.running = False

    async def start(self) -> None:
        if self.running:
            return
        with SessionLocal() as db:
            settings = settings_service.get_settings(db)
            self.global_concurrency = settings.automation.concurrency
        self.running = True
        self._spawn_workers()
        await self.bootstrap_pending_jobs()

    def _spawn_workers(self) -> None:
        for index in range(self.global_concurrency):
            self.workers.append(asyncio.create_task(self._worker(index)))

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def set_concurrency(self, concurrency: int) -> None:
        await self.stop()
        self.global_concurrency = concurrency
        self.running = True
        self._spawn_workers()

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def bootstrap_pending_jobs(self) -> None:
        with SessionLocal() as db:
            jobs = (
                db.query(AutomationJob)
                .filter(AutomationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
                .order_by(AutomationJob.created_at.asc())
                .all()
            )
            for job in jobs:
                job.status = JobStatus.PENDING
            db.commit()
            job_ids = [job.id for job in jobs]

        for job_id in job_ids:
            await self.enqueue(job_id)

    def _profile_semaphore(self, profile: Profile) -> asyncio.Semaphore:
        existing = self.profile_semaphores.get(profile.id)
        limit = max(profile.concurrency_limit, 1)
        if existing is None or self.profile_limits.get(profile.id) != limit:
            self.profile_semaphores[profile.id] = asyncio.Semaphore(limit)
            self.profile_limits[profile.id] = limit
        return self.profile_semaphores[profile.id]

    async def _worker(self, worker_index: int) -> None:
        del worker_index
        while True:
            job_id = await self.queue.get()
            try:
                await self._process(job_id)
            finally:
                self.queue.task_done()

    async def _process(self, job_id: str) -> None:
        with SessionLocal() as db:
            job = (
                db.query(AutomationJob)
                .options(joinedload(AutomationJob.profile).joinedload(Profile.proxy))
                .filter(AutomationJob.id == job_id)
                .first()
            )
            if not job or not job.profile:
                return

            profile = job.profile
            semaphore = self._profile_semaphore(profile)
            automation_settings = settings_service.get_settings(db).automation
            provider = providers.get(profile.category)
            if provider is None:
                job.status = JobStatus.FAILED
                job.error_message = f"Provider not implemented for category {profile.category.value}"
                db.commit()
                return

            job.status = JobStatus.RUNNING
            db.commit()

            async with semaphore:
                try:
                    timeout_seconds = max(120, int(automation_settings.timeout_ms / 1000) * 2)
                    result = await asyncio.wait_for(
                        provider.run(profile, profile.proxy, job, automation_settings),
                        timeout=timeout_seconds,
                    )
                    if job.target.value in {"image", "video"} and not result.get("media_urls"):
                        raise RuntimeError(f"No media output captured for {job.target.value} job")
                    job.status = JobStatus.SUCCEEDED
                    job.result_payload = result
                    job.error_message = None
                except TimeoutError:
                    job.status = JobStatus.FAILED
                    job.error_message = f"Automation timed out after {timeout_seconds}s"
                except Exception as exc:  # noqa: BLE001
                    job.status = JobStatus.FAILED
                    job.error_message = str(exc)
                db.add(job)
                db.commit()


job_runner = JobRunner()
