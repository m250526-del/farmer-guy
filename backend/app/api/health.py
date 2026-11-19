from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check() -> dict:
    """
    Liveness check. Returns the project name and current environment.
    Used by the mobile app to verify backend connectivity.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }

