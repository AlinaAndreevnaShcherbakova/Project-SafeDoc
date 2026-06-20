from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_internal_service
from app.services.audit import audit_service

router = APIRouter()


class AuditEventRequest(BaseModel):
    event_type: str
    event_context: str | None = None
    event_object: str | None = None
    event_subject: str
    result: str
    extra: str | None = None


@router.post("/internal/log")
async def ingest_audit_event(
    payload: AuditEventRequest,
    _: None = Depends(require_internal_service),
) -> dict:
    #Внутренний endpoint принимает события от других сервисов в едином формате audit.
    event_context = payload.event_context or payload.event_object
    if event_context is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_context is required")

    await audit_service.log_event(
        payload.event_type,
        payload.event_subject,
        event_context,
        payload.result,
        payload.extra,
    )
    return {"status": "ok"}


