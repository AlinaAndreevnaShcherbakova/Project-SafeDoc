import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.core.config import settings
from app.models.enums import AccessRequestStatus
from app.services.audit import safe_log_event


@dataclass(frozen=True)
class NotificationMessage:
    subject: str
    body: str


ACCESS_REQUEST_NOTIFICATION_SUBJECT = "Запрос на доступ к файлу"
ACCESS_REQUEST_RESOLUTION_NOTIFICATION_SUBJECT = "Статус заявки на доступ"
ACCESS_GRANT_NOTIFICATION_SUBJECT = "Уровень доступа к файлу изменен"
ACCESS_REVOKE_NOTIFICATION_SUBJECT = "Доступ к файлу изменен"
PASSWORD_CHANGED_NOTIFICATION_SUBJECT = "Пароль изменен"


ACCESS_REQUEST_STATUS_RU_MAP: dict[AccessRequestStatus, str] = {
    AccessRequestStatus.PENDING: "На рассмотрении",
    AccessRequestStatus.APPROVED: "Одобрена",
    AccessRequestStatus.REJECTED: "Отклонена",
}


def notification_actor_label(user) -> str:
    if user is None:
        return "неизвестным пользователем"

    login = str(getattr(user, "login", "") or "").strip()
    full_name = " ".join(
        part
        for part in [
            str(getattr(user, "surname", "") or "").strip(),
            str(getattr(user, "name", "") or "").strip(),
            str(getattr(user, "middle_name", "") or "").strip(),
        ]
        if part
    )

    if full_name and login:
        return f"{full_name} ({login})"
    return full_name or login or "неизвестным пользователем"


def _build_password_changed_body(actor, target_user=None) -> str:
    actor_label = notification_actor_label(actor)
    target = target_user or actor
    same_user = target is not None and actor is not None and getattr(target, "id", None) == getattr(actor, "id", None)

    if same_user:
        return "Ваш пароль был изменен. Если это не вы, обратитесь к суперадминистратору, чтобы установить новый пароль"

    if getattr(actor, "is_superadmin", False):
        return "Ваш пароль был изменен суперадминистратором. Обратитесь к суперадминистратору за новым паролем"

    return (
        f"Ваш пароль был изменен пользователем {actor_label}. "
        "Обратитесь к суперадминистратору за новым паролем."
    )


def build_password_changed_email(actor, target_user=None) -> NotificationMessage:
    return NotificationMessage(
        subject=PASSWORD_CHANGED_NOTIFICATION_SUBJECT,
        body=_build_password_changed_body(actor, target_user),
    )


def build_access_request_email(document_name: str, actor, role_label: str, request_message: str | None) -> NotificationMessage:
    body = (
        f'Пользователь {notification_actor_label(actor)} запросил доступ к документу "{document_name}". '
        f"Запрошенный уровень: {role_label}."
    )
    comment = (request_message or "").strip()
    if comment:
        body += f"\nКомментарий: {comment}"
    return NotificationMessage(subject=ACCESS_REQUEST_NOTIFICATION_SUBJECT, body=body)


def build_access_request_resolution_email(
    document_name: str,
    actor,
    status_value: AccessRequestStatus,
    role_label: str,
    resolution_comment: str | None,
) -> NotificationMessage:
    status_label = ACCESS_REQUEST_STATUS_RU_MAP.get(status_value, status_value.value)
    comment = (resolution_comment or "").strip()
    body = (
        f'Ваш запрос на доступ к документу "{document_name}" был обработан пользователем '
        f"{notification_actor_label(actor)}: {status_label}. Текущий уровень: {role_label}."
    )
    if comment:
        body += f"\nКомментарий: {comment}"
    return NotificationMessage(subject=ACCESS_REQUEST_RESOLUTION_NOTIFICATION_SUBJECT, body=body)


def build_access_grant_email(document_name: str, actor, role_label: str, is_update: bool) -> NotificationMessage:
    action = "изменен" if is_update else "предоставлен"
    body = (
        f'Ваш доступ к документу "{document_name}" был {action} пользователем '
        f"{notification_actor_label(actor)}. Текущий уровень: {role_label}."
    )
    return NotificationMessage(subject=ACCESS_GRANT_NOTIFICATION_SUBJECT, body=body)


def build_access_revoke_email(document_name: str, actor) -> NotificationMessage:
    body = (
        f'Ваш доступ к документу "{document_name}" был отозван пользователем '
        f"{notification_actor_label(actor)}. Текущий уровень: гость."
    )
    return NotificationMessage(subject=ACCESS_REVOKE_NOTIFICATION_SUBJECT, body=body)


class NotificationService:
    def _is_configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_from)

    def _open_smtp(self) -> smtplib.SMTP:
        if settings.smtp_use_ssl:
            return smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )

        smtp = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
        if settings.smtp_use_tls:
            smtp.starttls()
        return smtp

    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        if settings.notification_service_url:
            try:
                httpx.post(
                    f"{settings.notification_service_url.rstrip('/')}/internal/notifications/send",
                    headers={"X-Internal-Token": settings.internal_service_token},
                    json={"to_email": to_email, "subject": subject, "body": body},
                    timeout=settings.smtp_timeout_seconds,
                )
            except Exception:
                return False
            return True

        if not self._is_configured():
            return False

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.set_content(body)

        try:
            with self._open_smtp() as smtp:
                if settings.smtp_user and settings.smtp_password:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False


notification_service = NotificationService()


async def audit_safe_send_notification(
    to_email: str,
    notification: NotificationMessage,
    event_subject: str = "notification",
    event_context: str | None = None,
) -> bool:
    try:
        sent = notification_service.send_email(to_email, notification.subject, notification.body)
    except Exception:
        sent = False
    if not sent:
        event_context = event_context or f"failed to send notification '{notification.subject}'"
        await safe_log_event("notification", event_subject, event_context, "error", f"recipient={to_email}")
    return sent
