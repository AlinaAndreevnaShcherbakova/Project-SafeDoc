from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.core.security import hash_password
from app.db.postgres import get_session
from app.models import AccessRequest, Department, Document, DocumentACL, DocumentVersion, Folder, Position, PublicLink, Role, RoleName, User, UserRole, Worker
from app.schemas.users import UserCreate, UserPut, UserRead, UserUpdate, UsersBulkDelete
from app.services.audit import audit_bulk_extra, audit_bulk_result, audit_error_handler, audit_user_label, audit_user_labels, audit_user_object, safe_log_event
from app.services.notifications import audit_safe_send_notification, build_password_changed_email

router = APIRouter()


async def _audit_update_user_error_context(**kwargs) -> str:
    return f"{kwargs['current_user'].login} failed to update user {await audit_user_label(kwargs['session'], kwargs['user_id'])}"


async def _audit_replace_user_error_context(**kwargs) -> str:
    return f"{kwargs['current_user'].login} failed to replace user {await audit_user_label(kwargs['session'], kwargs['user_id'])}"


async def _audit_delete_user_error_context(**kwargs) -> str:
    return f"{kwargs['current_user'].login} failed to delete user {await audit_user_label(kwargs['session'], kwargs['user_id'])}"


async def _audit_bulk_delete_users_error_context(**kwargs) -> str:
    labels = await audit_user_labels(kwargs["session"], kwargs["payload"].user_ids)
    return f"{kwargs['current_user'].login} failed to bulk delete users: {labels}"


async def _get_or_create_department(session: AsyncSession, name: str) -> Department:
    department = (await session.execute(select(Department).where(Department.name == name.strip()))).scalar_one_or_none()
    if department is None:
        department = Department(name=name.strip())
        session.add(department)
        await session.flush()
    return department


async def _get_or_create_position(session: AsyncSession, name: str) -> Position:
    position = (await session.execute(select(Position).where(Position.name == name.strip()))).scalar_one_or_none()
    if position is None:
        position = Position(name=name.strip())
        session.add(position)
        await session.flush()
    return position


async def _set_worker_org(session: AsyncSession, user: User, department_name: str, position_name: str) -> None:
    department = await _get_or_create_department(session, department_name)
    position = await _get_or_create_position(session, position_name)
    user.worker.department_id = department.id
    user.worker.department_ref = department
    user.worker.position_id = position.id
    user.worker.position_ref = position


async def _is_access_manager(session: AsyncSession, user_id: int) -> bool:
    exists = (
        await session.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.name == RoleName.ACCESS_MANAGER)
        )
    ).scalar_one_or_none()
    return exists is not None


async def _set_access_manager_assignment(session: AsyncSession, user_id: int, enabled: bool) -> None:
    #Роль менеджера доступа хранится как глобальная роль без привязки к документу.
    rows = (
        await session.execute(
            select(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.name == RoleName.ACCESS_MANAGER)
        )
    ).scalars().all()

    if enabled:
        if not rows:
            role_id = select(Role.id).where(Role.name == RoleName.ACCESS_MANAGER).scalar_subquery()
            await session.execute(insert(UserRole).values(user_id=user_id, role_id=role_id))
        return

    for row in rows:
        await session.delete(row)


async def _serialize_user(session: AsyncSession, user: User) -> UserRead:
    role = "superadmin" if user.is_superadmin else ("access_manager" if await _is_access_manager(session, user.id) else "user")
    return _serialize_user_payload(user, role)


def _serialize_user_payload(user: User, role: str) -> UserRead:
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    return UserRead.model_validate(
        {
            "id": user.id,
            "login": _clean(user.login) or f"user_{user.id}",
            "surname": _clean(user.surname) or "-",
            "name": _clean(user.name) or "-",
            "middle_name": _clean(user.middle_name),
            "department": _clean(user.department),
            "position": _clean(user.position),
            "email": _clean(user.email) or f"user{user.id}@invalid.local",
            "is_superadmin": user.is_superadmin,
            "role": role,
        }
    )


async def _get_reassignment_user(session: AsyncSession, deleting_user_id: int) -> User:
    #Перед удалением пользователя все его объекты переводятся на менеджера доступа его отдела.
    deleting_user_department_id = (
        await session.execute(
            select(Worker.department_id)
            .join(User, User.worker_id == Worker.id)
            .where(User.id == deleting_user_id)
        )
    ).scalar_one_or_none()
    if deleting_user_department_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Отдел удаляемого пользователя не найден")

    reassignment_user = (
        await session.execute(
            select(User)
            .join(Worker, Worker.id == User.worker_id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.id != deleting_user_id,
                Worker.department_id == deleting_user_department_id,
                Role.name == RoleName.ACCESS_MANAGER,
            )
            .order_by(User.login.asc(), User.id.asc())
        )
    ).scalars().first()
    if reassignment_user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В отделе удаляемого пользователя не найден менеджер доступа для переноса данных")
    return reassignment_user


async def _reassign_user_data(session: AsyncSession, user_id: int, reassigned_to_user_id: int) -> None:
    await session.execute(update(Document).where(Document.owner_id == user_id).values(owner_id=reassigned_to_user_id))
    await session.execute(update(DocumentVersion).where(DocumentVersion.author_id == user_id).values(author_id=reassigned_to_user_id))
    await session.execute(update(PublicLink).where(PublicLink.created_by_id == user_id).values(created_by_id=reassigned_to_user_id))
    await session.execute(update(Folder).where(Folder.owner_id == user_id).values(owner_id=reassigned_to_user_id))


async def _clear_nullable_user_refs(session: AsyncSession, user_id: int) -> None:
    resolved_requests = (
        await session.execute(select(AccessRequest).where(AccessRequest.resolved_by_id == user_id))
    ).scalars().all()
    for request in resolved_requests:
        request.resolved_by_id = None


@router.post("", response_model=UserRead)
@audit_error_handler("users", lambda **kwargs: f"{kwargs['current_user'].login} failed to create user {kwargs['payload'].login}")
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_superadmin),
) -> UserRead:
    #Создание новых суперадминистраторов через интерфейс пользователей запрещено явно.
    requested_role = payload.role or ("superadmin" if payload.is_superadmin else "user")
    if requested_role == "superadmin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Создание пользователей с правами суперадмина запрещено",
        )
    if requested_role == "access_manager" and not payload.department.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для менеджера доступа необходимо указать отдел ответственности",
        )

    exists = (
        await session.execute(
            select(User)
            .join(Worker, Worker.id == User.worker_id)
            .where((User.login == payload.login) | (Worker.email == str(payload.email)))
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пользователь с таким логином или email уже существует")

    department = await _get_or_create_department(session, payload.department)
    position = await _get_or_create_position(session, payload.position)
    worker = Worker(
        surname=payload.surname,
        name=payload.name,
        middle_name=payload.middle_name,
        department_id=department.id,
        position_id=position.id,
        email=str(payload.email),
    )
    session.add(worker)
    await session.flush()

    user = User(
        login=payload.login,
        password_hash=hash_password(payload.password),
        worker_id=worker.id,
        is_superadmin=False,
    )
    session.add(user)
    await session.flush()

    if requested_role == "access_manager":
        await _set_access_manager_assignment(session, user.id, enabled=True)

    await session.commit()
    await session.refresh(user)
    await safe_log_event("users", audit_user_object(current_user), f"created user {user.login}", "success")
    return await _serialize_user(session, user)


@router.get("", response_model=list[UserRead])
async def list_users(
    query: str | None = Query(None, max_length=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_superadmin),
) -> list[UserRead]:
    users_query = select(User).join(Worker, Worker.id == User.worker_id).join(Department, Department.id == Worker.department_id).join(Position, Position.id == Worker.position_id)
    text_query = (query or "").strip()
    if text_query:
        pattern = f"%{text_query}%"
        users_query = users_query.where(
            or_(
                User.login.ilike(pattern),
                Worker.surname.ilike(pattern),
                Worker.name.ilike(pattern),
                Worker.middle_name.ilike(pattern),
                Department.name.ilike(pattern),
                Position.name.ilike(pattern),
                Worker.email.ilike(pattern),
            )
        )
    users = (await session.execute(users_query.order_by(User.id))).scalars().all()
    access_manager_ids = set(
        (
            await session.execute(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name == RoleName.ACCESS_MANAGER)
            )
        ).scalars().all()
    )
    return [
        _serialize_user_payload(user, "superadmin" if user.is_superadmin else ("access_manager" if user.id in access_manager_ids else "user"))
        for user in users
    ]


@router.patch("/{user_id}", response_model=UserRead)
@audit_error_handler("users", _audit_update_user_error_context)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_superadmin),
) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    if payload.is_superadmin is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя изменять флаг суперадминистратора",
        )

    password_changed = False
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "password" and value is not None:
            user.password_hash = hash_password(value)
            password_changed = True
        elif field == "department" and value is not None:
            await _set_worker_org(session, user, value, user.position)
        elif field == "position" and value is not None:
            await _set_worker_org(session, user, user.department, value)
        elif value is not None:
            setattr(user, field, value)

    await session.commit()
    await session.refresh(user)
    if password_changed:
        await audit_safe_send_notification(
            user.email,
            build_password_changed_email(current_user, user),
        )
    await safe_log_event("users", audit_user_object(current_user), f"updated user {user.login}", "success")
    return await _serialize_user(session, user)


@router.put("/{user_id}", response_model=UserRead)
@audit_error_handler("users", _audit_replace_user_error_context)
async def replace_user(
    user_id: int,
    payload: UserPut,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_superadmin),
) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    duplicate = (
        await session.execute(
            select(User).where(
                User.id != user_id,
                User.login == payload.login,
            )
        )
    ).scalar_one_or_none()
    duplicate_email = (
        await session.execute(
            select(User)
            .join(Worker, Worker.id == User.worker_id)
            .where(User.id != user_id, Worker.email == str(payload.email))
        )
    ).scalar_one_or_none()
    if duplicate is not None or duplicate_email is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пользователь с таким логином или email уже существует")

    requested_role = payload.role or ("superadmin" if user.is_superadmin else ("access_manager" if await _is_access_manager(session, user.id) else "user"))
    requested_superadmin = requested_role == "superadmin"
    if requested_role == "access_manager" and not payload.department.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для менеджера доступа необходимо указать отдел ответственности",
        )
    superadmins = (await session.execute(select(User).where(User.is_superadmin.is_(True)))).scalars().all()
    current_superadmin_ids = {row.id for row in superadmins}

    if requested_superadmin and user_id not in current_superadmin_ids and current_superadmin_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В системе уже существует суперадминистратор")

    if not requested_superadmin and user_id in current_superadmin_ids and len(current_superadmin_ids) == 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В системе должен оставаться ровно один суперадминистратор")

    user.login = payload.login
    user.surname = payload.surname
    user.name = payload.name
    user.middle_name = payload.middle_name
    await _set_worker_org(session, user, payload.department, payload.position)
    user.email = str(payload.email)
    user.is_superadmin = requested_superadmin
    await _set_access_manager_assignment(session, user.id, enabled=(requested_role == "access_manager"))
    password_changed = False
    if payload.password:
        user.password_hash = hash_password(payload.password)
        password_changed = True

    await session.commit()
    await session.refresh(user)
    if password_changed:
        await audit_safe_send_notification(
            user.email,
            build_password_changed_email(current_user, user),
        )
    await safe_log_event("users", audit_user_object(current_user), f"replaced user {user.login}", "success")
    return await _serialize_user(session, user)


@router.delete("/{user_id}")
@audit_error_handler("users", _audit_delete_user_error_context)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_superadmin),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    if user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пользователя-суперадмина нельзя удалить")

    reassignment_user = await _get_reassignment_user(session, user_id)
    await _reassign_user_data(session, user_id, reassignment_user.id)

    await _clear_nullable_user_refs(session, user_id)

    try:
        await session.delete(user)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невозможно удалить пользователя из-за связанных данных")

    await safe_log_event("users", audit_user_object(current_user), f"deleted user {user.login}", "success")
    await safe_log_event(
        "users",
        audit_user_object(current_user),
        f"reassigned deleted user {user.login} data to {reassignment_user.login}",
        "success",
    )
    return {"status": "ok"}


@router.post("/bulk-delete")
@audit_error_handler("users", _audit_bulk_delete_users_error_context)
async def bulk_delete_users(
    payload: UsersBulkDelete,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_superadmin),
) -> dict:
    processed: list[int] = []
    processed_logins: list[str] = []
    skipped: list[dict] = []

    for user_id in payload.user_ids:
        user = await session.get(User, user_id)
        if user is None:
            skipped.append({"id": user_id, "reason": "Пользователь не найден"})
            continue
        if user.is_superadmin:
            skipped.append({"id": user_id, "reason": "Пользователя-суперадмина нельзя удалить"})
            continue

        reassignment_user = await _get_reassignment_user(session, user_id)
        await _reassign_user_data(session, user_id, reassignment_user.id)

        await _clear_nullable_user_refs(session, user_id)

        await session.delete(user)
        processed.append(user_id)
        processed_logins.append(user.login)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невозможно удалить одного или нескольких пользователей из-за связанных данных")

    if processed or skipped:
        await safe_log_event(
            "users",
            audit_user_object(current_user),
            f"bulk deleted users: {', '.join(processed_logins)}",
            audit_bulk_result(processed, skipped),
            audit_bulk_extra(skipped),
        )
    return {"processed": processed, "skipped": skipped}


