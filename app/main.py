from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import init_db
from app.services.job_runner import job_runner


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await job_runner.start()
    try:
        yield
    finally:
        await job_runner.stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.mount("/storage", StaticFiles(directory=str(settings.storage_root)), name="storage")
