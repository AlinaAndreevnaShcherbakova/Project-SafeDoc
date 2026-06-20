from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_global_role_names
from app.core.config import settings
from app.db.postgres import get_session
from app.models import (
    AccessRequest,
    AccessRequestStatus,
    Document,
    DocumentACL,
    DocumentVersion,
    Folder,
    PublicLink,
    Role,
    RoleName,
    User,
    Visibility,
    Worker,
)
from app.schemas.documents import (
    DocumentBulkDelete,
    DocumentBulkMove,
    DocumentCatalogRead,
    DocumentMove,
    DocumentRead,
    DocumentVisibilityUpdate,
    FolderCreate,
    FolderRead,
    FolderUpdate,
    VersionRead,
)
from app.services.audit import audit_bulk_extra, audit_bulk_result, audit_document_label, audit_document_labels, audit_document_object, audit_error_handler, audit_folder_label, audit_folder_object, audit_user_object, safe_log_event
from app.services.access_client import get_document_permissions, get_documents_permissions
from app.services.storage import storage_service
from app.services.preview import preview_service

router = APIRouter()
REPLACE_EXISTING_DOCUMENT_MESSAGE = "Файл с таким именем уже был загружен в систему. Заменить текущую версию? При необходимости вы сможете ее восстановить"


async def _audit_update_folder_error_context(**kwargs) -> str:
    return f"{kwargs['current_user'].login} failed to update folder {await audit_folder_label(kwargs['session'], kwargs['folder_id'])}"


async def _audit_delete_folder_error_context(**kwargs) -> str:
    return f"{kwargs['current_user'].login} failed to delete folder {await audit_folder_label(kwargs['session'], kwargs['folder_id'])}"


async def _audit_document_error_context(action: str, **kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["document_id"])
    return f"{kwargs['current_user'].login} failed to {action} {document}"


async def _audit_bulk_move_documents_error_context(**kwargs) -> str:
    documents = await audit_document_labels(kwargs["session"], kwargs["payload"].document_ids)
    return f"{kwargs['current_user'].login} failed to bulk move documents: {documents}"


async def _audit_bulk_delete_documents_error_context(**kwargs) -> str:
    documents = await audit_document_labels(kwargs["session"], kwargs["payload"].document_ids)
    return f"{kwargs['current_user'].login} failed to bulk delete documents: {documents}"


async def _audit_restore_version_error_context(**kwargs) -> str:
    document = await audit_document_label(kwargs["session"], kwargs["document_id"])
    return f"{kwargs['current_user'].login} failed to restore version {kwargs['version']} for {document}"


def _build_content_disposition(filename: str) -> str:
    fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


async def _get_remote_document_permissions(document_id: int, user_id: int) -> dict[str, bool]:
    try:
        return await get_document_permissions(document_id, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис контроля доступа недоступен",
        ) from exc


async def _can_read_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    permissions = await _get_remote_document_permissions(document.id, current_user.id)
    return permissions["can_read"]


async def _can_write_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    permissions = await _get_remote_document_permissions(document.id, current_user.id)
    return permissions["can_write"]


async def _can_download_document(session: AsyncSession, current_user: User, document: Document) -> bool:
    permissions = await _get_remote_document_permissions(document.id, current_user.id)
    return permissions.get("can_download", permissions["can_write"])


async def can_manage_document_access(session: AsyncSession, current_user: User, document: Document) -> bool:
    permissions = await _get_remote_document_permissions(document.id, current_user.id)
    return permissions["can_manage_access"]


async def _get_remote_documents_permissions(document_ids: list[int], user_id: int) -> dict[int, dict[str, bool]]:
    try:
        return await get_documents_permissions(document_ids, user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис контроля доступа недоступен",
        ) from exc


async def _get_folder_maps(session: AsyncSession, doc_ids: list[int]) -> tuple[dict[int, int], dict[int, str]]:
    if not doc_ids:
        return {}, {}
    docs = (await session.execute(select(Document.id, Document.folder_id).where(Document.id.in_(doc_ids)))).all()
    doc_to_folder = {row.id: row.folder_id for row in docs if row.folder_id is not None}
    folder_ids = list({row.folder_id for row in docs if row.folder_id is not None})
    folder_map = {}
    if folder_ids:
        try:
            folders = (await session.execute(select(Folder).where(Folder.id.in_(folder_ids)))).scalars().all()
            folder_map = {folder.id: folder.name for folder in folders}
        except Exception:
            folder_map = {}
    return doc_to_folder, folder_map


async def _get_active_public_link_doc_ids(
    session: AsyncSession,
    docs: list[Document],
    current_user: User,
    global_roles: set[RoleName] | None = None,
) -> set[int]:
    doc_ids = [doc.id for doc in docs]
    if not doc_ids:
        return set()

    roles = global_roles if global_roles is not None else await get_global_role_names(current_user.id, session)
    if current_user.is_superadmin or RoleName.SUPERADMIN in roles:
        visible_doc_ids = set(doc_ids)
    elif RoleName.ACCESS_MANAGER in roles:
        visible_doc_ids = set(
            (
                await session.execute(
                    select(Document.id)
                    .join(User, User.id == Document.owner_id)
                    .join(Worker, Worker.id == User.worker_id)
                    .where(Document.id.in_(doc_ids), Worker.department_id == current_user.worker.department_id)
                )
            ).scalars().all()
        )
    else:
        visible_doc_ids = {doc.id for doc in docs if doc.owner_id == current_user.id}

    if not visible_doc_ids:
        return set()

    return set(
        (
            await session.execute(
                select(PublicLink.document_id)
                .where(
                    PublicLink.document_id.in_(list(visible_doc_ids)),
                    PublicLink.revoked_at.is_(None),
                    PublicLink.expires_at > datetime.now(timezone.utc),
                )
                .distinct()
            )
        ).scalars().all()
    )


async def _serialize_document(session: AsyncSession, doc: Document, current_user: User | None = None) -> DocumentRead:
    doc_to_folder, folder_map = await _get_folder_maps(session, [doc.id])
    folder_id = doc_to_folder.get(doc.id)
    owner = await session.get(User, doc.owner_id)
    owner_full_name = None
    if owner is not None:
        owner_full_name = " ".join(part for part in [owner.surname, owner.name, owner.middle_name] if part).strip() or owner.login
    can_download = await _can_download_document(session, current_user, doc) if current_user is not None else False
    can_write = await _can_write_document(session, current_user, doc) if current_user is not None else False
    active_public_link_doc_ids = await _get_active_public_link_doc_ids(session, [doc], current_user) if current_user is not None else set()
    return DocumentRead.model_validate(doc).model_copy(
        update={
            "owner_login": owner.login if owner else None,
            "owner_full_name": owner_full_name,
            "folder_id": folder_id,
            "folder_name": folder_map.get(folder_id) if folder_id else None,
            "can_download": can_download,
            "can_write": can_write,
            "has_active_public_links": doc.id in active_public_link_doc_ids,
        }
    )


async def _find_duplicate_in_folder(
    session: AsyncSession,
    *,
    owner_id: int,
    document_name: str,
    folder_id: int | None,
    exclude_document_id: int,
) -> Document | None:
    #Дубликат определяется внутри папки владельца, поэтому одинаковые имена допустимы в разных папках.
    return (
        await session.execute(
            select(Document).where(
                Document.deleted_at.is_(None),
                Document.owner_id == owner_id,
                Document.name == document_name,
                Document.folder_id == folder_id,
                Document.id != exclude_document_id,
            )
        )
    ).scalar_one_or_none()


async def _replace_document_with_duplicate(
    session: AsyncSession,
    *,
    source_document: Document,
    target_document: Document,
    author_id: int,
) -> Document:
    now = datetime.now(timezone.utc)
    next_version = target_document.current_version + 1

    target_document.storage_key = source_document.storage_key
    target_document.size_bytes = source_document.size_bytes
    target_document.mime = source_document.mime
    target_document.current_version = next_version
    target_document.updated_at = now

    session.add(
        DocumentVersion(
            document_id=target_document.id,
            version=next_version,
            author_id=author_id,
            comment=source_document.comment,
            storage_key=source_document.storage_key,
        )
    )

    source_document.deleted_at = now
    source_document.folder_id = None

    return target_document


@router.get("/folders", response_model=list[FolderRead])
async def list_folders(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FolderRead]:
    try:
        rows = (
            await session.execute(
                select(Folder).where(Folder.owner_id == current_user.id).order_by(Folder.parent_id.nullsfirst(), Folder.name.asc())
            )
        ).scalars().all()
        return [FolderRead.model_validate(row) for row in rows]
    except Exception:
        #Отсутствие структуры папок не должно ломать загрузку страницы.
        return []


@router.post("/folders", response_model=FolderRead)
@audit_error_handler("folder", lambda **kwargs: f"{kwargs['current_user'].login} failed to create folder \"{kwargs['payload'].name}\"")
async def create_folder(
    payload: FolderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderRead:
    parent_id = payload.parent_id
    if parent_id is not None:
        try:
            parent = await session.get(Folder, parent_id)
        except Exception:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская папка не найдена")
        if parent is None or parent.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская папка не найдена")

    try:
        duplicate = (
            await session.execute(
                select(Folder).where(
                    Folder.owner_id == current_user.id,
                    Folder.parent_id == parent_id,
                    Folder.name == payload.name.strip(),
                )
            )
        ).scalar_one_or_none()
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка доступа к БД при создании папки")
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Папка с таким именем уже существует")

    folder = Folder(name=payload.name.strip(), parent_id=parent_id, owner_id=current_user.id)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    await safe_log_event("folder", audit_user_object(current_user), f"{current_user.login} created folder {audit_folder_object(folder)}", "success")
    return FolderRead.model_validate(folder)


@router.patch("/folders/{folder_id}", response_model=FolderRead)
@audit_error_handler("folder", _audit_update_folder_error_context)
async def update_folder(
    folder_id: int,
    payload: FolderUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderRead:
    folder = await session.get(Folder, folder_id)
    if folder is None or folder.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")

    parent_id = payload.parent_id
    if parent_id == folder.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Папка не может быть родителем самой себя")

    if parent_id is not None:
        parent = await session.get(Folder, parent_id)
        if parent is None or parent.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская папка не найдена")

    duplicate = (
        await session.execute(
            select(Folder).where(
                Folder.owner_id == current_user.id,
                Folder.parent_id == parent_id,
                Folder.name == payload.name.strip(),
                Folder.id != folder.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Папка с таким именем уже существует")

    folder.name = payload.name.strip()
    folder.parent_id = parent_id
    await session.commit()
    await session.refresh(folder)

    await safe_log_event("folder", audit_user_object(current_user), f"{current_user.login} updated folder {audit_folder_object(folder)}", "success")
    return FolderRead.model_validate(folder)


@router.delete("/folders/{folder_id}")
@audit_error_handler("folder", _audit_delete_folder_error_context)
async def delete_folder(
    folder_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    folder = await session.get(Folder, folder_id)
    if folder is None or folder.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")

    has_children = (
        await session.execute(select(Folder.id).where(Folder.parent_id == folder_id).limit(1))
    ).scalar_one_or_none()
    if has_children is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала удалите вложенные папки")

    has_documents = (
        await session.execute(select(Document.id).where(Document.folder_id == folder_id, Document.deleted_at.is_(None)).limit(1))
    ).scalar_one_or_none()
    if has_documents is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала переместите или удалите документы из папки")

    await session.delete(folder)
    await session.commit()
    await safe_log_event("folder", audit_user_object(current_user), f"{current_user.login} deleted folder {audit_folder_object(folder)}", "success")
    return {"status": "ok"}


@router.get("/catalog", response_model=list[DocumentCatalogRead])
async def catalog_documents(
    search: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[DocumentCatalogRead]:
    try:
        query = (
            select(
                Document,
                User.login.label("owner_login"),
                Worker.surname.label("owner_surname"),
                Worker.name.label("owner_name"),
                Worker.middle_name.label("owner_middle_name"),
                Folder.name.label("folder_name"),
                Folder.id.label("folder_id"),
            )
            .outerjoin(User, User.id == Document.owner_id)
            .outerjoin(Worker, Worker.id == User.worker_id)
            .outerjoin(Folder, Folder.id == Document.folder_id)
            .where(Document.deleted_at.is_(None))
        )
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(Document.name.ilike(pattern))
        rows = (await session.execute(query.order_by(Document.name.asc()))).all()
        docs = [row[0] for row in rows]
    except Exception:
        #Каталог отдает пустой список вместо ошибки, чтобы основной интерфейс оставался доступным.
        return []

    try:
        pending_doc_ids = set(
            (
                await session.execute(
                    select(AccessRequest.document_id).where(
                        AccessRequest.requester_id == current_user.id,
                        AccessRequest.status == AccessRequestStatus.PENDING,
                    )
                )
            ).scalars().all()
        )
    except Exception:
        pending_doc_ids = set()

    row_by_doc_id = {row[0].id: row for row in rows}
    global_roles = await get_global_role_names(current_user.id, session)
    active_public_link_doc_ids = await _get_active_public_link_doc_ids(session, docs, current_user, global_roles)
    permissions_by_doc_id = await _get_remote_documents_permissions([doc.id for doc in docs], current_user.id)

    result: list[DocumentCatalogRead] = []
    for doc in docs:
        permissions = permissions_by_doc_id.get(doc.id, {})
        has_access = permissions.get("can_read", False)
        can_download = permissions.get("can_download", permissions.get("can_write", False))
        can_write = permissions.get("can_write", False)
        can_manage_access = permissions.get("can_manage_access", False)
        can_request = doc.owner_id != current_user.id and not has_access and doc.id not in pending_doc_ids
        row = row_by_doc_id.get(doc.id)
        folder_id = row.folder_id if row else None
        result.append(
            DocumentCatalogRead(
                id=doc.id,
                name=doc.name,
                owner_id=doc.owner_id,
                owner_login=row.owner_login if row else None,
                owner_full_name=(
                    " ".join(part for part in [row.owner_surname, row.owner_name, row.owner_middle_name] if part).strip() or row.owner_login
                ) if row else None,
                current_version=doc.current_version,
                folder_id=folder_id,
                folder_name=row.folder_name if row else None,
                visibility=doc.visibility,
                has_access=has_access,
                can_request=can_request,
                can_download=can_download,
                can_write=can_write,
                can_manage_access=can_manage_access,
                has_active_public_links=doc.id in active_public_link_doc_ids,
            )
        )
    return result


@router.post("", response_model=DocumentRead)
@audit_error_handler("document", lambda **kwargs: f"{kwargs['current_user'].login} failed to upload document \"{kwargs['file'].filename}\"")
async def upload_document(
    file: UploadFile = File(...),
    visibility: Visibility = Form(Visibility.BY_REQUEST),
    comment: str | None = Form(None),
    folder_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    storage_key, file_size = await storage_service.upload_stream(
        file,
        metadata={"owner_id": current_user.id, "version": 1},
        max_size=settings.max_file_size_bytes,
    )

    doc = Document(
        name=file.filename,
        owner_id=current_user.id,
        comment=comment,
        mime=file.content_type or "application/octet-stream",
        size_bytes=file_size,
        storage_key=storage_key,
        visibility=visibility,
        current_version=1,
        folder_id=folder_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    await session.flush()

    if folder_id is not None:
        folder = await session.get(Folder, folder_id)
        if folder is None or folder.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")
        doc.folder_id = folder.id

    owner_role = (await session.execute(select(Role).where(Role.name == RoleName.OWNER))).scalar_one()
    existing_owner_acl = (
        await session.execute(
            select(DocumentACL).where(
                and_(DocumentACL.user_id == current_user.id, DocumentACL.role_id == owner_role.id, DocumentACL.document_id == doc.id)
            )
        )
    ).scalar_one_or_none()
    if existing_owner_acl is None:
        session.add(DocumentACL(user_id=current_user.id, role_id=owner_role.id, document_id=doc.id))

    session.add(
        DocumentVersion(
            document_id=doc.id,
            version=1,
            author_id=current_user.id,
            comment=comment,
            storage_key=storage_key,
        )
    )
    await session.commit()
    await session.refresh(doc)

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} uploaded document {audit_document_object(doc)}", "success")
    return await _serialize_document(session, doc, current_user)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    search: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[DocumentRead]:
    query = select(Document).where(Document.deleted_at.is_(None))
    if search:
        query = query.where(Document.name.ilike(f"%{search}%"))

    docs = (await session.execute(query.order_by(Document.updated_at.desc()))).scalars().all()
    doc_to_folder, folder_map = await _get_folder_maps(session, [doc.id for doc in docs])
    global_roles = await get_global_role_names(current_user.id, session)
    active_public_link_doc_ids = await _get_active_public_link_doc_ids(session, docs, current_user, global_roles)
    permissions_by_doc_id = await _get_remote_documents_permissions([doc.id for doc in docs], current_user.id)
    owner_ids = sorted({doc.owner_id for doc in docs})
    owner_map: dict[int, tuple[str | None, str | None]] = {}
    if owner_ids:
        owner_rows = (
            await session.execute(
                select(User.id, User.login, Worker.surname, Worker.name, Worker.middle_name)
                .join(Worker, Worker.id == User.worker_id)
                .where(User.id.in_(owner_ids))
            )
        ).all()
        owner_map = {
            row.id: (
                row.login,
                " ".join(part for part in [row.surname, row.name, row.middle_name] if part).strip() or row.login,
            )
            for row in owner_rows
        }

    result: list[DocumentRead] = []
    for doc in docs:
        permissions = permissions_by_doc_id.get(doc.id, {})
        if permissions.get("can_read", False):
            folder_id = doc_to_folder.get(doc.id)
            result.append(
                DocumentRead.model_validate(doc).model_copy(
                    update={
                        "owner_login": owner_map.get(doc.owner_id, (None, None))[0],
                        "owner_full_name": owner_map.get(doc.owner_id, (None, None))[1],
                        "folder_id": folder_id,
                        "folder_name": folder_map.get(folder_id) if folder_id else None,
                        "can_download": permissions.get("can_download", permissions.get("can_write", False)),
                        "can_write": permissions.get("can_write", False),
                        "has_active_public_links": doc.id in active_public_link_doc_ids,
                    }
                )
            )
    return result


@router.get("/{document_id}/download")
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("download", **kwargs))
async def download_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_download_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к документу")

    try:
        data = await storage_service.download(doc.storage_key)
    except FileNotFoundError as exc:
        await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} failed to download {audit_document_object(doc)}: file not found in storage", "error", str(exc))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл документа не найден в хранилище") from exc
    except ValueError as exc:
        await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} failed to download {audit_document_object(doc)}: invalid storage key", "error", str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Поврежден ключ хранения документа") from exc

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} downloaded {audit_document_object(doc)}", "success")
    return Response(content=data, media_type=doc.mime, headers={"Content-Disposition": _build_content_disposition(doc.name)})


@router.get("/{document_id}/preview")
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("open preview for", **kwargs))
async def preview_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_read_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к документу")

    data = await storage_service.download(doc.storage_key)
    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} opened preview for {audit_document_object(doc)}", "success")
    return await preview_service.build_preview_response(data=data, filename=doc.name)


@router.post("/{document_id}/versions", response_model=VersionRead)
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("upload new version for", **kwargs))
async def upload_new_version(
    document_id: int,
    file: UploadFile = File(...),
    comment: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> VersionRead:
    #Новая версия заменяет текущий файл, но история версий остается доступной для восстановления.
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_write_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для редактирования")

    new_version = doc.current_version + 1
    storage_key, file_size = await storage_service.upload_stream(
        file,
        metadata={"doc_id": doc.id, "version": new_version},
        max_size=settings.max_file_size_bytes,
    )

    doc.storage_key = storage_key
    doc.size_bytes = file_size
    doc.mime = file.content_type or "application/octet-stream"
    doc.current_version = new_version
    doc.updated_at = datetime.now(timezone.utc)

    version = DocumentVersion(
        document_id=doc.id,
        version=new_version,
        author_id=current_user.id,
        comment=comment,
        storage_key=storage_key,
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} uploaded version {new_version} for {audit_document_object(doc)}", "success")
    return VersionRead.model_validate(version)


@router.get("/{document_id}/versions", response_model=list[VersionRead])
async def list_versions(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[VersionRead]:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_read_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к документу")

    versions = (
        await session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.version.desc())
        )
    ).scalars().all()
    author_ids = sorted({version.author_id for version in versions})
    author_map: dict[int, str] = {}
    if author_ids:
        author_rows = (await session.execute(select(User.id, User.login).where(User.id.in_(author_ids)))).all()
        author_map = {
            row.id: row.login
            for row in author_rows
        }

    return [
        VersionRead.model_validate(version).model_copy(update={"author_full_name": author_map.get(version.author_id)})
        for version in versions
    ]


@router.patch("/{document_id}/rename", response_model=DocumentRead)
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("rename", **kwargs))
async def rename_document(
    document_id: int,
    name: str = Form(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_write_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    doc.name = name
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(doc)

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} renamed document to {audit_document_object(doc)}", "success")
    return await _serialize_document(session, doc, current_user)


@router.patch("/{document_id}/visibility", response_model=DocumentRead)
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("change visibility for", **kwargs))
async def update_document_visibility(
    document_id: int,
    payload: DocumentVisibilityUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Изменять уровень доступа может только владелец")

    doc.visibility = payload.visibility
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(doc)

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} changed visibility of {audit_document_object(doc)} to {payload.visibility.value}", "success")
    return await _serialize_document(session, doc, current_user)


@router.post("/{document_id}/move", response_model=DocumentRead)
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("move", **kwargs))
async def move_document(
    document_id: int,
    payload: DocumentMove,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if doc.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Перемещать можно только свои документы")

    target_folder_id = payload.folder_id
    target_folder_name = None
    if target_folder_id is not None:
        folder = await session.get(Folder, target_folder_id)
        if folder is None or folder.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")
        target_folder_name = folder.name

    duplicate_document = await _find_duplicate_in_folder(
        session,
        owner_id=current_user.id,
        document_name=doc.name,
        folder_id=target_folder_id,
        exclude_document_id=doc.id,
    )
    if duplicate_document is not None:
        if not payload.replace_existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=REPLACE_EXISTING_DOCUMENT_MESSAGE)

        duplicate_document = await _replace_document_with_duplicate(
            session,
            source_document=doc,
            target_document=duplicate_document,
            author_id=current_user.id,
        )
        await session.commit()
        await session.refresh(duplicate_document)
        await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} moved {audit_document_object(doc)} and replaced existing {audit_document_object(duplicate_document)}", "success")
        return await _serialize_document(session, duplicate_document, current_user)

    doc.folder_id = target_folder_id
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(doc)
    target_description = f'to folder "{target_folder_name}"' if target_folder_name is not None else "to root"
    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} moved {audit_document_object(doc)} {target_description}", "success")
    return await _serialize_document(session, doc, current_user)


@router.delete("/{document_id}")
@audit_error_handler("document", lambda **kwargs: _audit_document_error_context("delete", **kwargs))
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_write_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    doc.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} deleted {audit_document_object(doc)}", "success")
    return {"status": "ok"}


@router.post("/move/bulk")
@audit_error_handler("document", _audit_bulk_move_documents_error_context)
async def bulk_move_documents(
    payload: DocumentBulkMove,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    processed: list[int] = []
    processed_names: list[str] = []
    skipped: list[dict] = []

    target_folder_id = payload.folder_id
    if target_folder_id is not None:
        folder = await session.get(Folder, target_folder_id)
        if folder is None or folder.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Папка не найдена")

    for document_id in payload.document_ids:
        doc = await session.get(Document, document_id)
        if doc is None or doc.deleted_at is not None:
            skipped.append({"id": document_id, "reason": "Документ не найден"})
            continue
        if doc.owner_id != current_user.id:
            skipped.append({"id": document_id, "reason": "Перемещать можно только свои документы"})
            continue

        duplicate_document = await _find_duplicate_in_folder(
            session,
            owner_id=current_user.id,
            document_name=doc.name,
            folder_id=target_folder_id,
            exclude_document_id=doc.id,
        )
        if duplicate_document is not None:
            if not payload.replace_existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=REPLACE_EXISTING_DOCUMENT_MESSAGE)

            await _replace_document_with_duplicate(
                session,
                source_document=doc,
                target_document=duplicate_document,
                author_id=current_user.id,
            )
            processed.append(document_id)
            processed_names.append(doc.name)
            continue

        doc.folder_id = target_folder_id
        doc.updated_at = datetime.now(timezone.utc)
        processed.append(document_id)
        processed_names.append(doc.name)

    await session.commit()
    if processed or skipped:
        await safe_log_event(
            "document",
            audit_user_object(current_user),
            f"{current_user.login} bulk moved documents: {', '.join(processed_names)}",
            audit_bulk_result(processed, skipped),
            audit_bulk_extra(skipped),
        )
    return {"processed": processed, "skipped": skipped}


@router.post("/bulk/delete")
@audit_error_handler("document", _audit_bulk_delete_documents_error_context)
async def bulk_delete_documents(
    payload: DocumentBulkDelete,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    processed: list[int] = []
    processed_names: list[str] = []
    skipped: list[dict] = []

    for document_id in payload.document_ids:
        doc = await session.get(Document, document_id)
        if doc is None or doc.deleted_at is not None:
            skipped.append({"id": document_id, "reason": "Документ не найден"})
            continue
        if not await _can_write_document(session, current_user, doc):
            skipped.append({"id": document_id, "reason": "Недостаточно прав"})
            continue

        doc.deleted_at = datetime.now(timezone.utc)
        processed.append(document_id)
        processed_names.append(doc.name)

    await session.commit()
    if processed or skipped:
        await safe_log_event(
            "document",
            audit_user_object(current_user),
            f"{current_user.login} bulk deleted documents: {', '.join(processed_names)}",
            audit_bulk_result(processed, skipped),
            audit_bulk_extra(skipped),
        )
    return {"processed": processed, "skipped": skipped}


@router.post("/{document_id}/restore/{version}", response_model=DocumentRead)
@audit_error_handler("document", _audit_restore_version_error_context)
async def restore_version(
    document_id: int,
    version: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    if not await _can_write_document(session, current_user, doc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    target_version = (
        await session.execute(
            select(DocumentVersion).where(
                and_(DocumentVersion.document_id == document_id, DocumentVersion.version == version)
            )
        )
    ).scalar_one_or_none()
    if target_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версия не найдена")
    if target_version.version == doc.current_version:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущую версию нельзя восстанавливать")

    doc.storage_key = target_version.storage_key
    doc.current_version = target_version.version
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(doc)

    await safe_log_event("document", audit_user_object(current_user), f"{current_user.login} restored version {version} for {audit_document_object(doc)}", "success")
    return await _serialize_document(session, doc, current_user)
