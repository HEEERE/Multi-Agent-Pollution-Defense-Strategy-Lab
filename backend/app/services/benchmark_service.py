"""Benchmark business logic — run benchmarks and retrieve reports."""

from app.event_store import get_event_store
from app.benchmark.runner import BenchmarkRunner
from app.llm.factory import get_llm_client


async def run_benchmark() -> dict:
    store = await get_event_store()
    runner = BenchmarkRunner(llm_client=get_llm_client(), event_store=store)
    report = await runner.run()
    await store.store_benchmark_report(report.model_dump(mode="json"))
    return report.model_dump(mode="json")


async def list_reports() -> list[dict]:
    store = await get_event_store()
    reports = await store.get_benchmark_reports()
    return [
        {"report_id": r.get("report_id"), "timestamp": r.get("timestamp"),
         "total_payloads": r.get("total_payloads"), "overall_recall": r.get("overall_recall"),
         "overall_fpr": r.get("overall_fpr")}
        for r in reports
    ]


async def get_report(report_id: str) -> dict | None:
    store = await get_event_store()
    return await store.get_benchmark_report(report_id)
