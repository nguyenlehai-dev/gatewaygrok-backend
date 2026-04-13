from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.api.routes import api_keys, auth, client, health, jobs, meta, profiles, proxies, settings

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(meta.router, tags=["meta"], dependencies=[Depends(require_admin)])
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"], dependencies=[Depends(require_admin)])
api_router.include_router(proxies.router, prefix="/proxies", tags=["proxies"], dependencies=[Depends(require_admin)])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"], dependencies=[Depends(require_admin)])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_admin)])
api_router.include_router(client.router, prefix="/client", tags=["client"])
