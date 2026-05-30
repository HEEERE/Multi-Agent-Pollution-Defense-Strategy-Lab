"""Settings business logic — CRUD with pipeline rebuild hooks."""

from app.settings_manager import VALID_CATEGORIES, get_settings_manager


async def get_all() -> dict:
    mgr = get_settings_manager()
    categories = await mgr.get_all()
    updated_at = await mgr.get_last_updated()
    return {"categories": categories, "updated_at": updated_at}


async def get_category(category: str) -> dict:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    mgr = get_settings_manager()
    values = await mgr.get_category(category)
    return {"category": category, "values": values}


async def update_category(category: str, payload: dict) -> dict:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    mgr = get_settings_manager()
    updated = await mgr.update_category(category, payload)
    if category == "llm":
        from app.llm.factory import get_llm_client_manager
        get_llm_client_manager().invalidate()
    if category in ("detectors", "llm"):
        from app.demo_topology import rebuild_runtime_pipeline
        rebuild_runtime_pipeline()
    return {"status": "saved", "category": category, "updated": updated}


async def reset_category(category: str) -> dict:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    mgr = get_settings_manager()
    values = await mgr.reset_category(category)
    if category == "llm":
        from app.llm.factory import get_llm_client_manager
        get_llm_client_manager().invalidate()
    if category in ("detectors", "llm"):
        from app.demo_topology import rebuild_runtime_pipeline
        rebuild_runtime_pipeline()
    return {"category": category, "values": values}
