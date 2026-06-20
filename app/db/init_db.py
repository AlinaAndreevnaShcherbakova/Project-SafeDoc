from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models import Department, Permission, Position, Role, RoleName, RolePermission, RoleScope, User, UserRole, Worker
from app.models.base import Base


ROLE_SCOPE_MAP: dict[RoleName, RoleScope] = {
    RoleName.SUPERADMIN: RoleScope.COMPANY,
    RoleName.ACCESS_MANAGER: RoleScope.DEPARTMENT,
    RoleName.OWNER: RoleScope.DOCUMENT,
    RoleName.EDITOR: RoleScope.DOCUMENT,
    RoleName.READER: RoleScope.DOCUMENT,
    RoleName.GUEST: RoleScope.DOCUMENT,
}

ROLE_PERMISSIONS_MAP: dict[RoleName, list[str]] = {
    RoleName.SUPERADMIN: ["preview", "download", "edit", "version_view", "version_manage", "access_manage"],
    RoleName.ACCESS_MANAGER: ["preview", "download", "access_manage"],
    RoleName.OWNER: ["preview", "download", "edit", "version_view", "version_manage", "access_manage"],
    RoleName.EDITOR: ["preview", "download", "edit", "version_view", "version_manage"],
    RoleName.READER: ["preview", "version_view"],
    RoleName.GUEST: [],
}

DEFAULT_ADMIN_EMAIL = "admin@safedoc.com"


def _ensure_public_link_name_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {column["name"] for column in inspector.get_columns("documents_public_links")}
    if "name" not in columns:
        sync_conn.execute(text("ALTER TABLE documents_public_links ADD COLUMN name VARCHAR(255)"))


async def create_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_public_link_name_column)


async def _get_or_create_department(session: AsyncSession, name: str) -> Department:
    department = (await session.execute(select(Department).where(Department.name == name))).scalar_one_or_none()
    if department is None:
        department = Department(name=name)
        session.add(department)
        await session.flush()
    return department


async def _get_or_create_position(session: AsyncSession, name: str) -> Position:
    position = (await session.execute(select(Position).where(Position.name == name))).scalar_one_or_none()
    if position is None:
        position = Position(name=name)
        session.add(position)
        await session.flush()
    return position


async def seed_defaults(session: AsyncSession) -> None:
    existing_roles = (await session.execute(select(Role))).scalars().all()
    existing_role_names = {role.name for role in existing_roles}

    for role_name, scope in ROLE_SCOPE_MAP.items():
        if role_name not in existing_role_names:
            session.add(Role(name=role_name, scope=scope))

    await session.flush()

    existing_permissions = (await session.execute(select(Permission))).scalars().all()
    existing_permission_names = {permission.name for permission in existing_permissions}
    for permission_name in sorted({name for values in ROLE_PERMISSIONS_MAP.values() for name in values}):
        if permission_name not in existing_permission_names:
            session.add(Permission(name=permission_name))

    await session.flush()

    roles_by_name = {role.name: role for role in (await session.execute(select(Role))).scalars().all()}
    permissions_by_name = {permission.name: permission for permission in (await session.execute(select(Permission))).scalars().all()}
    existing_role_permissions = {
        (row.role_id, row.permission_id)
        for row in (await session.execute(select(RolePermission))).scalars().all()
    }
    for role_name, permission_names in ROLE_PERMISSIONS_MAP.items():
        role = roles_by_name[role_name]
        for permission_name in permission_names:
            permission = permissions_by_name[permission_name]
            if (role.id, permission.id) not in existing_role_permissions:
                session.add(RolePermission(role_id=role.id, permission_id=permission.id))

    await session.flush()

    admin = (await session.execute(select(User).where(User.login == settings.default_superadmin_login))).scalar_one_or_none()
    if admin is None:
        department = await _get_or_create_department(session, "IT")
        position = await _get_or_create_position(session, "SuperAdmin")
        worker = Worker(
            surname="Admin",
            name="System",
            middle_name=None,
            department_id=department.id,
            position_id=position.id,
            email=DEFAULT_ADMIN_EMAIL,
        )
        session.add(worker)
        await session.flush()

        admin = User(
            login=settings.default_superadmin_login,
            password_hash=hash_password(settings.default_superadmin_password),
            worker_id=worker.id,
            is_superadmin=True,
        )
        session.add(admin)
        await session.flush()
    elif admin.email == "admin@safedoc.local":
        admin.email = DEFAULT_ADMIN_EMAIL

    admin.is_superadmin = True

    superadmin_role = roles_by_name[RoleName.SUPERADMIN]
    has_superadmin_role = (
        await session.execute(select(UserRole).where(UserRole.user_id == admin.id, UserRole.role_id == superadmin_role.id))
    ).scalar_one_or_none()
    if has_superadmin_role is None:
        session.add(UserRole(user_id=admin.id, role_id=superadmin_role.id))

    other_superadmins = (
        await session.execute(select(User).where(User.is_superadmin.is_(True), User.id != admin.id))
    ).scalars().all()
    for user in other_superadmins:
        user.is_superadmin = False

    extra_superadmin_roles = (
        await session.execute(select(UserRole).where(UserRole.role_id == superadmin_role.id, UserRole.user_id != admin.id))
    ).scalars().all()
    for row in extra_superadmin_roles:
        await session.delete(row)

    await session.commit()
