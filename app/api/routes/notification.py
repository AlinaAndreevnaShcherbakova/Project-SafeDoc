from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends

from app.api.deps import require_internal_service
from app.services.notifications import NotificationMessage, audit_safe_send_notification

router = APIRouter()


class NotificationSendRequest(BaseModel):
    to_email: EmailStr
    subject: str
    body: str


@router.post("/send")
async def send_notification(
    payload: NotificationSendRequest,
    _: None = Depends(require_internal_service),
) -> dict:
    #Внешние вызовы сюда не допускаются: письма отправляются только по внутреннему токену.
    await audit_safe_send_notification(
        str(payload.to_email),
        NotificationMessage(subject=payload.subject, body=payload.body),
    )
    return {"status": "ok"}
