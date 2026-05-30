"""Benchmark endpoints."""

from fastapi import APIRouter

from app.services import benchmark_service

router = APIRouter(tags=["benchmark"])


@router.post("/run")
async def run_benchmark() -> dict:
    return await benchmark_service.run_benchmark()


@router.get("/reports")
async def list_benchmark_reports() -> list[dict]:
    return await benchmark_service.list_reports()


@router.get("/reports/{report_id}")
async def get_benchmark_report(report_id: str) -> dict:
    return await benchmark_service.get_report(report_id)
