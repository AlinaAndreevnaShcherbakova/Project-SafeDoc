from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI

from app.api.audit_service_router import router
from app.apps.factory import build_service_app
from app.db.mongo import connect_mongo, disconnect_mongo
from app.services.audit_log_archiver import (
    archive_pending_audit_logs_once,
    run_audit_log_archive_loop,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_mongo()
    try:
        await archive_pending_audit_logs_once()
    except Exception:
        pass
    stop_event = asyncio.Event()
    archive_task = asyncio.create_task(run_audit_log_archive_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await archive_task
        await disconnect_mongo()


app = build_service_app(title="SafeDoc AuditService", router=router, lifespan=lifespan)
