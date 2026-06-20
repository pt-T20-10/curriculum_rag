"""Helpers for resolving system and per-user advanced configuration."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.config_registry import PARAMETER_REGISTRY
from app.models.config import SystemConfig, UserConfig


def decode_config_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def load_system_overrides(db: AsyncSession) -> dict[str, Any]:
    rows = await db.execute(select(SystemConfig))
    return {row.key: decode_config_value(row.value) for row in rows.scalars().all()}


async def load_user_overrides(db: AsyncSession, user_id: int) -> dict[str, Any]:
    rows = await db.execute(select(UserConfig).where(UserConfig.user_id == user_id))
    return {row.key: decode_config_value(row.value) for row in rows.scalars().all()}


async def load_effective_config(
    db: AsyncSession,
    user_id: int | None = None,
    include_admin_only: bool = False,
) -> dict[str, Any]:
    """Merge user > system > settings/default for registered parameters."""
    base: dict[str, Any] = {}
    for key, entry in PARAMETER_REGISTRY.items():
        if not include_admin_only and entry.get("admin_only"):
            continue
        default = entry["default"]
        base[key] = getattr(settings, key, default)

    system = {
        key: value
        for key, value in (await load_system_overrides(db)).items()
        if key in PARAMETER_REGISTRY
    }
    user = {}
    if user_id is not None:
        user = {
            key: value
            for key, value in (await load_user_overrides(db, user_id)).items()
            if key in PARAMETER_REGISTRY
        }

    return {**base, **system, **user}
