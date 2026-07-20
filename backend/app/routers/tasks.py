"""Server background task status endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.textbook import Textbook
from app.models.user import User, UserRole
from app.security.jwt import get_current_user_id
from app.services.server_task_manager import server_task_manager


router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskStatusResponse(BaseModel):
    task_id: str
    textbook_id: int
    status: str
    phase: str = ""
    progress_data: dict[str, Any] | None = None
    error_message: str = ""


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    record = server_task_manager.get(task_id)
    if record:
        textbook_id = record.textbook_id
    else:
        textbook = await db.scalar(
            select(Textbook).where(Textbook.task_id == task_id)
        )
        if not textbook:
            raise HTTPException(status_code=404, detail="Task not found")
        textbook_id = textbook.id  # type: ignore[assignment]

    user = await db.scalar(select(User).where(User.id == current_user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    textbook = await db.scalar(select(Textbook).where(Textbook.id == textbook_id))
    if not textbook:
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = user.role == UserRole.ADMIN.value  # type: ignore[comparison-overlap]
    if textbook.user_id != current_user_id and not is_admin:  # type: ignore[comparison-overlap]
        raise HTTPException(status_code=404, detail="Task not found")

    progress_data = dict(textbook.progress_data or {})  # type: ignore[arg-type]
    if textbook.pdf_path:  # type: ignore
        progress_data["pdf_path"] = textbook.pdf_path  # type: ignore
    if textbook.docx_path:  # type: ignore
        progress_data["docx_path"] = textbook.docx_path  # type: ignore
    if textbook.title:  # type: ignore
        progress_data["title"] = textbook.title  # type: ignore
    progress_data.setdefault("task_id", task_id)

    task_status = record.status if record else str(textbook.status or "")
    error_message = (
        record.error_message
        if record and record.error_message
        else str(textbook.error_message or progress_data.get("error_message") or "")
    )

    return TaskStatusResponse(
        task_id=task_id,
        textbook_id=int(textbook.id),  # type: ignore[arg-type]
        status=task_status,
        phase=str(progress_data.get("phase") or ""),
        progress_data=progress_data,
        error_message=error_message,
    )
