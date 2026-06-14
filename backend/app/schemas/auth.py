import re
from pydantic import BaseModel, EmailStr, Field, field_validator

class UserCreate(BaseModel):
    email: EmailStr
    username: str | None = None
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) < 3:
            raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự")
        if len(v) > 50:
            raise ValueError("Tên đăng nhập tối đa 50 ký tự")
        if not re.match(r"^[a-zA-Z0-9_.-]+$", v):
            raise ValueError("Tên đăng nhập chỉ được chứa chữ cái, số, dấu _ . -")
        return v

class UserLogin(BaseModel):
    identifier: str          # email hoặc username
    password: str
    remember_me: bool = False

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    avatar_url: str | None
    is_active: bool
    is_verified: bool
    credits: int
    auth_provider: str
    role: str = "user"
    is_locked: bool = False

    class Config:
        from_attributes = True


class UserData(BaseModel):
    """User data returned in login/register response."""
    id: int
    email: str
    full_name: str | None
    credits: int
    is_active: bool
    is_verified: bool
    role: str = "user"
    is_locked: bool = False

class LoginResponse(BaseModel):
    """Response for login and register endpoints."""
    access_token: str
    token_type: str = "bearer"
    user: UserData


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=72)

    @field_validator("code")
    @classmethod
    def code_must_be_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("Mã xác nhận phải gồm 6 chữ số")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=72)