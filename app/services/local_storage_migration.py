import asyncio
from pathlib import Path

from sqlalchemy import select, update

from app.core.config import settings
from app.db import mongo
from app.db.mongo import connect_mongo
from app.db.postgres import SessionLocal
from app.models import Document, DocumentVersion
from app.services.storage import storage_service


LOCAL_STORAGE_PREFIX = "local://"


def _filename_from_storage_key(storage_key: str) -> str:
    name = Path(storage_key.replace(LOCAL_STORAGE_PREFIX, "")).name
    if name.startswith("local-"):
        parts = name.split("-", maxsplit=2)
        if len(parts) == 3:
            return parts[2] or "migrated.bin"
    return name or "migrated.bin"


async def _ensure_mongo_available() -> bool:
    if mongo.files_bucket is not None:
        try:
            await mongo.client.admin.command("ping")  # type: ignore[union-attr]
            return True
        except Exception:
            await mongo.disconnect_mongo()
    await connect_mongo()
    return mongo.files_bucket is not None


async def migrate_local_storage_once() -> int:
    if not await _ensure_mongo_available():
        return 0

    async with SessionLocal() as session:
        document_keys = (
            await session.execute(
                select(Document.storage_key).where(Document.storage_key.startswith(LOCAL_STORAGE_PREFIX))
            )
        ).scalars().all()
        version_keys = (
            await session.execute(
                select(DocumentVersion.storage_key).where(DocumentVersion.storage_key.startswith(LOCAL_STORAGE_PREFIX))
            )
        ).scalars().all()

        migrated = 0
        for local_key in sorted(set(document_keys) | set(version_keys)):
            try:
                mongo_key = await storage_service.upload_local_file_to_mongo(
                    local_key,
                    _filename_from_storage_key(local_key),
                    metadata={"migrated_from": local_key},
                )

                await session.execute(
                    update(Document)
                    .where(Document.storage_key == local_key)
                    .values(storage_key=mongo_key)
                )
                await session.execute(
                    update(DocumentVersion)
                    .where(DocumentVersion.storage_key == local_key)
                    .values(storage_key=mongo_key)
                )
                await session.commit()
                storage_service.delete_local(local_key)
                migrated += 1
            except Exception:
                await session.rollback()

        return migrated


async def run_local_storage_migration_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await migrate_local_storage_once()
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.local_storage_migration_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass
