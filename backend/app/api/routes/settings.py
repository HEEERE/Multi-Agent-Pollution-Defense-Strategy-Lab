"""Settings CRUD endpoints."""

from fastapi import APIRouter, Body, HTTPException

from app.services import settings_service

router = APIRouter(tags=["settings"])


@router.get("")
async def get_all_settings() -> dict:
    return await settings_service.get_all()


@router.get("/{category}")
async def get_settings_category(category: str) -> dict:
    try:
        return await settings_service.get_category(category)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{category}")
async def update_settings_category(category: str, payload: dict = Body(...)) -> dict:
    try:
        return await settings_service.update_category(category, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{category}/reset")
async def reset_settings_category(category: str) -> dict:
    try:
        return await settings_service.reset_category(category)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
