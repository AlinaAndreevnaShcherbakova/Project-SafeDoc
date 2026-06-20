from pathlib import Path
from uuid import uuid4

from bson import ObjectId
from fastapi import HTTPException, UploadFile, status
from gridfs.errors import NoFile

from app.core.config import settings
from app.db import mongo


class StorageService:
    def __init__(self) -> None:
        self.storage_dir = Path(settings.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def upload(self, filename: str, data: bytes, metadata: dict) -> str:
        #MongoDB используется как основное хранилище, локальная запись остается резервным вариантом.
        if mongo.files_bucket is not None:
            try:
                object_id = await mongo.files_bucket.upload_from_stream(filename, data, metadata=metadata)
                return f"mongo://{str(object_id)}"
            except Exception:
                await mongo.disconnect_mongo()

        key = f"local-{uuid4().hex}-{filename}"
        path = self.storage_dir / key
        path.write_bytes(data)
        return f"local://{key}"

    async def upload_local_file_to_mongo(
        self,
        storage_key: str,
        filename: str,
        metadata: dict,
        chunk_size: int = 1024 * 1024,
    ) -> str:
        #Миграция читает локальный файл чанками, чтобы не держать весь файл в памяти.
        if mongo.files_bucket is None:
            raise RuntimeError("MongoDB file bucket is not available")

        path = self.local_path_for_key(storage_key)
        if not path.exists():
            raise FileNotFoundError("Local file not found")

        stream = mongo.files_bucket.open_upload_stream(filename, metadata=metadata)
        try:
            with path.open("rb") as source:
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    await stream.write(chunk)
            await stream.close()
            return f"mongo://{str(stream._id)}"
        except Exception:
            try:
                await stream.abort()
            except Exception:
                pass
            raise

    def local_path_for_key(self, storage_key: str) -> Path:
        key = storage_key.replace("local://", "")
        return self.storage_dir / key

    def delete_local(self, storage_key: str) -> None:
        path = self.local_path_for_key(storage_key)
        if path.exists():
            path.unlink()

    async def upload_stream(self, upload_file: UploadFile, metadata: dict, max_size: int, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
        #Потоковая загрузка сразу контролирует размер файла и обрывает запись при превышении лимита.
        filename = upload_file.filename or "upload.bin"
        max_size_mb = max_size // (1024 * 1024)
        size_error = f"Файл больше {max_size_mb} МБ"

        if mongo.files_bucket is not None:
            stream = mongo.files_bucket.open_upload_stream(filename, metadata=metadata)
            total_size = 0
            try:
                while True:
                    chunk = await upload_file.read(chunk_size)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_size:
                        await stream.abort()
                        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=size_error)
                    await stream.write(chunk)
                await stream.close()
                return f"mongo://{str(stream._id)}", total_size
            except HTTPException:
                try:
                    await stream.abort()
                except Exception:
                    pass
                raise
            except Exception:
                try:
                    await stream.abort()
                except Exception:
                    pass
                await mongo.disconnect_mongo()
                await upload_file.seek(0)

        key = f"local-{uuid4().hex}-{filename}"
        path = self.storage_dir / key
        total_size = 0
        try:
            with path.open("wb") as target:
                while True:
                    chunk = await upload_file.read(chunk_size)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_size:
                        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=size_error)
                    target.write(chunk)
            return f"local://{key}", total_size
        except Exception:
            if path.exists():
                path.unlink()
            raise

    async def download(self, storage_key: str) -> bytes:
        #Префикс storage_key определяет, откуда читать файл: из MongoDB или локального каталога.
        if storage_key.startswith("mongo://"):
            if mongo.files_bucket is None:
                raise FileNotFoundError("MongoDB недоступна для чтения файла")
            object_id_raw = storage_key.replace("mongo://", "")
            if not ObjectId.is_valid(object_id_raw):
                raise ValueError("Некорректный storage_key для MongoDB")
            object_id = ObjectId(object_id_raw)
            try:
                stream = await mongo.files_bucket.open_download_stream(object_id)
            except NoFile as exc:
                raise FileNotFoundError("Файл в MongoDB не найден") from exc
            return await stream.read()

        path = self.local_path_for_key(storage_key)
        if not path.exists():
            raise FileNotFoundError("Локальный файл не найден")
        return path.read_bytes()


storage_service = StorageService()

