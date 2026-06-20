import asyncio

from app.core.config import settings
from app.db import mongo
from app.db.mongo import connect_mongo
from app.services.audit import audit_service


async def _ensure_mongo_available() -> bool:
    if mongo.logs_bucket is not None:
        try:
            await mongo.client.admin.command("ping")  # type: ignore[union-attr]
            return True
        except Exception:
            await mongo.disconnect_mongo()
    await connect_mongo()
    return mongo.logs_bucket is not None


async def archive_pending_audit_logs_once() -> int:
    if not await _ensure_mongo_available():
        return 0
    return await audit_service.archive_pending_logs()


async def run_audit_log_archive_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await archive_pending_audit_logs_once()
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.audit_log_archive_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass
