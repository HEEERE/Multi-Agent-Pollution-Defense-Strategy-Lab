import json
from time import time

from fastapi import HTTPException

from app.event_store import get_event_store
from app.schemas import (
    StrategyCreate,
    StrategyRead,
    StrategyUpdate,
    StrategyValidationResult,
    new_id,
)
from app.strategy.validator import validate_strategy


async def create_strategy(data: StrategyCreate) -> StrategyRead:
    result = validate_strategy(data.content)
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail=[i.model_dump(mode="json") for i in result.issues],
        )

    store = await get_event_store()
    now = time()
    strategy_id = new_id()

    strategy = {
        "strategy_id": strategy_id,
        "name": data.name,
        "description": data.description,
        "format": data.format,
        "content_json": json.dumps(data.content, ensure_ascii=False),
        "tags_json": json.dumps(data.tags, ensure_ascii=False),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    await store.store_strategy(strategy)
    await store.store_strategy_version(
        {
            "version_id": new_id(),
            "strategy_id": strategy_id,
            "version": 1,
            "content_json": strategy["content_json"],
            "created_at": now,
        }
    )

    return StrategyRead(
        strategy_id=strategy_id,
        name=data.name,
        description=data.description,
        format=data.format,
        content=data.content,
        tags=data.tags,
        version=1,
        created_at=now,
        updated_at=now,
    )


async def get_strategy(strategy_id: str) -> StrategyRead:
    store = await get_event_store()
    row = await store.get_strategy(strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return _row_to_read(row)


async def list_strategies(limit: int = 50, offset: int = 0) -> list[StrategyRead]:
    store = await get_event_store()
    rows = await store.list_strategies(limit=limit, offset=offset)
    return [_row_to_read(r) for r in rows]


async def update_strategy(
    strategy_id: str, data: StrategyUpdate
) -> StrategyRead:
    store = await get_event_store()
    existing = await store.get_strategy(strategy_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="strategy not found")

    now = time()
    updates: dict = {"updated_at": now}

    if data.name is not None:
        updates["name"] = data.name
    if data.description is not None:
        updates["description"] = data.description
    if data.tags is not None:
        updates["tags_json"] = json.dumps(data.tags, ensure_ascii=False)
    if data.content is not None:
        result = validate_strategy(data.content)
        if not result.valid:
            raise HTTPException(
                status_code=422,
                detail=[i.model_dump(mode="json") for i in result.issues],
            )
        updates["content_json"] = json.dumps(data.content, ensure_ascii=False)
        new_version = existing["version"] + 1
        updates["version"] = new_version
        await store.store_strategy_version(
            {
                "version_id": new_id(),
                "strategy_id": strategy_id,
                "version": new_version,
                "content_json": updates["content_json"],
                "created_at": now,
            }
        )

    if updates:
        await store.update_strategy(strategy_id, updates)

    updated = await store.get_strategy(strategy_id)
    return _row_to_read(updated)


async def delete_strategy(strategy_id: str) -> dict:
    store = await get_event_store()
    count = await store.delete_strategy(strategy_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="strategy not found")
    return {"deleted": count, "strategy_id": strategy_id}


async def validate_strategy_content(content: dict) -> StrategyValidationResult:
    return validate_strategy(content)


async def run_strategy(strategy_id: str) -> dict:
    from app.services.run_service import create_run_from_strategy

    store = await get_event_store()
    strategy = await store.get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    run = await create_run_from_strategy(strategy)
    return {"run_id": run.run_id, "status": run.status.value}


def _row_to_read(row: dict) -> StrategyRead:
    content = {}
    if row.get("content_json"):
        try:
            content = json.loads(row["content_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    tags = []
    if row.get("tags_json"):
        try:
            tags = json.loads(row["tags_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return StrategyRead(
        strategy_id=row["strategy_id"],
        name=row["name"],
        description=row.get("description", ""),
        format=row.get("format", "json"),
        content=content,
        tags=tags,
        version=row.get("version", 1),
        created_at=row.get("created_at", 0),
        updated_at=row.get("updated_at", 0),
    )
