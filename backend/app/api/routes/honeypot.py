"""Honeypot threat intelligence endpoints."""

from fastapi import APIRouter

from app.demo_topology import honeypot

router = APIRouter(tags=["honeypot"])


@router.get("/intel")
async def get_honeypot_intel() -> dict:
    report = honeypot.generate_intel_report()
    return report.model_dump(mode="json")


@router.post("/intel/feed-vector")
async def feed_honeypot_to_vector() -> dict:
    count = honeypot.feed_to_vector_store()
    return {"novel_payloads_fed": count, "session_id": honeypot._session_id}
