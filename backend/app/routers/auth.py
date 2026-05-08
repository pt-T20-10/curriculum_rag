import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_db
from app.models.user import AuthProvider, User, UserRole
from app.schemas.auth import LoginResponse, Token, UserCreate, UserLogin, UserResponse
from app.security.jwt import create_access_token, get_current_user_id
from app.security.oauth import exchange_google_code, get_google_auth_url
from app.security.password import pwd_context, verify_password

router = APIRouter()


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
        return user

    # 2. Match on email (link or reject)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        if user.google_id and user.google_id != google_id:
            raise ValueError("Email is already linked to a different Google account")
        user.google_id = google_id  # type: ignore[assignment]
        if not user.avatar_url and google_info.get("picture"):
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
        credits=200,        # same starter credits as local signup
        role=UserRole.USER.value,
        is_locked=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/register", response_model=LoginResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Register new user. Returns access token and user data."""

    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    hashed_password = pwd_context.hash(user_data.password)

    new_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name or "",
        credits=200,
        is_active=True,
        is_verified=False,
        auth_provider="local",
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    access_token = create_access_token(data={"sub": str(new_user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "credits": new_user.credits,
            "is_active": new_user.is_active,
            "is_verified": new_user.is_verified,
            "role": new_user.role,
            "is_locked": new_user.is_locked,
        }
    }

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_async_db)):
    """Login and get access token. Supports remember_me for 30-day sessions."""
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.hashed_password): #type: ignore
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active: #type: ignore
        raise HTTPException(status_code=403, detail="Account is inactive")

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

    result = await db.execute(select(User).where(User.id == current_user_id))
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
        return RedirectResponse(
            f"{frontend_cb}?error=email_conflict&state={state}"
        )
    except Exception:
        return RedirectResponse(f"{frontend_cb}?error=server_error&state={state}")

    if not user.is_active or user.is_locked:  # type: ignore[truthy-bool]
        return RedirectResponse(f"{frontend_cb}?error=account_disabled&state={state}")

    access_token = create_access_token(data={"sub": str(user.id)})
    return RedirectResponse(
        f"{frontend_cb}?token={access_token}&state={state}"
    )
