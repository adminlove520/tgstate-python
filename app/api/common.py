from __future__ import annotations

import logging
from fastapi import Request, HTTPException, status
from typing import Any, Optional

from ..core.config import get_active_password

logger = logging.getLogger(__name__)


def error_payload(message: str, *, code: str = "error", details: Optional[Any] = None) -> dict:
    payload = {"status": "error", "code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return payload


def http_error(status_code: int, message: str, *, code: str = "error", details: Optional[Any] = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail=error_payload(message, code=code, details=details))


def is_web_upload_request(request: Request) -> bool:
    return "referer" in request.headers


import re

COOKIE_NAME = "tgstate_session"

def ensure_upload_auth(request: Request, app_settings: dict, submitted_key: str | None) -> None:
    picgo_api_key = app_settings.get("PICGO_API_KEY")
    active_password = app_settings.get("PASS_WORD") or get_active_password()
    web_request = is_web_upload_request(request)

    if not active_password and not picgo_api_key:
        return

    if picgo_api_key and not active_password:
        if web_request:
            return
        if picgo_api_key == submitted_key:
            return
        logger.warning("API 上传鉴权失败：无效 API Key")
        raise http_error(401, "无效的 API 密钥", code="invalid_api_key")

    if not picgo_api_key and active_password:
        if not web_request:
            return
        # Fix: use correct cookie name
        session_password = request.cookies.get(COOKIE_NAME)
        if active_password == session_password:
            return
        logger.warning("Web 上传鉴权失败：需要登录")
        raise http_error(401, "需要网页登录", code="login_required")

    if web_request:
        session_password = request.cookies.get(COOKIE_NAME)
        if active_password == session_password:
            return
        logger.warning("Web 上传鉴权失败：需要登录")
        raise http_error(401, "需要网页登录", code="login_required")

    if picgo_api_key == submitted_key:
        return
    logger.warning("API 上传鉴权失败：无效 API Key")
    raise http_error(401, "无效的 API 密钥", code="invalid_api_key")

