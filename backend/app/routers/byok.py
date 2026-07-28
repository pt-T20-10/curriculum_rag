"""
User-provided API key management endpoints.
"""

import httpx
from fastapi import APIRouter, Depends

from app.schemas.byok import (
    CredentialState,
    ByokStatusResponse,
    ByokValidateRequest,
    ByokValidateResponse,
)
from app.security.jwt import get_current_user_id
from app.services.byok_service import (
    generation_mode,
    generation_mode_label,
)

router = APIRouter(prefix="/byok", tags=["byok"])

VALIDATION_MESSAGES = {
    "vi": {
        "openai_required": "OpenAI API key là bắt buộc.",
        "openai_forbidden": "OpenAI API key không hợp lệ hoặc không có quyền truy cập.",
        "openai_quota": "OpenAI API key đang bị giới hạn tốc độ hoặc hết quota.",
        "openai_status": "OpenAI trả về lỗi {status_code}.",
        "openai_timeout": "Không kiểm tra được OpenAI API key do timeout.",
        "openai_connection": "Không kết nối được tới OpenAI để kiểm tra key.",
        "serper_forbidden": "Serper API key không hợp lệ hoặc không có quyền truy cập.",
        "serper_quota": "Serper API key đang bị giới hạn tốc độ hoặc hết quota.",
        "serper_status": "Serper trả về lỗi {status_code}.",
        "serper_timeout": "Không kiểm tra được Serper API key do timeout.",
        "serper_connection": "Không kết nối được tới Serper để kiểm tra key.",
        "openai_ok_serper_error": "OpenAI hợp lệ, nhưng Serper API key có lỗi.",
        "keys_ok": "API key hợp lệ để tiếp tục.",
        "openai_invalid": "OpenAI API key không hợp lệ.",
    },
    "en": {
        "openai_required": "OpenAI API key is required.",
        "openai_forbidden": "OpenAI API key is invalid or does not have access.",
        "openai_quota": "OpenAI API key is rate-limited or out of quota.",
        "openai_status": "OpenAI returned status {status_code}.",
        "openai_timeout": "Could not validate OpenAI API key because the request timed out.",
        "openai_connection": "Could not connect to OpenAI to validate the key.",
        "serper_forbidden": "Serper API key is invalid or does not have access.",
        "serper_quota": "Serper API key is rate-limited or out of quota.",
        "serper_status": "Serper returned status {status_code}.",
        "serper_timeout": "Could not validate Serper API key because the request timed out.",
        "serper_connection": "Could not connect to Serper to validate the key.",
        "openai_ok_serper_error": "OpenAI is valid, but the Serper API key has an error.",
        "keys_ok": "API key is valid to continue.",
        "openai_invalid": "OpenAI API key is invalid.",
    },
}


def _validation_message(language: str, key: str, **values) -> str:
    messages = VALIDATION_MESSAGES["vi" if language == "vi" else "en"]
    return messages[key].format(**values)


async def _status() -> ByokStatusResponse:
    mode = generation_mode()
    return ByokStatusResponse(
        generation_mode=mode,  # type: ignore[arg-type]
        generation_mode_label=generation_mode_label(mode),
        openai=CredentialState(),
        serper=CredentialState(),
    )


@router.get("/status", response_model=ByokStatusResponse)
async def get_byok_status(
    current_user_id: int = Depends(get_current_user_id),
):
    _ = current_user_id
    return await _status()


@router.post("/validate", response_model=ByokValidateResponse)
async def validate_byok_credentials(
    payload: ByokValidateRequest,
    current_user_id: int = Depends(get_current_user_id),
):
    _ = current_user_id
    ui_language = "vi" if payload.ui_language == "vi" else "en"
    msg = lambda key, **values: _validation_message(ui_language, key, **values)
    openai_key = (payload.openai_api_key or "").strip()
    serper_key = (payload.serper_api_key or "").strip()

    openai_valid = False
    serper_valid = None
    openai_error = ""
    serper_error = ""

    if not openai_key:
        openai_error = msg("openai_required")
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
                openai_error = msg("openai_forbidden")
            elif response.status_code == 429:
                openai_error = msg("openai_quota")
            else:
                openai_error = msg("openai_status", status_code=response.status_code)
        except httpx.TimeoutException:
            openai_error = msg("openai_timeout")
        except httpx.HTTPError:
            openai_error = msg("openai_connection")

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
                serper_error = msg("serper_forbidden")
            elif response.status_code == 429:
                serper_valid = False
                serper_error = msg("serper_quota")
            else:
                serper_valid = False
                serper_error = msg("serper_status", status_code=response.status_code)
        except httpx.TimeoutException:
            serper_valid = False
            serper_error = msg("serper_timeout")
        except httpx.HTTPError:
            serper_valid = False
            serper_error = msg("serper_connection")

    if openai_valid and serper_valid is False:
        message = msg("openai_ok_serper_error")
    elif openai_valid:
        message = msg("keys_ok")
    else:
        message = openai_error or msg("openai_invalid")

    return ByokValidateResponse(
        openai_valid=openai_valid,
        serper_valid=serper_valid,
        openai_error=openai_error,
        serper_error=serper_error,
        message=message,
    )
