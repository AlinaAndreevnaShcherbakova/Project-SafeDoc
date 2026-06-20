import enum


class RoleName(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ACCESS_MANAGER = "access_manager"
    OWNER = "owner"
    EDITOR = "editor"
    READER = "reader"
    GUEST = "guest"


class RoleScope(str, enum.Enum):
    COMPANY = "company"
    DEPARTMENT = "department"
    DOCUMENT = "document"


class Visibility(str, enum.Enum):
    READ_ALL = "read_all"
    EDIT_ALL = "edit_all"
    BY_REQUEST = "by_request"


class AccessRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

