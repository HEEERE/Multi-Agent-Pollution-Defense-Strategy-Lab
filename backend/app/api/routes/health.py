"""Health and platform config endpoints."""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "multi-agent-pollution-defense-platform"}


@router.get("/api/platform/config")
async def platform_config() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "llm_provider": "mimo",
        "llm_base_url": str(settings.mimo_base_url),
        "llm_model": settings.mimo_model,
        "llm_enabled": settings.llm_enabled,
        "llm_ready": settings.llm_ready,
        "auth_enabled": settings.auth_enabled,
    }
