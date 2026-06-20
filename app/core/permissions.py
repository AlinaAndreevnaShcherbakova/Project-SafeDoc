from app.models.enums import RoleName


FILE_READ_ROLES = {RoleName.OWNER, RoleName.EDITOR, RoleName.READER}
FILE_WRITE_ROLES = {RoleName.OWNER, RoleName.EDITOR}
FILE_ACCESS_MANAGE_ROLES = {RoleName.SUPERADMIN, RoleName.ACCESS_MANAGER, RoleName.OWNER}


def can_view_file(role_names: set[RoleName]) -> bool:
    return bool(role_names & FILE_READ_ROLES)


def can_manage_file(role_names: set[RoleName]) -> bool:
    return bool(role_names & FILE_WRITE_ROLES)


def can_manage_access(role_names: set[RoleName]) -> bool:
    return bool(role_names & FILE_ACCESS_MANAGE_ROLES)

