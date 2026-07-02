import hashlib
import random
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_db
from app.models.user import AuthProvider, User, UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    EmailVerificationRequest,
    ForgotPasswordRequest,
    LoginResponse,
    RegisterResponse,
    ResendEmailVerificationRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.security.jwt import create_access_token, get_current_user_id
from app.security.oauth import exchange_google_code, get_google_auth_url
from app.security.password import pwd_context, verify_password
from app.services.email_service import send_email_verification_email, send_password_reset_email

router = APIRouter()

_OTP_EXPIRY_MINUTES = 15


def _new_otp() -> tuple[str, str, datetime]:
    otp = f"{random.randint(0, 999999):06d}"
    code_hash = hashlib.sha256(otp.encode()).hexdigest()
    expires = datetime.utcnow() + timedelta(minutes=_OTP_EXPIRY_MINUTES)
    return otp, code_hash, expires


async def _send_verification_code(user: User) -> None:
    otp, code_hash, expires = _new_otp()
    user.email_verification_code = code_hash  # type: ignore[assignment]
    user.email_verification_expires = expires  # type: ignore[assignment]
    await send_email_verification_email(str(user.email), otp)


# ---------------------------------------------------------------------------
# Google OAuth helpers
# ---------------------------------------------------------------------------

async def _get_or_create_google_user(db: AsyncSession, google_info: dict) -> User:
    """
    Find or create a User from Google userinfo response.
    Handles three cases: existing google_id, existing email, new user.
    """
    google_id = str(google_info["id"])
    email = google_info["email"]

    # 1. Exact match on google_id
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()
    if user:
        if user.is_deleted: #type: ignore
            raise ValueError("account_deleted")
        return user

    # 2. Match on email (link or reject)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        if user.is_deleted: #type: ignore
            raise ValueError("account_deleted")
        if user.google_id and user.google_id != google_id: #type: ignore
            raise ValueError("Email is already linked to a different Google account")
        user.google_id = google_id  # type: ignore[assignment]
        if not user.avatar_url and google_info.get("picture"): #type: ignore
            user.avatar_url = google_info["picture"]  # type: ignore[assignment]
        await db.commit()
        return user

    # 3. Create new user
    user = User(
        email=email,
        full_name=google_info.get("name"),
        google_id=google_id,
        avatar_url=google_info.get("picture"),
        auth_provider=AuthProvider.GOOGLE.value,
        is_active=True,
        is_verified=True,   # Google email is already verified
        role=UserRole.USER.value,
        is_locked=False,
        is_deleted=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/register", response_model=RegisterResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Register new user. Returns access token and user data."""

    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email này đã được đăng ký")

    if user_data.username:
        result = await db.execute(
            select(User).where(User.username == user_data.username)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Tên đăng nhập đã được sử dụng")

    hashed_password = pwd_context.hash(user_data.password)
    otp, code_hash, expires = _new_otp()

    new_user = User(
        email=user_data.email,
        username=user_data.username or None,
        hashed_password=hashed_password,
        full_name=user_data.full_name or "",
        is_active=True,
        is_verified=False,
        auth_provider="local",
        is_deleted=False,
        email_verification_code=code_hash,
        email_verification_expires=expires,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    try:
        await send_email_verification_email(user_data.email, otp)
    except Exception:
        # Email delivery can be retried from the verification page.
        pass

    return {
        "message": "Tài khoản đã được tạo. Vui lòng kiểm tra email để xác nhận đăng ký.",
        "email": new_user.email,
        "is_verified": bool(new_user.is_verified),
    }

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_async_db)):
    """Login and get access token. Supports remember_me for 30-day sessions."""
    identifier = credentials.identifier.strip()
    result = await db.execute(
        select(User).where(
            or_(User.email == identifier, User.username == identifier),
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản với thông tin đăng nhập này")

    if user.is_locked:  # type: ignore[truthy-bool]
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa. Vui lòng liên hệ hỗ trợ.")

    if not user.is_active:  # type: ignore[truthy-bool]
        raise HTTPException(status_code=403, detail="Tài khoản chưa được kích hoạt.")

    if not user.hashed_password: #type: ignore[truthy-bool]
        raise HTTPException(
            status_code=400,
            detail="Tài khoản này đăng ký qua Google. Vui lòng đăng nhập bằng nút Google bên dưới."
        )

    if user.auth_provider == AuthProvider.LOCAL.value and not user.is_verified:  # type: ignore[truthy-bool]
        raise HTTPException(
            status_code=403,
            detail="Email chưa được xác nhận. Vui lòng nhập mã xác nhận đã gửi tới email của bạn.",
        )

    if not verify_password(credentials.password, user.hashed_password): # type: ignore[arg-type]
        raise HTTPException(status_code=401, detail="Mật khẩu không đúng")

    if credentials.remember_me:
        expires_delta = timedelta(days=settings.REMEMBER_ME_EXPIRE_DAYS)
    else:
        expires_delta = timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=expires_delta,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "credits": user.credits,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "role": user.role,
            "is_locked": user.is_locked,
        }
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    current_user_id: Optional[int] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Get current user info."""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(User).where(
            User.id == current_user_id,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


# ---------------------------------------------------------------------------
# Google OAuth endpoints
# ---------------------------------------------------------------------------

@router.get("/google/login")
async def google_login():
    """Return Google OAuth URL + random state. Frontend stores state and redirects."""
    state = secrets.token_urlsafe(16)
    auth_url = get_google_auth_url(state)
    return {"auth_url": auth_url, "state": state}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Google redirects here after consent. Exchanges code → user info → JWT,
    then redirects browser to the frontend callback page with the token.
    """
    frontend_cb = f"{settings.FRONTEND_URL}/auth/callback"

    try:
        google_info = await exchange_google_code(code)
    except Exception:
        return RedirectResponse(f"{frontend_cb}?error=google_auth_failed&state={state}")

    try:
        user = await _get_or_create_google_user(db, google_info)
    except ValueError as exc:
        error_code = "account_deleted" if str(exc) == "account_deleted" else "email_conflict"
        return RedirectResponse(
            f"{frontend_cb}?error={error_code}&state={state}"
        )
    except Exception:
        return RedirectResponse(f"{frontend_cb}?error=server_error&state={state}")

    if user.is_deleted or not user.is_active or user.is_locked:  # type: ignore[truthy-bool]
        return RedirectResponse(f"{frontend_cb}?error=account_disabled&state={state}")

    access_token = create_access_token(data={"sub": str(user.id)})
    return RedirectResponse(
        f"{frontend_cb}?token={access_token}&state={state}"
    )


# ---------------------------------------------------------------------------
# Password reset endpoints
# ---------------------------------------------------------------------------

_GENERIC_RESPONSE = {"message": "Nếu email tồn tại, mã xác nhận đã được gửi."}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Generate and email a 6-digit OTP for password reset.
    Always returns the same response to prevent email enumeration.
    """
    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if user and user.auth_provider == AuthProvider.LOCAL.value: #type: ignore
        otp, code_hash, expires = _new_otp()

        user.password_reset_code = code_hash      # type: ignore[assignment]
        user.password_reset_expires = expires     # type: ignore[assignment]
        await db.commit()

        try:
            await send_password_reset_email(body.email, otp)
        except Exception:
            # Log already done inside email_service; don't leak error to client
            pass

    return _GENERIC_RESPONSE


@router.post("/verify-email", response_model=LoginResponse)
async def verify_email(
    body: EmailVerificationRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Verify a local user's email using the 6-digit OTP sent after registration."""
    invalid_exc = HTTPException(
        status_code=400,
        detail="Mã xác nhận email không hợp lệ hoặc đã hết hạn.",
    )

    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise invalid_exc
    if user.auth_provider != AuthProvider.LOCAL.value:  # type: ignore[comparison-overlap]
        raise HTTPException(status_code=400, detail="Tài khoản này đăng nhập qua Google.")
    if user.is_verified:  # type: ignore[truthy-bool]
        raise HTTPException(status_code=400, detail="Email đã được xác nhận. Vui lòng đăng nhập.")
    if not user.email_verification_code or not user.email_verification_expires:  # type: ignore[truthy-bool]
        raise invalid_exc
    if datetime.utcnow() > user.email_verification_expires:  # type: ignore[operator]
        raise invalid_exc

    submitted_hash = hashlib.sha256(body.code.encode()).hexdigest()
    if submitted_hash != user.email_verification_code:
        raise invalid_exc

    user.is_verified = True  # type: ignore[assignment]
    user.email_verification_code = None  # type: ignore[assignment]
    user.email_verification_expires = None  # type: ignore[assignment]
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "credits": user.credits,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "role": user.role,
            "is_locked": user.is_locked,
        }
    }


@router.post("/resend-verification")
async def resend_verification(
    body: ResendEmailVerificationRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Send a fresh email verification OTP.
    Always returns a generic response to reduce account enumeration.
    """
    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if user and user.auth_provider == AuthProvider.LOCAL.value and not user.is_verified:  # type: ignore[truthy-bool]
        try:
            await _send_verification_code(user)
            await db.commit()
        except Exception:
            await db.rollback()
            # Log already done inside email_service; do not leak delivery state.
            pass

    return {"message": "Nếu tài khoản cần xác nhận, mã mới đã được gửi."}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Verify OTP and set new password."""
    invalid_exc = HTTPException(
        status_code=400,
        detail="Mã xác nhận không hợp lệ hoặc đã hết hạn.",
    )

    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_reset_code or not user.password_reset_expires: #type: ignore
        raise invalid_exc

    if datetime.utcnow() > user.password_reset_expires:  # type: ignore[operator]
        raise invalid_exc

    submitted_hash = hashlib.sha256(body.code.encode()).hexdigest()
    if submitted_hash != user.password_reset_code:
        raise invalid_exc

    user.hashed_password = pwd_context.hash(body.new_password)  # type: ignore[assignment]
    user.password_reset_code = None       # type: ignore[assignment]
    user.password_reset_expires = None    # type: ignore[assignment]
    await db.commit()

    return {"message": "Mật khẩu đã được đặt lại thành công."}


# ---------------------------------------------------------------------------
# Change password (authenticated)
# ---------------------------------------------------------------------------

@router.patch("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user_id: Optional[int] = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Change password for an authenticated local-auth user."""
    if not current_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(User).where(
            User.id == current_user_id,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.hashed_password:  # type: ignore[truthy-bool]
        raise HTTPException(
            status_code=400,
            detail="Tài khoản này không sử dụng mật khẩu. Vui lòng đăng nhập qua Google.",
        )

    if not verify_password(body.current_password, user.hashed_password):  # type: ignore[arg-type]
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng")

    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu mới phải khác mật khẩu hiện tại",
        )

    user.hashed_password = pwd_context.hash(body.new_password)  # type: ignore[assignment]
    await db.commit()

    return {"message": "Mật khẩu đã được cập nhật thành công."}
