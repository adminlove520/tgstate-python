from __future__ import annotations

import mimetypes
import logging
from typing import List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import database
from ..core.http_client import get_http_client
from ..services.telegram_service import TelegramService, get_telegram_service
from .common import http_error


router = APIRouter()
logger = logging.getLogger(__name__)

async def serve_file(
    file_id: str,
    filename: str,
    telegram_service: TelegramService,
    client: httpx.AsyncClient,
    request: Request,
    force_download: bool = False
):
    """
    Common logic to serve a file given its file_id (composite) and filename.
    Supports Range requests, Content-Disposition customization.
    """
    try:
        _, real_file_id = file_id.split(":", 1)
    except ValueError:
        real_file_id = file_id

    download_url = await telegram_service.get_download_url(real_file_id)
    if not download_url:
        raise http_error(404, "文件未找到或下载链接已过期。", code="file_not_found")

    # --- Header Preparation ---
    filename_encoded = quote(str(filename))
    
    # 1. Content-Type
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        # 兜底逻辑
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        if ext in ('txt', 'log', 'md', 'json', 'yml', 'yaml', 'ini', 'conf'):
             content_type = "text/plain; charset=utf-8"
        else:
             content_type = "application/octet-stream"
    else:
        # 如果是 text 类型，补充 charset
        if content_type.startswith("text/") and "charset" not in content_type:
             content_type += "; charset=utf-8"

    # 2. Content-Disposition
    # 定义可预览类型白名单
    preview_extensions = (
        # Images
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico",
        # Text/Code
        ".txt", ".md", ".json", ".xml", ".html", ".css", ".js", ".py", ".log",
        # Media
        ".mp4", ".mp3", ".webm", ".ogg", ".wav",
        # Documents
        ".pdf"
    )
    
    is_previewable = filename.lower().endswith(preview_extensions)
    
    if force_download:
        disposition_type = "attachment"
    else:
        disposition_type = "inline" if is_previewable else "attachment"

    common_headers = {
        "Content-Disposition": f"{disposition_type}; filename*=UTF-8''{filename_encoded}",
        "Content-Type": content_type,
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes"
    }

    # --- Range Handling ---
    range_header = request.headers.get("Range")
    
    # First, peek content to check if it's a manifest (TG split file)
    # We only read a small chunk to identify manifest
    try:
        # Use a separate request for head check to avoid consuming the stream
        # However, getting Content-Length for Range support is tricky with TG API if we don't know it.
        # DB has `filesize`, let's use it if possible, but serve_file signature relies on passing it or fetching.
        # Here we just fetch head.
        
        # Optimization: We need to know if it's manifest.
        head_resp = await client.get(download_url, headers={"Range": "bytes=0-127"})
        head_resp.raise_for_status()
        first_bytes = head_resp.content
    except httpx.RequestError as e:
        raise http_error(503, "无法连接到 Telegram 服务器。", code="tg_unreachable", details=str(e))

    # Check for manifest (large file split)
    if first_bytes.startswith(b"tgstate-blob\n"):
        # Manifest processing (No Range support for split files yet, complex to implement)
        manifest_resp = await client.get(download_url)
        manifest_resp.raise_for_status()
        manifest_content = manifest_resp.content

        lines = manifest_content.decode("utf-8").strip().split("\n")
        if len(lines) < 3:
            raise http_error(500, "清单文件格式错误。", code="manifest_invalid")
        # original_filename = lines[1] 
        chunk_file_ids = [cid for cid in lines[2:] if cid.strip()]

        # Force attachment for split files usually, but respect user preference if previewable (e.g. large video?)
        # For now, let's keep basic logic. Streaming split files with Range is hard.
        # We will serve it sequentially without Range support for now.
        return StreamingResponse(
            stream_chunks(chunk_file_ids, telegram_service, client), 
            headers=common_headers
        )

    # Standard Single File
    
    # Get total size for Range
    # We can try HEAD request to TG, but TG presigned URLs sometimes don't support HEAD or return correct Content-Length.
    # We rely on what we can get.
    # Note: Telegram file paths are usually direct to file storage, supporting Range.
    
    async def get_remote_file_size():
        # Try HEAD
        try:
             h_resp = await client.head(download_url)
             if h_resp.headers.get("Content-Length"):
                 return int(h_resp.headers["Content-Length"])
        except:
             pass
        return None

    file_size = await get_remote_file_size()

    if range_header and file_size:
        # Parse Range: bytes=0-1024
        try:
            unit, ranges = range_header.split("=")
            if unit != "bytes": raise ValueError
            start_str, end_str = ranges.split("-")
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
            
            if start >= file_size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
            
            # Correct end if out of bounds
            if end >= file_size:
                end = file_size - 1
                
            length = end - start + 1
            
            common_headers.update({
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length)
            })
            
            # Stream partial content
            async def range_streamer():
                async with client.stream("GET", download_url, headers={"Range": f"bytes={start}-{end}"}) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            
            return StreamingResponse(range_streamer(), status_code=206, headers=common_headers)
            
        except (ValueError, Exception):
            # Fallback to full content if Range parsing fails
            pass

    # Full content stream
    if file_size:
        common_headers["Content-Length"] = str(file_size)

    async def single_file_streamer():
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk

    return StreamingResponse(single_file_streamer(), headers=common_headers)


@router.get("/d/{file_id}/{filename}")
async def download_file_legacy(
    file_id: str,
    filename: str,
    request: Request,
    download: Optional[str] = Query(None), # ?download=1
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Legacy route for downloading files using explicit file_id and filename.
    """
    try:
        telegram_service = get_telegram_service()
    except Exception:
        raise http_error(503, "未配置 BOT_TOKEN/CHANNEL_NAME，下载不可用", code="cfg_missing")

    force_download = download == "1" or download == "true"
    return await serve_file(file_id, filename, telegram_service, client, request, force_download)


@router.get("/d/{identifier}")
async def download_file_short(
    identifier: str,
    request: Request,
    download: Optional[str] = Query(None), # ?download=1
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    New route for downloading files using short_id (or checking file_id).
    """
    try:
        telegram_service = get_telegram_service()
    except Exception:
        raise http_error(503, "未配置 BOT_TOKEN/CHANNEL_NAME，下载不可用", code="cfg_missing")

    # Lookup metadata
    meta = database.get_file_by_id(identifier)
    if not meta:
         raise http_error(404, "文件不存在", code="file_not_found")

    force_download = download == "1" or download == "true"
    return await serve_file(meta['file_id'], meta['filename'], telegram_service, client, request, force_download)


@router.get("/api/files")
async def get_files_list():
    return database.get_all_files()


@router.delete("/api/files/{file_id}")
async def delete_file(
    file_id: str,
):
    try:
        telegram_service = get_telegram_service()
    except Exception:
        raise http_error(503, "未配置 BOT_TOKEN/CHANNEL_NAME，删除不可用", code="cfg_missing")

    logger.info("请求删除文件: %s", file_id)
    delete_result = await telegram_service.delete_file_with_chunks(file_id)

    if delete_result.get("main_message_deleted"):
        was_deleted_from_db = database.delete_file_metadata(file_id)
        delete_result["db_status"] = "deleted" if was_deleted_from_db else "not_found_in_db"
    else:
        # 即使 Telegram 删除失败（可能已手动删除），我们也尝试从 DB 删除，避免死数据
        logger.warning(f"Telegram 删除报告失败 ({delete_result.get('error')})，但尝试强制清理 DB: {file_id}")
        was_deleted_from_db = database.delete_file_metadata(file_id)
        delete_result["db_status"] = "force_deleted" if was_deleted_from_db else "not_found_in_db"

    # 只要 DB 删除了，或者 TG 删除了，我们都视为成功
    if delete_result.get("status") == "success" or delete_result.get("db_status") in ("deleted", "force_deleted"):
        logger.info("删除操作完成: %s", file_id)
        return {"status": "ok", "message": f"文件 {file_id} 已删除。", "details": delete_result}

    if delete_result.get("status") == "partial_failure":
        logger.warning("删除部分失败: %s", file_id)
        raise http_error(500, f"文件 {file_id} 删除部分失败。", code="delete_partial_failure", details=delete_result)

    logger.warning("删除失败: %s", file_id)
    raise http_error(400, f"删除文件 {file_id} 时出错。", code="delete_failed", details=delete_result)


class BatchDeleteRequest(BaseModel):
    file_ids: List[str]


@router.post("/api/batch_delete")
async def batch_delete_files(
    request_data: BatchDeleteRequest,
    telegram_service: TelegramService = Depends(get_telegram_service),
):
    successful_deletions = []
    failed_deletions = []

    for file_id in request_data.file_ids:
        try:
            response = await delete_file(file_id)
            successful_deletions.append(response)
        except Exception as e:
            if hasattr(e, "detail"):
                failed_deletions.append(e.detail)
            else:
                failed_deletions.append({"file_id": file_id, "error": str(e)})

    return {"status": "completed", "deleted": successful_deletions, "failed": failed_deletions}


async def stream_chunks(chunk_composite_ids, telegram_service: TelegramService, client: httpx.AsyncClient):
    for chunk_id in chunk_composite_ids:
        try:
            _, actual_chunk_id = chunk_id.split(":", 1)
        except (ValueError, IndexError):
            continue

        chunk_url = await telegram_service.get_download_url(actual_chunk_id)
        if not chunk_url:
            continue

        try:
            async with client.stream("GET", chunk_url) as chunk_resp:
                if chunk_resp.status_code != 200:
                    await asyncio.sleep(1)
                    chunk_url = await telegram_service.get_download_url(actual_chunk_id)
                    if not chunk_url:
                        break
                    async with client.stream("GET", chunk_url) as retry_resp:
                        retry_resp.raise_for_status()
                        async for chunk_data in retry_resp.aiter_bytes():
                            yield chunk_data
                else:
                    async for chunk_data in chunk_resp.aiter_bytes():
                        yield chunk_data
        except httpx.RequestError:
            break
