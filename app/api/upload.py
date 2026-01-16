from __future__ import annotations

import os
import shutil
import tempfile
import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, Request

from ..core.config import Settings, get_app_settings, get_settings
from ..services.telegram_service import get_telegram_service
from .common import ensure_upload_auth, http_error


router = APIRouter()
logger = logging.getLogger(__name__)


import re
from .common import ensure_upload_auth, http_error

@router.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    key: Optional[str] = Form(None),
    settings: Settings = Depends(get_settings),
    x_api_key: Optional[str] = Header(None),
):
    app_settings = get_app_settings()
    if not (app_settings.get("BOT_TOKEN") or "").strip() or not (app_settings.get("CHANNEL_NAME") or "").strip():
        raise http_error(503, "缺少 BOT_TOKEN 或 CHANNEL_NAME，无法上传", code="cfg_missing")
    ensure_upload_auth(request, app_settings, x_api_key or key)
    logger.info("开始上传: %s", file.filename)

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        telegram_service = get_telegram_service()
        file_id = await telegram_service.upload_file(temp_file_path, file.filename)
    except Exception as e:
        logger.error("上传失败: %s: %s", file.filename, e)
        raise http_error(500, "文件上传失败。", code="upload_failed", details=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass

    if not file_id:
        logger.error("上传失败（未返回 file_id）: %s", file.filename)
        raise http_error(500, "文件上传失败。", code="upload_failed")

    # 构造短链 URL: /d/{short_id}
    # 这里的 file_id 实际上是 short_id
    file_path = f"/d/{file_id}"
    
    # PicGo 需要绝对路径
    base_url = (app_settings.get("BASE_URL") or "").rstrip("/")
    if base_url:
        full_url = f"{base_url}{file_path}"
    else:
        # Fallback if no BASE_URL set (though config usually defaults)
        full_url = file_path

    logger.info("上传成功: %s -> %s", file.filename, file_id)
    return {
        "file_id": file_id,          # 这里的 file_id 是用于分享的 ID (即 short_id)
        "short_id": file_id,         # 兼容旧字段
        "download_path": file_path,  # 用户要求的字段
        "path": file_path,           # 兼容旧字段
        "url": str(full_url)         # 兼容旧字段
    }

