from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from ...core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
    }
