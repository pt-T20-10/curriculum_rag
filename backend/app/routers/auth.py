from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_async_db
from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin, Token, UserResponse, LoginResponse
from app.security.password import hash_password, verify_password
from app.security.jwt import create_access_token, get_current_user_id
from app.security.password import pwd_context
from app.config import settings

router = APIRouter()

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
