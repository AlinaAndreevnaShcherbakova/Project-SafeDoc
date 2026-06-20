from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_global_role_names
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.postgres import get_session
from app.models import RoleName, User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse, UpdateProfileRequest
from app.schemas.users import UserRead
from app.services.audit import audit_error_handler, audit_user_object, safe_log_event
from app.services.notifications import audit_safe_send_notification, build_password_changed_email

router = APIRouter()

MAX_FAILED_LOGINS = 3
LOCKOUT_MINUTES = 10
MAX_LOGIN_ATTEMPTS_PER_IP = 20
LOGIN_IP_WINDOW_MINUTES = 10

_IP_LOGIN_FAILURES: dict[str, list[datetime]] = {}


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_lock_detail(lock_until: datetime, now: datetime) -> dict:
    lock_until_utc = _normalize_utc(lock_until) or now
    remaining_seconds = max(1, ceil((lock_until_utc - now).total_seconds()))
    return {
        "message": "Форма входа заблокирована на 10 минут",
        "remaining_seconds": remaining_seconds,
        "lock_until": lock_until_utc.isoformat(),
    }


def _get_request_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def _cleanup_ip_window(ip: str, now: datetime) -> list[datetime]:
    threshold = now - timedelta(minutes=LOGIN_IP_WINDOW_MINUTES)
    recent = [stamp for stamp in _IP_LOGIN_FAILURES.get(ip, []) if stamp >= threshold]
    _IP_LOGIN_FAILURES[ip] = recent
    return recent


def _register_ip_login_failure(ip: str, now: datetime) -> None:
    recent = _cleanup_ip_window(ip, now)
    recent.append(now)
    _IP_LOGIN_FAILURES[ip] = recent


def _clear_ip_login_failures(ip: str) -> None:
    _IP_LOGIN_FAILURES.pop(ip, None)


def _assert_ip_not_rate_limited(ip: str, now: datetime) -> None:
    #Ограничение по IP снижает риск перебора паролей до проверки учетной записи.
    recent = _cleanup_ip_window(ip, now)
    if len(recent) >= MAX_LOGIN_ATTEMPTS_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Повторите позже.",
        )


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        httponly=True,
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        domain=settings.jwt_cookie_domain,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.jwt_cookie_name,
        domain=settings.jwt_cookie_domain,
        path="/",
        samesite=settings.jwt_cookie_samesite,
        secure=settings.jwt_cookie_secure,
    )


async def _serialize_user(session: AsyncSession, user: User) -> UserRead:
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    global_roles = await get_global_role_names(user.id, session)
    role = "superadmin" if user.is_superadmin else ("access_manager" if RoleName.ACCESS_MANAGER in global_roles else "user")
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


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    now = datetime.now(timezone.utc)
    ip = _get_request_ip(request)
    _assert_ip_not_rate_limited(ip, now)

    user = (await session.execute(select(User).where(User.login == payload.login))).scalar_one_or_none()
    if user is None:
        _register_ip_login_failure(ip, now)
        await safe_log_event("auth", payload.login, f"{payload.login} attempted login for a non-existent user", "error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    lock_until = _normalize_utc(user.lock_until)
    if lock_until and lock_until > now:
        _register_ip_login_failure(ip, now)
        await safe_log_event("auth", audit_user_object(user), f"{user.login} attempted login to a locked account", "error")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=_build_lock_detail(lock_until, now))
    if lock_until and lock_until <= now:
        #Истекшая блокировка сбрасывает счетчик и снимает блокировку.
        user.failed_logins = 0
        user.lock_until = None

    if not verify_password(payload.password, user.password_hash):
        _register_ip_login_failure(ip, now)
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = MAX_FAILED_LOGINS
            user.lock_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            await session.commit()
            await safe_log_event("auth", audit_user_object(user), f"{user.login} account locked after failed login attempts", "error")
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=_build_lock_detail(user.lock_until, now))
        await session.commit()
        await safe_log_event("auth", audit_user_object(user), f"{user.login} failed login: invalid password", "error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    user.failed_logins = 0
    user.lock_until = None
    await session.commit()

    token = create_access_token(subject=str(user.id))
    _set_auth_cookie(response, token)
    _clear_ip_login_failures(ip)
    await safe_log_event("auth", audit_user_object(user), f"{user.login} logged in", "success")
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(response: Response) -> dict:
    _clear_auth_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=UserRead)
async def me(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> UserRead:
    return await _serialize_user(session, current_user)


@router.patch("/me", response_model=UserRead)
@audit_error_handler("auth", lambda **kwargs: f"{kwargs['current_user'].login} failed to update own profile")
async def update_me(
    payload: UpdateProfileRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> UserRead:
    #Профиль пользователя обновляется без служебных полей отдела и должности.
    data = payload.model_dump(exclude_unset=True)
    data.pop("department", None)
    data.pop("position", None)
    for field, value in data.items():
        if value is not None:
            setattr(current_user, field, value)

    await session.commit()
    await session.refresh(current_user)
    await safe_log_event("auth", audit_user_object(current_user), f"{current_user.login} updated own profile", "success")
    return await _serialize_user(session, current_user)


@router.post("/change-password")
@audit_error_handler("auth", lambda **kwargs: f"{kwargs['current_user'].login} failed to change own password")
async def change_password(
    payload: ChangePasswordRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль указан неверно")

    current_user.password_hash = hash_password(payload.new_password)
    await session.commit()
    await audit_safe_send_notification(
        current_user.email,
        build_password_changed_email(current_user),
    )
    await safe_log_event("auth", audit_user_object(current_user), f"{current_user.login} changed own password", "success")
    return {"status": "ok"}


