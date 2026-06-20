from app.models import RoleName, Visibility


def is_read_allowed_by_visibility(visibility: Visibility) -> bool:
    return visibility in {Visibility.READ_ALL, Visibility.EDIT_ALL}


def is_write_allowed_by_visibility(visibility: Visibility) -> bool:
    return visibility == Visibility.EDIT_ALL


def role_can_read(role_names: set[RoleName]) -> bool:
    return bool(role_names & {RoleName.OWNER, RoleName.EDITOR, RoleName.READER})


def role_can_download(role_names: set[RoleName]) -> bool:
    return bool(role_names & {RoleName.OWNER, RoleName.EDITOR})


def role_can_write(role_names: set[RoleName]) -> bool:
    return bool(role_names & {RoleName.OWNER, RoleName.EDITOR})


def role_can_manage_access(role_names: set[RoleName]) -> bool:
    return bool(role_names & {RoleName.SUPERADMIN, RoleName.ACCESS_MANAGER, RoleName.OWNER})

