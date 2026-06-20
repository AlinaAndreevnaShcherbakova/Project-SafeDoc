from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.postgres import get_session
from app.models import DocumentACL, Role, RoleName, RoleScope, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    cookie_token: str | None = Cookie(default=None, alias=settings.jwt_cookie_name),
    session: AsyncSession = Depends(get_session),
) -> User:
    #Авторизация поддерживает Bearer-токен и cookie, чтобы frontend работал без ручных заголовков.
    token_value = token or cookie_token
    if not token_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется аутентификация")

    subject = decode_token(token_value)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалидный токен")

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалидный токен") from exc

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")

    lock_until = _normalize_utc(user.lock_until)
    if lock_until and lock_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Учетная запись временно заблокирована")

    return user


async def get_user_role_names(
    user_id: int,
    session: AsyncSession,
    document_id: int | None = None,
) -> set[RoleName]:
    #Совместимый helper возвращает документные роли вместе с глобальными.
    global_rows = (
        await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
    ).scalars().all()
    result = set(global_rows)
    if document_id is not None:
        document_rows = (
            await session.execute(
                select(Role.name)
                .join(DocumentACL, DocumentACL.role_id == Role.id)
                .where(DocumentACL.user_id == user_id, DocumentACL.document_id == document_id)
            )
        ).scalars().all()
        result.update(document_rows)
    return result


async def get_global_role_names(user_id: int, session: AsyncSession) -> set[RoleName]:
    rows = (
        await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.scope.in_([RoleScope.COMPANY, RoleScope.DEPARTMENT]),
            )
        )
    ).scalars().all()
    return set(rows)


async def get_document_role_names(user_id: int, document_id: int, session: AsyncSession) -> set[RoleName]:
    rows = (
        await session.execute(
            select(Role.name)
            .join(DocumentACL, DocumentACL.role_id == Role.id)
            .where(
                DocumentACL.user_id == user_id,
                DocumentACL.document_id == document_id,
                Role.scope == RoleScope.DOCUMENT,
            )
        )
    ).scalars().all()
    return set(rows)


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Требуются права суперадминистратора")
    return current_user


async def require_internal_service(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    #Внутренние вызовы между сервисами защищаются отдельным служебным токеном.
    if x_internal_token != settings.internal_service_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недопустимый внутренний вызов")
