from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_document_role_names, get_global_role_names, require_internal_service
from app.db.postgres import get_session
from app.models import AccessRequest, AccessRequestStatus, Document, DocumentACL, Role, RoleName, User, Worker
from app.schemas.access import (
    AccessGrantRead,
    STATUS_RU_MAP,
    AccessPermission,
    GrantAccessBulkRequest,
    AccessRequestBulkCreate,
    AccessRequestBulkResolve,
    AccessRequestCreate,
    AccessRequestRead,
    AccessRequestResolve,
    AccessUserOption,
    DocumentPermissionsBulkRequest,
    GrantAccessRequest,
    RevokeAccessRequest,
    RevokeAccessBulkRequest,
    normalize_permissions,
)
from app.services.audit import audit_access_request_label, audit_access_request_labels, audit_bulk_extra, audit_bulk_result, audit_document_label, audit_document_labels, audit_document_object, audit_error_handler, audit_user_label, audit_user_labels, audit_user_object, safe_log_event
from app.services.notifications import (
    audit_safe_send_notification,
    build_access_grant_email,
    build_access_request_email,
    build_access_request_resolution_email,
    build_access_revoke_email,
)
from app.services.authz import (
    is_read_allowed_by_visibility,
    is_write_allowed_by_visibility,
    role_can_manage_access as role_names_can_manage_access,
    role_can_download,
    role_can_read,
    role_can_write,
)

router = APIRouter()


async def _can_read_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    if current_user.id == document.owner_id:
        return True
    document_roles = await get_document_role_names(current_user.id, document.id, session)
    return role_can_read(document_roles) or is_read_allowed_by_visibility(document.visibility)


async def _can_write_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    if current_user.id == document.owner_id:
        return True
    document_roles = await get_document_role_names(current_user.id, document.id, session)
    return role_can_write(document_roles) or is_write_allowed_by_visibility(document.visibility)


async def _can_download_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    if current_user.id == document.owner_id:
        return True
    document_roles = await get_document_role_names(current_user.id, document.id, session)
    return role_can_download(document_roles) or is_write_allowed_by_visibility(document.visibility)


async def can_manage_document_access(session: AsyncSession, current_user: User, document: Document) -> bool:
    if current_user.id == document.owner_id:
        return True
    global_roles = await get_global_role_names(current_user.id, session)
    if RoleName.SUPERADMIN in global_roles:
        return True
    if RoleName.ACCESS_MANAGER in global_roles:
        owner = await session.get(User, document.owner_id)
        if owner is not None and owner.worker.department_id == current_user.worker.department_id:
            return True
    document_roles = await get_document_role_names(current_user.id, document.id, session)
    return role_names_can_manage_access(document_roles)


async def _get_bulk_document_permissions(
    session: AsyncSession,
    user: User,
    document_ids: list[int],
) -> dict[int, dict[str, bool]]:
    unique_doc_ids = list(dict.fromkeys(document_ids))
    if not unique_doc_ids:
        return {}

    documents = (
        await session.execute(
            select(Document).where(
                Document.id.in_(unique_doc_ids),
                Document.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    role_rows = (
        await session.execute(
            select(DocumentACL.document_id, Role.name)
            .join(Role, Role.id == DocumentACL.role_id)
            .where(
                DocumentACL.user_id == user.id,
                DocumentACL.document_id.in_(unique_doc_ids),
            )
        )
    ).all()
    roles_by_doc_id: dict[int, set[RoleName]] = {}
    for document_id, role_name in role_rows:
        roles_by_doc_id.setdefault(document_id, set()).add(role_name)

    global_roles = await get_global_role_names(user.id, session)
    access_manager_owner_departments: dict[int, int | None] = {}
    if RoleName.ACCESS_MANAGER in global_roles:
        owner_ids = sorted({document.owner_id for document in documents if document.owner_id != user.id})
        if owner_ids:
            owner_rows = (
                await session.execute(
                    select(User.id, Worker.department_id)
                    .join(Worker, Worker.id == User.worker_id)
                    .where(User.id.in_(owner_ids))
                )
            ).all()
            access_manager_owner_departments = {row.id: row.department_id for row in owner_rows}

    result: dict[int, dict[str, bool]] = {}
    for document in documents:
        document_roles = roles_by_doc_id.get(document.id, set())
        is_owner = user.id == document.owner_id
        can_read = is_owner or role_can_read(document_roles) or is_read_allowed_by_visibility(document.visibility)
        can_download = is_owner or role_can_download(document_roles) or is_write_allowed_by_visibility(document.visibility)
        can_write = is_owner or role_can_write(document_roles) or is_write_allowed_by_visibility(document.visibility)
        can_manage = is_owner or RoleName.SUPERADMIN in global_roles or role_names_can_manage_access(document_roles)
        if not can_manage and RoleName.ACCESS_MANAGER in global_roles:
            can_manage = access_manager_owner_departments.get(document.owner_id) == user.worker.department_id
        result[document.id] = {
            "can_read": can_read,
            "can_download": can_download,
            "can_write": can_write,
            "can_manage_access": can_manage,
        }
    return result


async def _audit_request_access_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["payload"].document_id)
    return f"{kwargs['current_user'].login} failed to request access to {document}"


async def _audit_bulk_request_access_error_context(**kwargs) -> str:
    documents = await audit_document_labels(kwargs["session"], kwargs["payload"].document_ids)
    return f"{kwargs['current_user'].login} failed to bulk request access to documents: {documents}"


async def _audit_resolve_request_error_context(**kwargs) -> str:
    request_label = await audit_access_request_label(kwargs["session"], kwargs["request_id"])
    return f"{kwargs['current_user'].login} failed to resolve {request_label}"


async def _audit_bulk_resolve_requests_error_context(**kwargs) -> str:
    requests = await audit_access_request_labels(kwargs["session"], kwargs["payload"].request_ids)
    return f"{kwargs['current_user'].login} failed to bulk resolve access requests: {requests}"


async def _audit_grant_access_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["payload"].document_id)
    user = await audit_user_label(kwargs["session"], kwargs["payload"].user_id)
    return f"{kwargs['current_user'].login} failed to grant access to {document} for user {user}"


async def _audit_bulk_grant_access_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["payload"].document_id)
    users = await audit_user_labels(kwargs["session"], kwargs["payload"].user_ids)
    return f"{kwargs['current_user'].login} failed to bulk grant access to {document} for users: {users}"


async def _audit_revoke_access_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["payload"].document_id)
    user = await audit_user_label(kwargs["session"], kwargs["payload"].user_id)
    return f"{kwargs['current_user'].login} failed to revoke access to {document} from user {user}"


async def _audit_bulk_revoke_access_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["payload"].document_id)
    users = await audit_user_labels(kwargs["session"], kwargs["payload"].user_ids)
    return f"{kwargs['current_user'].login} failed to bulk revoke access to {document} from users: {users}"


def _permissions_to_role(permissions: Iterable[AccessPermission]) -> RoleName:
    permissions_set = set(permissions)
    if "access_manage" in permissions_set:
        return RoleName.OWNER
    if "edit" in permissions_set or "version_manage" in permissions_set:
        return RoleName.EDITOR
    if "preview" in permissions_set or "download" in permissions_set or "version_view" in permissions_set:
        return RoleName.READER
    #Гость вычисляется логически, поэтому в БД сохраняется минимальная роль читателя.
    return RoleName.READER


def _role_to_permissions(role: RoleName) -> list[AccessPermission]:
    if role == RoleName.OWNER:
        return normalize_permissions(["preview", "download", "edit", "version_view", "version_manage", "access_manage"])
    if role == RoleName.EDITOR:
        return normalize_permissions(["preview", "download", "edit", "version_view", "version_manage"])
    if role == RoleName.READER:
        return normalize_permissions(["preview", "version_view"])
    return []


def _unpack_message_and_permissions(raw_message: str | None, requested_role: RoleName) -> tuple[str | None, list[AccessPermission]]:
    return (raw_message.strip() or None) if raw_message else None, _role_to_permissions(requested_role)


async def _get_role_by_name(session: AsyncSession, role_name: RoleName) -> Role:
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Роль не найдена")
    return role


def _role_label_ru(role: RoleName | str) -> str:
    if isinstance(role, str):
        try:
            role = RoleName(role)
        except ValueError:
            return role

    return {
        RoleName.OWNER: "владелец",
        RoleName.EDITOR: "редактор",
        RoleName.READER: "читатель",
        RoleName.GUEST: "гость",
    }.get(role, role.value)


def _parse_date_filter(value: str | None) -> datetime | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный формат даты фильтра") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _serialize_access_request(session: AsyncSession, request: AccessRequest) -> AccessRequestRead:
    def _safe_role(value: RoleName | str | None) -> RoleName:
        if isinstance(value, RoleName):
            return value
        if isinstance(value, str):
            try:
                return RoleName(value)
            except ValueError:
                return RoleName.GUEST
        return RoleName.GUEST

    def _safe_status(value: AccessRequestStatus | str | None) -> AccessRequestStatus:
        if isinstance(value, AccessRequestStatus):
            return value
        if isinstance(value, str):
            try:
                return AccessRequestStatus(value)
            except ValueError:
                return AccessRequestStatus.PENDING
        return AccessRequestStatus.PENDING

    requester = await session.get(User, request.requester_id)
    resolver = await session.get(User, request.resolved_by_id) if request.resolved_by_id else None
    document = await session.get(Document, request.document_id)
    requested_role = _safe_role(request.requested_role)
    status_value = _safe_status(request.status)
    message, permissions = _unpack_message_and_permissions(request.message, requested_role)

    payload = AccessRequestRead.model_validate(
        {
            "id": request.id,
            "document_id": request.document_id,
            "document_name": document.name if document else None,
            "requester_id": request.requester_id,
            "requester_login": requester.login if requester else None,
            "requested_role": requested_role,
            "requested_permissions": permissions,
            "status": status_value,
            "status_ru": STATUS_RU_MAP.get(status_value, status_value.value),
            "message": message,
            "created_at": request.created_at,
            "resolved_at": request.resolved_at,
            "resolved_by_id": request.resolved_by_id,
            "resolved_by_login": resolver.login if resolver else None,
            "resolution_comment": request.resolution_comment,
        }
    )
    return payload


@router.post("/requests", response_model=AccessRequestRead)
@audit_error_handler("access_request", _audit_request_access_error_context)
async def request_access(
    payload: AccessRequestCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AccessRequestRead:
    #Заявка создается только на чужой документ и не дублирует уже ожидающий запрос.
    doc = await session.get(Document, payload.document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    requested_role = payload.requested_role or _permissions_to_role(payload.requested_permissions)
    role = await _get_role_by_name(session, requested_role)
    request = AccessRequest(
        document_id=payload.document_id,
        requester_id=current_user.id,
        requested_role_id=role.id,
        status=AccessRequestStatus.PENDING,
        message=payload.message,
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)

    owner = await session.get(User, doc.owner_id)
    if owner is not None:
        message = request.message
        await audit_safe_send_notification(
            owner.email,
            build_access_request_email(doc.name, current_user, _role_label_ru(requested_role), message),
        )

    await safe_log_event("access_request", audit_user_object(current_user), f"{current_user.login} requested access to {audit_document_object(doc)}", "success")
    return await _serialize_access_request(session, request)


@router.post("/requests/bulk")
@audit_error_handler("access_request", _audit_bulk_request_access_error_context)
async def request_access_bulk(
    payload: AccessRequestBulkCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    created_ids: list[int] = []
    created_document_names: list[str] = []
    skipped: list[dict] = []
    requested_role = payload.requested_role or _permissions_to_role(payload.requested_permissions)
    role = await _get_role_by_name(session, requested_role)

    for document_id in payload.document_ids:
        doc = await session.get(Document, document_id)
        if doc is None or doc.deleted_at is not None:
            skipped.append({"document_id": document_id, "reason": "Документ не найден"})
            continue
        if doc.owner_id == current_user.id:
            skipped.append({"document_id": document_id, "reason": "Нельзя запрашивать доступ к собственному документу"})
            continue

        duplicate_pending = (
            await session.execute(
                select(AccessRequest.id).where(
                    AccessRequest.document_id == document_id,
                    AccessRequest.requester_id == current_user.id,
                    AccessRequest.status == AccessRequestStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        if duplicate_pending is not None:
            skipped.append({"document_id": document_id, "reason": "Заявка уже отправлена"})
            continue

        request = AccessRequest(
            document_id=document_id,
            requester_id=current_user.id,
            requested_role_id=role.id,
            status=AccessRequestStatus.PENDING,
            message=payload.message,
        )
        session.add(request)
        await session.flush()
        created_ids.append(request.id)
        created_document_names.append(doc.name)

        owner = await session.get(User, doc.owner_id)
        if owner is not None:
            message = request.message
            await audit_safe_send_notification(
                owner.email,
                build_access_request_email(doc.name, current_user, _role_label_ru(requested_role), message),
            )

    await session.commit()
    await safe_log_event(
        "access_request",
        audit_user_object(current_user),
        f"{current_user.login} bulk requested access to documents: {', '.join(created_document_names)}",
        audit_bulk_result(created_ids, skipped),
        audit_bulk_extra(skipped, "document_id"),
    )
    return {"created_request_ids": created_ids, "skipped": skipped}


@router.get("/requests/my", response_model=list[AccessRequestRead])
async def my_requests(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[AccessRequestRead]:
    query = select(AccessRequest).where(AccessRequest.requester_id == current_user.id)
    from_dt = _parse_date_filter(date_from)
    to_dt = _parse_date_filter(date_to)
    if from_dt is not None:
        query = query.where(AccessRequest.created_at >= from_dt)
    if to_dt is not None:
        query = query.where(AccessRequest.created_at <= to_dt)

    rows = (await session.execute(query.order_by(AccessRequest.created_at.desc()))).scalars().all()
    return [await _serialize_access_request(session, row) for row in rows]


async def _apply_document_role(
    session: AsyncSession,
    document_id: int,
    user_id: int,
    role_name: RoleName,
) -> tuple[bool, bool]:
    #Смена роли выполняется как замена всех документных ролей пользователя одной актуальной ролью.
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Роль не найдена")

    current_rows = (
        await session.execute(
            select(DocumentACL).where(
                and_(DocumentACL.user_id == user_id, DocumentACL.document_id == document_id)
            )
        )
    ).scalars().all()
    had_existing_access = bool(current_rows)

    #Идемпотентность: если уже стоит нужная роль, ничего не меняется.
    if any(row.role_id == role.id for row in current_rows):
        return False, had_existing_access

    for row in current_rows:
        await session.delete(row)
    await session.flush()

    session.add(DocumentACL(user_id=user_id, role_id=role.id, document_id=document_id))
    return True, had_existing_access


@router.get("/documents/{document_id}/acl", response_model=list[AccessGrantRead])
async def document_acl(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[AccessGrantRead]:
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    rows = (
        await session.execute(
            select(DocumentACL, User, Role)
            .join(User, User.id == DocumentACL.user_id)
            .join(Role, Role.id == DocumentACL.role_id)
            .where(DocumentACL.document_id == document_id)
            .order_by(User.login.asc())
        )
    ).all()

    result: list[AccessGrantRead] = []
    for user_role, user, role in rows:
        full_name = " ".join(part for part in [user.surname, user.name, user.middle_name] if part).strip()
        effective_role = RoleName.OWNER if user_role.user_id == document.owner_id else role.name
        result.append(
            AccessGrantRead(
                user_id=user_role.user_id,
                user_login=user.login,
                user_full_name=full_name or user.login,
                role=effective_role,
                permissions=_role_to_permissions(effective_role),
            )
        )
    return result


@router.get("/users/search", response_model=list[AccessUserOption])
async def search_users(
    query: str | None = Query(None, max_length=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[AccessUserOption]:
    users_query = select(User).join(Worker, Worker.id == User.worker_id).order_by(User.login.asc()).limit(50)
    text_query = (query or "").strip()
    if text_query:
        pattern = f"%{text_query}%"
        users_query = users_query.where(
            (User.login.ilike(pattern))
            | (Worker.surname.ilike(pattern))
            | (Worker.name.ilike(pattern))
            | (Worker.email.ilike(pattern))
        )

    rows = (await session.execute(users_query)).scalars().all()
    return [
        AccessUserOption(
            id=row.id,
            login=row.login,
            full_name=" ".join(part for part in [row.surname, row.name, row.middle_name] if part).strip() or row.login,
        )
        for row in rows
    ]


@router.get("/requests/inbox", response_model=list[AccessRequestRead])
async def inbox_requests(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[AccessRequestRead]:
    global_roles = await get_global_role_names(current_user.id, session)
    from_dt = _parse_date_filter(date_from)
    to_dt = _parse_date_filter(date_to)

    base_query = select(AccessRequest)
    if from_dt is not None:
        base_query = base_query.where(AccessRequest.created_at >= from_dt)
    if to_dt is not None:
        base_query = base_query.where(AccessRequest.created_at <= to_dt)

    if RoleName.SUPERADMIN in global_roles:
        rows = (await session.execute(base_query.order_by(AccessRequest.created_at.desc()))).scalars().all()
    elif RoleName.ACCESS_MANAGER in global_roles:
        managed_doc_ids = (
            await session.execute(
                select(Document.id)
                .join(User, User.id == Document.owner_id)
                .join(Worker, Worker.id == User.worker_id)
                .where(Worker.department_id == current_user.worker.department_id, Document.deleted_at.is_(None))
            )
        ).scalars().all()
        if not managed_doc_ids:
            return []
        rows = (
            await session.execute(
                base_query
                .where(AccessRequest.document_id.in_(managed_doc_ids))
                .order_by(AccessRequest.created_at.desc())
            )
        ).scalars().all()
    else:
        owned_doc_ids = (await session.execute(select(Document.id).where(Document.owner_id == current_user.id))).scalars().all()
        if not owned_doc_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        rows = (
            await session.execute(
                base_query
                .where(AccessRequest.document_id.in_(owned_doc_ids))
                .order_by(AccessRequest.created_at.desc())
            )
        ).scalars().all()

    return [await _serialize_access_request(session, row) for row in rows]


@router.post("/requests/{request_id}/resolve", response_model=AccessRequestRead)
@audit_error_handler("access_request", _audit_resolve_request_error_context)
async def resolve_request(
    request_id: int,
    payload: AccessRequestResolve,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AccessRequestRead:
    access_request = await _resolve_single_request(
        session=session,
        current_user=current_user,
        access_request_id=request_id,
        approve=payload.approve,
        resolution_comment=payload.resolution_comment,
    )
    await session.commit()
    await session.refresh(access_request)

    requester = await session.get(User, access_request.requester_id)
    document = await session.get(Document, access_request.document_id)
    document_name = document.name if document is not None else "unknown document"
    if requester is not None:
        role_label = _role_label_ru(access_request.requested_role if access_request.status == AccessRequestStatus.APPROVED else RoleName.GUEST)
        await audit_safe_send_notification(
            requester.email,
            build_access_request_resolution_email(
                document_name,
                current_user,
                access_request.status,
                role_label,
                access_request.resolution_comment,
            ),
        )

    requester_login = requester.login if requester is not None else "unknown user"
    action = "approved" if access_request.status == AccessRequestStatus.APPROVED else "rejected"
    await safe_log_event("access_request", audit_user_object(current_user), f"{current_user.login} {action} access request from {requester_login} for document \"{document_name}\"", "success")
    return await _serialize_access_request(session, access_request)


async def _resolve_single_request(
    session: AsyncSession,
    current_user: User,
    access_request_id: int,
    approve: bool,
    resolution_comment: str | None,
) -> AccessRequest:
    access_request = await session.get(AccessRequest, access_request_id)
    if access_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Запрос {access_request_id} не найден")

    document = await session.get(Document, access_request.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    if access_request.status != AccessRequestStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка уже обработана")

    access_request.status = AccessRequestStatus.APPROVED if approve else AccessRequestStatus.REJECTED
    access_request.resolved_at = datetime.now(timezone.utc)
    access_request.resolved_by_id = current_user.id
    access_request.resolution_comment = resolution_comment

    if approve:
        role = (await session.execute(select(Role).where(Role.name == access_request.requested_role))).scalar_one()
        current_rows = (
            await session.execute(
                select(DocumentACL).where(
                    and_(
                        DocumentACL.user_id == access_request.requester_id,
                        DocumentACL.document_id == access_request.document_id,
                    )
                )
            )
        ).scalars().all()
        for row in current_rows:
            await session.delete(row)
        session.add(DocumentACL(user_id=access_request.requester_id, role_id=role.id, document_id=access_request.document_id, request_id=access_request.id))

    return access_request


@router.post("/requests/resolve/bulk")
@audit_error_handler("access_request", _audit_bulk_resolve_requests_error_context)
async def resolve_requests_bulk(
    payload: AccessRequestBulkResolve,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    processed: list[int] = []
    processed_descriptions: list[str] = []
    skipped: list[dict] = []

    for request_id in payload.request_ids:
        try:
            resolved_request = await _resolve_single_request(
                session=session,
                current_user=current_user,
                access_request_id=request_id,
                approve=payload.approve,
                resolution_comment=payload.resolution_comment,
            )
            requester = await session.get(User, resolved_request.requester_id)
            document = await session.get(Document, resolved_request.document_id)
            document_name = document.name if document is not None else "unknown document"
            if requester is not None:
                role_label = _role_label_ru(resolved_request.requested_role if resolved_request.status == AccessRequestStatus.APPROVED else RoleName.GUEST)
                await audit_safe_send_notification(
                    requester.email,
                    build_access_request_resolution_email(
                        document_name,
                        current_user,
                        resolved_request.status,
                        role_label,
                        resolved_request.resolution_comment,
                    ),
                )
            requester_login = requester.login if requester is not None else "unknown user"
            processed_descriptions.append(f"{requester_login} -> {document_name}")
            processed.append(request_id)
        except HTTPException as exc:
            skipped.append({"id": request_id, "reason": str(exc.detail)})

    await session.commit()

    await safe_log_event(
        "access_request",
        audit_user_object(current_user),
        f"{current_user.login} bulk {'approved' if payload.approve else 'rejected'} access requests: {', '.join(processed_descriptions)}",
        audit_bulk_result(processed, skipped),
        audit_bulk_extra(skipped),
    )
    return {"processed": processed, "skipped": skipped}


@router.post("/grant")
@audit_error_handler("acl", _audit_grant_access_error_context)
async def grant_access(
    payload: GrantAccessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    document = await session.get(Document, payload.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    target_user = await session.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    role_name = payload.role or _permissions_to_role(payload.permissions)
    changed, had_existing_access = await _apply_document_role(
        session=session,
        document_id=payload.document_id,
        user_id=payload.user_id,
        role_name=role_name,
    )
    if not changed:
        return {"status": "ok"}

    await session.commit()

    role_label = _role_label_ru(role_name)

    await audit_safe_send_notification(
        target_user.email,
        build_access_grant_email(document.name, current_user, role_label, had_existing_access),
    )

    await safe_log_event("acl", audit_user_object(current_user), f"{current_user.login} granted access to {audit_document_object(document)} for user {target_user.login} with role {role_name.value}", "success")
    return {"status": "ok"}


@router.post("/grant/bulk")
@audit_error_handler("acl", _audit_bulk_grant_access_error_context)
async def grant_access_bulk(
    payload: GrantAccessBulkRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    document = await session.get(Document, payload.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    role_name = payload.role or _permissions_to_role(payload.permissions)
    role_label = _role_label_ru(role_name)

    processed: list[int] = []
    processed_logins: list[str] = []
    skipped: list[dict] = []

    for user_id in payload.user_ids:
        if user_id == document.owner_id:
            skipped.append({"id": user_id, "reason": "Нельзя изменять доступ владельца документа"})
            continue

        target_user = await session.get(User, user_id)
        if target_user is None:
            skipped.append({"id": user_id, "reason": "Пользователь не найден"})
            continue

        changed, had_existing_access = await _apply_document_role(
            session=session,
            document_id=payload.document_id,
            user_id=user_id,
            role_name=role_name,
        )
        if not changed:
            skipped.append({"id": user_id, "reason": "У пользователя уже установлен выбранный уровень доступа"})
            continue

        processed.append(user_id)
        processed_logins.append(target_user.login)
        try:
            await audit_safe_send_notification(
                target_user.email,
                build_access_grant_email(document.name, current_user, role_label, had_existing_access),
            )
        except Exception:
            pass

    await session.commit()
    await safe_log_event(
        "acl",
        audit_user_object(current_user),
        f"{current_user.login} granted access to {audit_document_object(document)} for users: {', '.join(processed_logins)} with role {role_name.value}",
        audit_bulk_result(processed, skipped),
        audit_bulk_extra(skipped),
    )
    return {"processed": processed, "skipped": skipped}


@router.post("/revoke")
@audit_error_handler("acl", _audit_revoke_access_error_context)
async def revoke_access(
    payload: RevokeAccessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    document = await session.get(Document, payload.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    if payload.user_id == document.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя отозвать доступ у владельца документа")

    target_user = await session.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    roles = (
        await session.execute(
            select(DocumentACL).where(
                and_(DocumentACL.user_id == payload.user_id, DocumentACL.document_id == payload.document_id)
            )
        )
    ).scalars().all()

    for row in roles:
        await session.delete(row)

    await session.commit()

    revoked_user = await session.get(User, payload.user_id)
    if revoked_user is not None:
        try:
            await audit_safe_send_notification(
                revoked_user.email,
                build_access_revoke_email(document.name, current_user),
            )
        except Exception:
            pass

    await safe_log_event("acl", audit_user_object(current_user), f"{current_user.login} revoked access to {audit_document_object(document)} from user {target_user.login}", "success")
    return {"status": "ok"}


@router.post("/revoke/bulk")
@audit_error_handler("acl", _audit_bulk_revoke_access_error_context)
async def revoke_access_bulk(
    payload: RevokeAccessBulkRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    document = await session.get(Document, payload.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await can_manage_document_access(session, current_user, document):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    processed: list[int] = []
    processed_logins: list[str] = []
    skipped: list[dict] = []

    for user_id in payload.user_ids:
        if user_id == document.owner_id:
            skipped.append({"id": user_id, "reason": "Нельзя отозвать доступ у владельца документа"})
            continue

        target_user = await session.get(User, user_id)
        if target_user is None:
            skipped.append({"id": user_id, "reason": "Пользователь не найден"})
            continue

        roles = (
            await session.execute(
                select(DocumentACL).where(and_(DocumentACL.user_id == user_id, DocumentACL.document_id == payload.document_id))
            )
        ).scalars().all()

        for row in roles:
            await session.delete(row)

        if roles:
            processed.append(user_id)
            processed_logins.append(target_user.login)

        try:
            await audit_safe_send_notification(
                target_user.email,
                build_access_revoke_email(document.name, current_user),
            )
        except Exception:
            pass

    await session.commit()
    await safe_log_event(
        "acl",
        audit_user_object(current_user),
        f"{current_user.login} revoked access to {audit_document_object(document)} from users: {', '.join(processed_logins)}",
        audit_bulk_result(processed, skipped),
        audit_bulk_extra(skipped),
    )
    return {"processed": processed, "skipped": skipped}


@router.get("/internal/documents/{document_id}/permissions")
async def document_permissions(
    document_id: int,
    user_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_internal_service),
) -> dict:
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    return {
        "can_read": await _can_read_document(session, user, document),
        "can_download": await _can_download_document(session, user, document),
        "can_write": await _can_write_document(session, user, document),
        "can_manage_access": await can_manage_document_access(session, user, document),
    }


@router.post("/internal/documents/permissions/bulk")
async def document_permissions_bulk(
    payload: DocumentPermissionsBulkRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_internal_service),
) -> dict[int, dict[str, bool]]:
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    return await _get_bulk_document_permissions(session, user, payload.document_ids)



