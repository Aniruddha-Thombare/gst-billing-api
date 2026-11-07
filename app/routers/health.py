from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import health_service

# No /api/v1 prefix: load balancers and Docker probe fixed, unversioned paths.
router = APIRouter(tags=["System"])


@router.get("/health", summary="Liveness: the process is up")
async def health() -> dict[str, str]:
    """Never touches the database, so a slow DB cannot make the container look dead and restart-loop."""
    return {"status": "ok", "env": settings.ENVIRONMENT}


@router.get("/ready", summary="Readiness: the app can serve traffic")
async def ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    checks = await health_service.check_readiness(db)
    all_ok = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
    )
