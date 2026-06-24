"""Create or repair the configured bootstrap admin during deployment."""

import asyncio

from app.config import settings
from app.services.bootstrap import ensure_default_admin_user


async def main() -> None:
    if not settings.DEFAULT_ADMIN_ENABLED:
        print("Default admin bootstrap is disabled (DEFAULT_ADMIN_ENABLED=false)")
        return

    changed = await ensure_default_admin_user()
    if changed:
        print("Default admin account created/verified")
    else:
        print("Default admin account already exists and is ready")


if __name__ == "__main__":
    asyncio.run(main())

