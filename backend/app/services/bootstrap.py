"""Application bootstrap helpers for first-run local deployments."""

from sqlalchemy import or_, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import AuthProvider, User, UserRole


async def ensure_default_admin_user() -> bool:
    """
    Ensure a default admin exists for fresh local/database setups.

    Returns True when a new account is inserted or the default admin account is
    repaired enough to be usable. Existing non-default accounts are not reset.
    """
    if not settings.DEFAULT_ADMIN_ENABLED:
        return False

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == settings.DEFAULT_ADMIN_EMAIL)
        )
        existing = result.scalar_one_or_none()

        if existing:
            changed = False
            if existing.role != UserRole.ADMIN.value:
                existing.role = UserRole.ADMIN.value
                changed = True
            if not existing.is_active:
                existing.is_active = True
                changed = True
            if existing.is_locked:
                existing.is_locked = False
                existing.locked_at = None
                existing.locked_by = None
                changed = True
            if not existing.hashed_password:
                existing.hashed_password = settings.DEFAULT_ADMIN_PASSWORD_HASH
                existing.auth_provider = AuthProvider.LOCAL.value
                changed = True

            if changed:
                await session.commit()
            return changed

        username = settings.DEFAULT_ADMIN_USERNAME or None
        if username:
            username_result = await session.execute(
                select(User.id).where(
                    or_(User.username == username, User.email == username)
                )
            )
            if username_result.scalar_one_or_none() is not None:
                username = None

        session.add(
            User(
                email=settings.DEFAULT_ADMIN_EMAIL,
                username=username,
                hashed_password=settings.DEFAULT_ADMIN_PASSWORD_HASH,
                full_name=settings.DEFAULT_ADMIN_FULL_NAME,
                auth_provider=AuthProvider.LOCAL.value,
                is_active=True,
                is_verified=True,
                credits=0,
                role=UserRole.ADMIN.value,
                is_locked=False,
                is_deleted=False,
            )
        )
        await session.commit()
        return True
