"""
User-provided API key management endpoints.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.schemas.byok import (
    ByokCredentialUpdate,
    ByokCredentialUpdateResponse,
    ByokStatusResponse,
    ByokValidateRequest,
    ByokValidateResponse,
)
from app.security.jwt import get_current_user_id
from app.services.byok_service import (
    ByokConfigurationError,
    ByokCredentialError,
    credential_state,
    delete_user_key,
    generation_mode,
    generation_mode_label,
    saved_key,
    upsert_user_key,
)

router = APIRouter(prefix="/byok", tags=["byok"])


async def _status(db: AsyncSession, user_id: int) -> ByokStatusResponse:
    mode = generation_mode()
    return ByokStatusResponse(
        generation_mode=mode,  # type: ignore[arg-type]
        generation_mode_label=generation_mode_label(mode),
        openai=await credential_state(db, user_id, "openai"),
        serper=await credential_state(db, user_id, "serper"),
    )


@router.get("/status", response_model=ByokStatusResponse)
async def get_byok_status(
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    return await _status(db, current_user_id)


@router.put("/credentials", response_model=ByokCredentialUpdateResponse)
async def update_byok_credentials(
    payload: ByokCredentialUpdate,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        changed = False
        if payload.openai_api_key:
            await upsert_user_key(db, current_user_id, "openai", payload.openai_api_key)
            changed = True
        if payload.serper_api_key:
            await upsert_user_key(db, current_user_id, "serper", payload.serper_api_key)
            changed = True
        if not changed:
            raise HTTPException(status_code=400, detail="Vui lòng nhập ít nhất một API key.")
        await db.commit()
        status = await _status(db, current_user_id)
        return ByokCredentialUpdateResponse(**status.model_dump(), message="Đã lưu API key an toàn.")
    except ByokConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ByokCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/credentials/{provider}", response_model=ByokStatusResponse)
async def remove_byok_credential(
    provider: str,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        await delete_user_key(db, current_user_id, provider)
        await db.commit()
        return await _status(db, current_user_id)
    except ByokCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate", response_model=ByokValidateResponse)
async def validate_byok_credentials(
    payload: ByokValidateRequest,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    openai_key = (payload.openai_api_key or "").strip()
    serper_key = (payload.serper_api_key or "").strip()
    if payload.credential_usage == "saved":
        openai_key = openai_key or await saved_key(db, current_user_id, "openai")
        serper_key = serper_key or await saved_key(db, current_user_id, "serper")

    openai_valid = False
    serper_valid = None
    openai_error = ""
    serper_error = ""

    if not openai_key:
        openai_error = "OpenAI API key là bắt buộc."
    else:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {openai_key}"},
                )
            if response.status_code == 200:
                openai_valid = True
            elif response.status_code in {401, 403}:
                openai_error = "OpenAI API key không hợp lệ hoặc không có quyền truy cập."
            elif response.status_code == 429:
                openai_error = "OpenAI API key đang bị giới hạn tốc độ hoặc hết quota."
            else:
                openai_error = f"OpenAI trả về lỗi {response.status_code}."
        except httpx.TimeoutException:
            openai_error = "Không kiểm tra được OpenAI API key do timeout."
        except httpx.HTTPError:
            openai_error = "Không kết nối được tới OpenAI để kiểm tra key."

    if serper_key:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": serper_key,
                        "Content-Type": "application/json",
                    },
                    json={"q": "test", "num": 1},
                )
            if response.status_code == 200:
                serper_valid = True
            elif response.status_code in {401, 403}:
                serper_valid = False
                serper_error = "Serper API key không hợp lệ hoặc không có quyền truy cập."
            elif response.status_code == 429:
                serper_valid = False
                serper_error = "Serper API key đang bị giới hạn tốc độ hoặc hết quota."
            else:
                serper_valid = False
                serper_error = f"Serper trả về lỗi {response.status_code}."
        except httpx.TimeoutException:
            serper_valid = False
            serper_error = "Không kiểm tra được Serper API key do timeout."
        except httpx.HTTPError:
            serper_valid = False
            serper_error = "Không kết nối được tới Serper để kiểm tra key."

    if openai_valid and serper_valid is False:
        message = "OpenAI hợp lệ, nhưng Serper API key có lỗi."
    elif openai_valid:
        message = "API key hợp lệ để tiếp tục."
    else:
        message = openai_error or "OpenAI API key không hợp lệ."

    return ByokValidateResponse(
        openai_valid=openai_valid,
        serper_valid=serper_valid,
        openai_error=openai_error,
        serper_error=serper_error,
        message=message,
    )
