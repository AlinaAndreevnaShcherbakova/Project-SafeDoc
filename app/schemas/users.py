from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    surname: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    middle_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    department: str = Field(min_length=1, max_length=100)
    position: str = Field(min_length=1, max_length=100)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="user", pattern=r"^(superadmin|access_manager|user)$")
    is_superadmin: bool = False


class UserUpdate(BaseModel):
    surname: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    middle_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    department: str | None = Field(default=None, min_length=1, max_length=100)
    position: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_superadmin: bool | None = None


class UserPut(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    surname: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    middle_name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    department: str = Field(min_length=1, max_length=100)
    position: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: str | None = Field(default=None, pattern=r"^(superadmin|access_manager|user)$")
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    surname: str
    name: str
    middle_name: str | None = None
    department: str | None = None
    position: str | None = None
    email: EmailStr | str
    is_superadmin: bool
    role: str


class UsersBulkDelete(BaseModel):
    user_ids: list[int] = Field(min_length=1)

