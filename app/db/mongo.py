from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from app.core.config import settings

client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None
files_bucket: AsyncIOMotorGridFSBucket | None = None
logs_bucket: AsyncIOMotorGridFSBucket | None = None


async def connect_mongo() -> None:
    global client, database, files_bucket, logs_bucket
    next_client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=2000)
    try:
        await next_client.admin.command("ping")
    except Exception:
        next_client.close()
        client = None
        database = None
        files_bucket = None
        logs_bucket = None
        return

    client = next_client
    database = client[settings.mongo_db]
    files_bucket = AsyncIOMotorGridFSBucket(database, bucket_name="files")
    logs_bucket = AsyncIOMotorGridFSBucket(database, bucket_name="logs")


async def disconnect_mongo() -> None:
    global client, database, files_bucket, logs_bucket
    if client is not None:
        client.close()
        client = None
    database = None
    files_bucket = None
    logs_bucket = None

