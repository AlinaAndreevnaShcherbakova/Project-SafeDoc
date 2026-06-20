from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI

from app.api.document_service_router import router
from app.apps.factory import build_service_app
from app.db.mongo import connect_mongo, disconnect_mongo
from app.services.local_storage_migration import (
    migrate_local_storage_once,
    run_local_storage_migration_loop,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_mongo()
    try:
        await migrate_local_storage_once()
    except Exception:
        pass
    stop_event = asyncio.Event()
    migration_task = asyncio.create_task(run_local_storage_migration_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await migration_task
        await disconnect_mongo()


app = build_service_app(title="SafeDoc DocumentService", router=router, lifespan=lifespan)
