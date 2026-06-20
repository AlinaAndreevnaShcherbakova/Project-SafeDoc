from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.documents import can_manage_document_access
from app.db.postgres import get_session
from app.models import Document, PublicLink, User
from app.schemas.access import PublicLinkCreate, PublicLinkRead
from app.services.audit import audit_document_label, audit_document_object, audit_error_handler, audit_public_link_label, audit_user_object, safe_log_event
from app.services.preview import preview_service
from app.services.storage import storage_service

router = APIRouter()
_PUBLIC_VIEWER_KEYS: dict[str, tuple[str, datetime]] = {}
_VIEWER_KEY_TTL_SECONDS = 300


async def _audit_create_public_link_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["document_id"])
    return f"{kwargs['current_user'].login} failed to create public link for {document}"


async def _audit_revoke_public_link_by_id_error_context(**kwargs) -> str:
    link = await audit_public_link_label(kwargs["session"], kwargs["link_id"])
    return f"{kwargs['current_user'].login} failed to revoke {link}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_viewer_keys() -> None:
    now = _utcnow()
    expired_keys = [key for key, (_, expires_at) in _PUBLIC_VIEWER_KEYS.items() if expires_at <= now]
    for key in expired_keys:
        _PUBLIC_VIEWER_KEYS.pop(key, None)


def _create_viewer_key(public_token: str) -> str:
    #Короткий одноразовый ключ отделяет HTML-страницу публичного просмотра от прямого stream-запроса.
    _cleanup_viewer_keys()
    key = uuid4().hex
    expires_at = datetime.fromtimestamp(_utcnow().timestamp() + _VIEWER_KEY_TTL_SECONDS, tz=timezone.utc)
    _PUBLIC_VIEWER_KEYS[key] = (public_token, expires_at)
    return key


def _validate_viewer_key(public_token: str, viewer_key: str) -> bool:
    _cleanup_viewer_keys()
    value = _PUBLIC_VIEWER_KEYS.get(viewer_key)
    if value is None:
        return False
    key_token, expires_at = value
    if key_token != public_token or expires_at <= _utcnow():
        _PUBLIC_VIEWER_KEYS.pop(viewer_key, None)
        return False
    return True


async def _get_active_public_link(token: str, session: AsyncSession) -> PublicLink:
    #Публичная ссылка считается доступной только пока не истекла и не была отозвана.
    link = (
        await session.execute(
            select(PublicLink).where(and_(PublicLink.token == token, PublicLink.revoked_at.is_(None)))
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка не найдена")
    if link.expires_at <= _utcnow():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Срок действия ссылки истек")
    return link

@router.post("/{document_id}", response_model=PublicLinkRead)
@audit_error_handler("public_link", _audit_create_public_link_error_context)
async def create_public_link(
    document_id: int,
    payload: PublicLinkCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PublicLinkRead:
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    document = cast(Document, document)

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


    token = str(uuid4())
    link_name = payload.name.strip() if payload.name else None
    link = PublicLink(
        document_id=document_id,
        token=token,
        name=link_name or None,
        created_by_id=current_user.id,
        expires_at=payload.expires_at,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)

    await safe_log_event("public_link", audit_user_object(current_user), f"{current_user.login} created public link for {audit_document_object(document)}", "success")
    return PublicLinkRead.model_validate(link)


@router.get("/{document_id}", response_model=list[PublicLinkRead])
async def list_public_links(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[PublicLinkRead]:
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    document = cast(Document, document)
    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    rows = (
        await session.execute(
            select(PublicLink)
            .where(PublicLink.document_id == document_id)
            .order_by(PublicLink.id.desc())
        )
    ).scalars().all()
    return [PublicLinkRead.model_validate(row) for row in rows]


@router.get("/public/{token}")
async def preview_by_public_link(token: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    #HTML-обертка отдает iframe без раскрытия прямого доступа к файлу.
    link = await _get_active_public_link(token, session)
    document = await session.get(Document, link.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    document = cast(Document, document)

    viewer_key = _create_viewer_key(token)
    html = f"""<!doctype html>
<html lang=\"ru\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Публичный просмотр документа</title>
    <style>
      html, body {{ margin: 0; height: 100%; background: #f5f6f8; }}
      .wrap {{ height: 100%; display: flex; flex-direction: column; }}
      iframe {{ border: 0; width: 100%; height: 100%; }}
    </style>
  </head>
  <body>
    <div class=\"wrap\">
      <iframe src=\"/api/links/public/{token}/stream?viewer_key={viewer_key}#toolbar=0&navpanes=0&scrollbar=0\" referrerpolicy=\"no-referrer\"></iframe>
    </div>
    <script>
      document.addEventListener('contextmenu', function(e) {{ e.preventDefault(); }});
      document.addEventListener('keydown', function(e) {{
        const key = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (key === 's' || key === 'p')) {{
          e.preventDefault();
        }}
      }});
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/public/{token}/stream")
async def preview_by_public_link_stream(
    token: str,
    viewer_key: str = Query(..., min_length=8),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not _validate_viewer_key(token, viewer_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Сессия просмотра недействительна")

    link = await _get_active_public_link(token, session)
    document = await session.get(Document, link.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    document = cast(Document, document)

    data = await storage_service.download(document.storage_key)
    payload, media_type, _ = await preview_service.build_preview_payload(
        data=data,
        filename=document.name,
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )




@router.post("/{link_id}/revoke")
@audit_error_handler("public_link", _audit_revoke_public_link_by_id_error_context)
async def revoke_public_link_by_id(
    link_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    link = await session.get(PublicLink, link_id)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ссылка не найдена")

    document = await session.get(Document, link.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    link.revoked_at = datetime.now(timezone.utc)
    await session.commit()

    await safe_log_event(
        "public_link",
        audit_user_object(current_user),
        f"{current_user.login} revoked public link for {audit_document_object(document)}",
        "success",
    )
    return {"status": "ok"}



