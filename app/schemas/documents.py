from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Visibility


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_id: int
    owner_login: str | None = None
    owner_full_name: str | None = None
    mime: str
    size_bytes: int
    visibility: Visibility
    current_version: int
    folder_id: int | None = None
    folder_name: str | None = None
    can_download: bool = False
    can_write: bool = False
    has_active_public_links: bool = False
    created_at: datetime
    updated_at: datetime


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None


class FolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None


class DocumentMove(BaseModel):
    folder_id: int | None = None
    replace_existing: bool = False


class DocumentVisibilityUpdate(BaseModel):
    visibility: Visibility


class DocumentBulkMove(BaseModel):
    document_ids: list[int] = Field(min_length=1)
    folder_id: int | None = None
    replace_existing: bool = False


class DocumentBulkDelete(BaseModel):
    document_ids: list[int] = Field(min_length=1)


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None = None
    owner_id: int
    created_at: datetime


class DocumentCatalogRead(BaseModel):
    id: int
    name: str
    owner_id: int
    owner_login: str | None = None
    owner_full_name: str | None = None
    current_version: int
    folder_id: int | None = None
    folder_name: str | None = None
    visibility: Visibility
    has_access: bool
    can_request: bool
    can_download: bool = False
    can_write: bool = False
    can_manage_access: bool = False
    has_active_public_links: bool = False


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version: int
    author_id: int
    author_full_name: str | None = None
    comment: str | None
    created_at: datetime

