import json
import inspect
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import mongo
from app.models import AccessRequest, Document, Folder, PublicLink, User


class AuditService:
    def __init__(self) -> None:
        self.logs_dir = Path(settings.logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.active_file = self.logs_dir / f"Logs {datetime.now(timezone.utc).isoformat().replace(':', '-')}.jsonl"

    async def log_event(
        self,
        event_type: str,
        event_subject: str,
        event_context: str,
        result: str,
        extra: str | None = None,
    ) -> None:
        #Все события приводятся к единому JSONL-формату перед отправкой или локальной записью.
        event_subject = str(event_subject).strip()
        event_context = str(event_context).strip()
        result = str(result).strip()
        for prefix in (f"пользователь {event_subject} ", f"Пользователь {event_subject} "):
            if event_context.startswith(prefix):
                event_context = event_context[len(prefix):].strip()
                break

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "event_subject": event_subject,
            "event_context": event_context,
            "result": result,
            "extra": extra or "",
        }

        if settings.audit_service_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{settings.audit_service_url.rstrip('/')}/audit/internal/log",
                        headers={"X-Internal-Token": settings.internal_service_token},
                        json={
                            "event_type": event_type,
                            "event_subject": event_subject,
                            "event_context": event_context,
                            "result": result,
                            "extra": extra,
                        },
                    )
                return
            except Exception:
                pass

        await self._write_local_event(payload)

    async def _write_local_event(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.active_file.open("a", encoding="utf-8") as fh:
            fh.write(line)

        if self.active_file.stat().st_size >= 100 * 1024 * 1024:
            await self._rotate_file()

    async def _rotate_file(self) -> None:
        #При ротации закрытый файл сразу уходит в архивное хранилище.
        closed_file = self.active_file
        await self._archive_log_file(closed_file)

        self.active_file = self.logs_dir / f"Logs {datetime.now(timezone.utc).isoformat().replace(':', '-')}.jsonl"

    async def _archive_log_file(self, log_file: Path) -> bool:
        if mongo.logs_bucket is None or not log_file.exists():
            return False

        data = log_file.read_bytes()
        await mongo.logs_bucket.upload_from_stream(
            log_file.name,
            data,
            metadata={"created_at": datetime.now(timezone.utc).isoformat(), "size_bytes": len(data)},
        )
        log_file.unlink()
        return True

    async def archive_pending_logs(self) -> int:
        #Фоновая архивация забирает только закрытые файлы, активный лог остается на диске.
        if mongo.logs_bucket is None:
            return 0

        archived = 0
        active_file = self.active_file.resolve()
        for log_file in sorted(self.logs_dir.glob("Logs *.jsonl")):
            if log_file.resolve() == active_file:
                continue
            try:
                if await self._archive_log_file(log_file):
                    archived += 1
            except Exception:
                continue
        return archived


audit_service = AuditService()


def audit_error_extra(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    status_code = getattr(exc, "status_code", None)
    if detail is not None:
        if status_code is not None:
            return f"status={status_code}; {detail}"
        return str(detail)
    return str(exc)


async def log_audit_error(event_type: str, event_subject: str, event_context: str, exc: Exception) -> None:
    try:
        await audit_service.log_event(event_type, event_subject, event_context, "error", audit_error_extra(exc))
    except Exception:
        pass


async def safe_log_event(
    event_type: str,
    event_subject: str,
    event_context: str,
    result: str,
    extra: str | None = None,
) -> None:
    try:
        await audit_service.log_event(event_type, event_subject, event_context, result, extra)
    except Exception:
        pass


def audit_error_handler(
    event_type: str,
    context_builder: Callable[..., str],
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                current_user = kwargs.get("current_user")
                try:
                    subject = audit_user_object(current_user) if current_user is not None else "anonymous"
                except Exception:
                    subject = "anonymous"
                try:
                    context = context_builder(*args, **kwargs)
                    if inspect.isawaitable(context):
                        context = await context
                except TypeError:
                    try:
                        context = context_builder(**kwargs)
                        if inspect.isawaitable(context):
                            context = await context
                    except Exception:
                        context = f"{func.__name__} failed"
                except Exception:
                    context = f"{func.__name__} failed"
                session = kwargs.get("session")
                if session is not None:
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                await log_audit_error(event_type, subject, context, exc)
                raise

        return wrapper

    return decorator


def audit_user_object(user) -> str:
    return user.login


def audit_document_object(document) -> str:
    return f'"{document.name}"'


def audit_folder_object(folder) -> str:
    return f'"{folder.name}"'


async def audit_document_label(session: AsyncSession, document_id: int) -> str:
    try:
        document = await session.get(Document, document_id)
    except Exception:
        document = None
    return audit_document_object(document) if document is not None else f"document {document_id}"


async def audit_document_labels(session: AsyncSession, document_ids: list[int]) -> str:
    labels = [await audit_document_label(session, document_id) for document_id in document_ids]
    return ", ".join(labels)


async def audit_folder_label(session: AsyncSession, folder_id: int) -> str:
    try:
        folder = await session.get(Folder, folder_id)
    except Exception:
        folder = None
    return audit_folder_object(folder) if folder is not None else f"folder {folder_id}"


async def audit_user_label(session: AsyncSession, user_id: int) -> str:
    try:
        user = await session.get(User, user_id)
    except Exception:
        user = None
    return user.login if user is not None else f"user {user_id}"


async def audit_user_labels(session: AsyncSession, user_ids: list[int]) -> str:
    labels = [await audit_user_label(session, user_id) for user_id in user_ids]
    return ", ".join(labels)


async def audit_access_request_label(session: AsyncSession, request_id: int) -> str:
    try:
        access_request = await session.get(AccessRequest, request_id)
        if access_request is None:
            return f"access request {request_id}"
        requester = await audit_user_label(session, access_request.requester_id)
        document = await audit_document_label(session, access_request.document_id)
    except Exception:
        return f"access request {request_id}"
    return f"access request from {requester} for {document}"


async def audit_access_request_labels(session: AsyncSession, request_ids: list[int]) -> str:
    labels = [await audit_access_request_label(session, request_id) for request_id in request_ids]
    return ", ".join(labels)


async def audit_public_link_label(session: AsyncSession, link_id: int) -> str:
    try:
        link = await session.get(PublicLink, link_id)
        document = await session.get(Document, link.document_id) if link is not None else None
    except Exception:
        link = None
        document = None
    if link is None:
        return f"public link {link_id}"
    if document is not None:
        return f"public link for {audit_document_object(document)}"
    return f"public link {link_id}"


async def audit_public_link_token_label(session: AsyncSession, token: str) -> str:
    try:
        link = (await session.execute(select(PublicLink).where(PublicLink.token == token))).scalar_one_or_none()
        document = await session.get(Document, link.document_id) if link is not None else None
    except Exception:
        link = None
        document = None
    if link is None:
        return f"public link {token}"
    if document is not None:
        return f"public link for {audit_document_object(document)}"
    return f"public link {token}"


def audit_bulk_result(processed: list | tuple | set, skipped: list[dict]) -> str:
    if skipped and not processed:
        return "error"
    if skipped:
        return "partial"
    return "success"


def audit_bulk_extra(skipped: list[dict], object_key: str = "id") -> str | None:
    if not skipped:
        return None
    failed = []
    for item in skipped:
        object_value = item.get(object_key, item.get("id", item.get("document_id", "unknown")))
        reason = item.get("reason", "unknown reason")
        failed.append(f"{object_value}: {reason}")
    return "Failed objects: " + "; ".join(failed)
