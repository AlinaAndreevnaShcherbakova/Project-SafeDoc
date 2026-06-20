from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AccessRequestStatus, RoleName

AccessPermission = Literal[
    "preview",
    "download",
    "edit",
    "version_view",
    "version_manage",
    "access_manage",
]


STATUS_RU_MAP: dict[AccessRequestStatus, str] = {
    AccessRequestStatus.PENDING: "На рассмотрении",
    AccessRequestStatus.APPROVED: "Одобрена",
    AccessRequestStatus.REJECTED: "Отклонена",
}


def normalize_permissions(permissions: list[AccessPermission]) -> list[AccessPermission]:
    normalized = set(permissions)
    if "download" in normalized or "edit" in normalized or "version_view" in normalized or "version_manage" in normalized:
        normalized.add("preview")
    if "version_manage" in normalized:
        normalized.add("version_view")

    order: list[AccessPermission] = [
        "preview",
        "download",
        "edit",
        "version_view",
        "version_manage",
        "access_manage",
    ]
    return [permission for permission in order if permission in normalized]


ROLE_PERMISSIONS_MAP: dict[RoleName, list[AccessPermission]] = {
    RoleName.OWNER: ["preview", "download", "edit", "version_view", "version_manage", "access_manage"],
    RoleName.EDITOR: ["preview", "download", "edit", "version_view", "version_manage"],
    RoleName.READER: ["preview", "version_view"],
}


def _validate_document_role(role: RoleName) -> None:
    if role in {RoleName.SUPERADMIN, RoleName.ACCESS_MANAGER, RoleName.GUEST}:
        raise ValueError("Для доступа к документу можно использовать только роли owner, editor или reader")


class AccessRequestCreate(BaseModel):
    document_id: int
    requested_permissions: list[AccessPermission] = Field(default_factory=list)
    requested_role: RoleName | None = None
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _apply_permission_dependencies(self) -> "AccessRequestCreate":
        if self.requested_role is not None:
            _validate_document_role(self.requested_role)
            if not self.requested_permissions:
                self.requested_permissions = ROLE_PERMISSIONS_MAP[self.requested_role]
        if not self.requested_permissions:
            raise ValueError("Нужно выбрать хотя бы один уровень доступа")
        self.requested_permissions = normalize_permissions(self.requested_permissions)
        return self


class AccessRequestBulkCreate(BaseModel):
    document_ids: list[int] = Field(min_length=1)
    requested_permissions: list[AccessPermission] = Field(default_factory=list)
    requested_role: RoleName | None = None
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _apply_permission_dependencies(self) -> "AccessRequestBulkCreate":
        if self.requested_role is not None:
            _validate_document_role(self.requested_role)
            if not self.requested_permissions:
                self.requested_permissions = ROLE_PERMISSIONS_MAP[self.requested_role]
        if not self.requested_permissions:
            raise ValueError("Нужно выбрать хотя бы один уровень доступа")
        self.requested_permissions = normalize_permissions(self.requested_permissions)
        return self


class AccessRequestResolve(BaseModel):
    approve: bool
    resolution_comment: str | None = Field(default=None, max_length=1000)


class AccessRequestBulkResolve(BaseModel):
    request_ids: list[int] = Field(min_length=1)
    approve: bool
    resolution_comment: str | None = Field(default=None, max_length=1000)


class AccessRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_name: str | None = None
    requester_id: int
    requester_login: str | None = None
    requested_role: RoleName
    requested_permissions: list[AccessPermission] = Field(default_factory=list)
    status: AccessRequestStatus
    status_ru: str
    message: str | None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by_id: int | None = None
    resolved_by_login: str | None = None
    resolution_comment: str | None = None


class GrantAccessRequest(BaseModel):
    document_id: int
    user_id: int
    permissions: list[AccessPermission] = Field(default_factory=list)
    role: RoleName | None = None

    @model_validator(mode="after")
    def _apply_permission_dependencies(self) -> "GrantAccessRequest":
        if not self.permissions and self.role is not None:
            _validate_document_role(self.role)
            self.permissions = ROLE_PERMISSIONS_MAP[self.role]
        if not self.permissions:
            raise ValueError("Нужно выбрать хотя бы один уровень доступа")
        self.permissions = normalize_permissions(self.permissions)
        return self


class GrantAccessBulkRequest(BaseModel):
    document_id: int
    user_ids: list[int] = Field(min_length=1)
    permissions: list[AccessPermission] = Field(default_factory=list)
    role: RoleName | None = None

    @model_validator(mode="after")
    def _apply_permission_dependencies(self) -> "GrantAccessBulkRequest":
        if not self.permissions and self.role is not None:
            _validate_document_role(self.role)
            self.permissions = ROLE_PERMISSIONS_MAP[self.role]
        if not self.permissions:
            raise ValueError("Нужно выбрать хотя бы один уровень доступа")
        self.permissions = normalize_permissions(self.permissions)
        return self


class RevokeAccessRequest(BaseModel):
    document_id: int
    user_id: int


class RevokeAccessBulkRequest(BaseModel):
    document_id: int
    user_ids: list[int] = Field(min_length=1)


class PublicLinkCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    expires_at: datetime

    @model_validator(mode="after")
    def _validate_expiration(self) -> "PublicLinkCreate":
        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Дата и время действия ссылки должны быть в будущем")
        return self


class PublicLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    token: str
    name: str | None = None
    expires_at: datetime
    revoked_at: datetime | None = None


class AccessGrantRead(BaseModel):
    user_id: int
    user_login: str
    user_full_name: str
    role: RoleName
    permissions: list[AccessPermission] = Field(default_factory=list)


class AccessUserOption(BaseModel):
    id: int
    login: str
    full_name: str


class DocumentPermissionsBulkRequest(BaseModel):
    user_id: int = Field(ge=1)
    document_ids: list[int] = Field(min_length=1)


