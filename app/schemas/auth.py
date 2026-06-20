from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    surname: str | None = Field(default=None, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    name: str | None = Field(default=None, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    middle_name: str | None = Field(default=None, pattern=r"^[A-Za-zА-Яа-яЁё]+$")
    department: str | None = None
    position: str | None = None
    email: EmailStr | None = None


