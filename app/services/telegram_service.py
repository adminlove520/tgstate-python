import asyncio
import io
import logging
import os
from functools import lru_cache

import telegram
from telegram.request import HTTPXRequest

from ..core.config import get_app_settings
from .. import database

# Telegram Bot API 对通过 getFile 方法下载的文件有 20MB 的限制。
# tgState 将文件按 19.5MB 分块上传，并通过 .manifest 文件记录原始文件名与分块列表。
CHUNK_SIZE_BYTES = int(19.5 * 1024 * 1024)

logger = logging.getLogger(__name__)

class TelegramService:
    """
    用于与 Telegram Bot API 交互的服务。
    """
    def __init__(self, bot_token: str, channel_name: str):
        # 为大文件上传设置更长的超时时间 (例如 5 分钟)
        # 获取代理设置
        settings = get_app_settings()
        proxy_url = settings.get("HTTPS_PROXY") or settings.get("HTTP_PROXY")

        # 为大文件上传设置更长的超时时间 (例如 5 分钟)
        request_kwargs = {
            "connect_timeout": 300.0,
            "read_timeout": 300.0,
            "write_timeout": 300.0,
        }
        
        # 如果有代理，显式传递给 HTTPXRequest
        # 注意: python-telegram-bot 的 HTTPXRequest 可能需要 proxy_url 参数
        if proxy_url:
            request_kwargs["proxy_url"] = proxy_url

        request = HTTPXRequest(**request_kwargs)
        self.bot = telegram.Bot(token=bot_token, request=request)
        self.channel_name = channel_name

    async def _upload_chunk(self, chunk_data: bytes, chunk_name: str) -> str | None:
        """一个上传单个数据块的辅助函数。"""
        try:
            with io.BytesIO(chunk_data) as document_chunk:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=document_chunk,
                    filename=chunk_name
                )
            if message.document:
                return message.document.file_id
        except Exception as e:
            logger.error("上传分块 %s 到 Telegram 时出错: %s", chunk_name, e)
        return None

    async def _upload_as_chunks(self, file_path: str, original_filename: str) -> str | None:
        """
        将大文件分割成块，并通过回复链将所有部分聚合起来。
        """
        chunk_file_ids = []
        first_message_id = None
        
        try:
            with open(file_path, "rb") as f:
                chunk_number = 1
                while True:
                    chunk = f.read(CHUNK_SIZE_BYTES)
                    if not chunk:
                        break
                    
                    chunk_name = f"{original_filename}.part{chunk_number}"
                    logger.info("正在上传分块: %s", chunk_name)
                    
                    with io.BytesIO(chunk) as chunk_io:
                        # 如果是第一个块，正常发送。否则，作为对第一个块的回复发送。
                        reply_to_id = first_message_id if first_message_id else None
                        message = await self.bot.send_document(
                            chat_id=self.channel_name,
                            document=chunk_io,
                            filename=chunk_name,
                            reply_to_message_id=reply_to_id
                        )
                    
                    # 如果是第一个块，保存其 message_id
                    if not first_message_id:
                        first_message_id = message.message_id
                    
                    # 关键变更：存储复合ID (message_id:file_id) 而不是只有 file_id
                    chunk_file_ids.append(f"{message.message_id}:{message.document.file_id}")
                    chunk_number += 1
        except IOError as e:
            logger.error("读取或上传文件块时出错: %s", e)
            return None
        except Exception as e:
            logger.error("发送文件块时出错: %s", e)
            return None

        # 生成并上传清单文件，同样作为对第一个块的回复
        manifest_content = f"tgstate-blob\n{original_filename}\n" + "\n".join(chunk_file_ids)
        manifest_name = f"{original_filename}.manifest"
        
        logger.info("所有分块上传完毕。正在上传清单文件")
        try:
            with io.BytesIO(manifest_content.encode('utf-8')) as manifest_file:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=manifest_file,
                    filename=manifest_name,
                    reply_to_message_id=first_message_id
                )
            if message.document:
                logger.info("清单文件上传成功")
                # 将大文件的元数据存入数据库
                total_size = os.path.getsize(file_path)
                # 创建复合ID，格式为 "message_id:file_id"
                composite_id = f"{message.message_id}:{message.document.file_id}"
                short_id = database.add_file_metadata(
                    filename=original_filename,
                    file_id=composite_id, # 我们存储复合ID
                    filesize=total_size
                )
                return short_id # 返回 short_id
        except Exception as e:
            logger.error("上传清单文件时出错: %s", e)
        
        return None

    async def upload_file(self, file_path: str, file_name: str) -> str | None:
        """
        将文件上传到指定的 Telegram 频道。
        如果文件大小大于等于 CHUNK_SIZE_BYTES (约 19.5MB)，则使用分块 + manifest 机制上传。
        
        参数:
            file_path: 文件的本地路径。
            file_name: 文件名。

        返回:
            如果成功，则返回文件的 short_id，否则返回 None。
        """
        if not self.channel_name:
            logger.error("环境变量中未设置 CHANNEL_NAME")
            return None
        
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.error("无法获取文件大小: %s", e)
            return None

        if file_size >= CHUNK_SIZE_BYTES:
            logger.info(
                "文件大小 %.2fMB >= %.2fMB，启动分块上传",
                file_size / 1024 / 1024,
                CHUNK_SIZE_BYTES / 1024 / 1024,
            )
            return await self._upload_as_chunks(file_path, file_name)
        
        logger.info(
            "文件大小 %.2fMB < %.2fMB，直接上传",
            file_size / 1024 / 1024,
            CHUNK_SIZE_BYTES / 1024 / 1024,
        )
        try:
            with open(file_path, "rb") as document_file:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=document_file,
                    filename=file_name
                )
            if message.document:
                # 将小文件的元数据存入数据库
                # 创建复合ID，格式为 "message_id:file_id"
                composite_id = f"{message.message_id}:{message.document.file_id}"
                short_id = database.add_file_metadata(
                    filename=file_name,
                    file_id=composite_id, # 存储复合ID
                    filesize=file_size
                )
                return short_id # 返回 short_id
        except Exception as e:
            logger.error("上传文件到 Telegram 时出错: %s", e)
        
        return None

    async def get_download_url(self, file_id: str) -> str | None:
        """
        为给定的 file_id 获取临时下载链接。

        参数:
            file_id: 来自 Telegram 的文件 ID。

        返回:
            如果成功，则返回临时下载链接，否则返回 None。
        """
        try:
            file = await self.bot.get_file(file_id)
            return file.file_path
        except Exception as e:
            logger.error("从 Telegram 获取下载链接时出错: %s", e)
            return None

    async def try_get_manifest_original_filename(self, manifest_file_id: str) -> tuple[bool, str | None, str | None]:
        download_url = await self.get_download_url(manifest_file_id)
        if not download_url:
            return False, None, "无法获取下载链接（文件可能已过期或不存在）"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(download_url)
                resp.raise_for_status()
        except Exception as e:
            return False, None, f"下载清单失败：{e}"

        content = resp.content
        if not content.startswith(b"tgstate-blob\n"):
            return False, None, "清单格式不正确（缺少 tgstate-blob 头）"

        try:
            lines = content.decode("utf-8").strip().split("\n")
        except Exception as e:
            return False, None, f"清单解码失败：{e}"

        if len(lines) < 2 or not lines[1].strip():
            return False, None, "清单缺少原始文件名"

        return True, lines[1].strip(), None

    async def delete_message(self, message_id: int) -> tuple[bool, str]:
        """
        从频道中删除指定 ID 的消息。

        参数:
            message_id: 要删除的消息的 ID。

        返回:
            一个元组 (success, reason)，其中 success 表示逻辑上是否成功，
            reason 可以是 'deleted', 'not_found', 或 'error'。
        """
        try:
            await self.bot.delete_message(
                chat_id=self.channel_name,
                message_id=message_id
            )
            return (True, "deleted")
        except telegram.error.BadRequest as e:
            if "not found" in str(e).lower():
                logger.info("消息 %s 未找到，视为已删除", message_id)
                return (True, "not_found")
            else:
                logger.warning("删除消息 %s 失败 (BadRequest): %s", message_id, e)
                return (False, "error")
        except Exception as e:
            logger.error("删除消息 %s 时发生未知错误: %s", message_id, e)
            return (False, "error")

    async def delete_file_with_chunks(self, file_id: str) -> dict:
        """
        完全删除一个文件，包括其所有可能的分块。
        该函数会处理清单文件，并删除所有引用的分块。

        参数:
            file_id: 要删除的文件的复合 ID ("message_id:actual_file_id")。

        返回:
            一个包含删除操作结果的字典。
        """
        results = {
            "status": "pending",
            "main_file_id": file_id,
            "deleted_chunks": [],
            "failed_chunks": [],
            "main_message_deleted": False,
            "main_delete_reason": "",
            "is_manifest": False,
            "reason": ""
        }

        try:
            main_message_id_str, main_actual_file_id = file_id.split(':', 1)
            main_message_id = int(main_message_id_str)
        except (ValueError, IndexError):
            results["status"] = "error"
            results["reason"] = "Invalid composite file_id format."
            return results

        # 步骤 1: 检查文件是否为清单
        download_url = await self.get_download_url(main_actual_file_id)
        if not download_url:
            logger.warning("无法为文件 %s 获取下载链接，将只尝试删除主消息", main_actual_file_id)
            results["reason"] = f"Could not get download URL for {main_actual_file_id}."
        else:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(download_url)
                    if response.status_code == 200 and response.content.startswith(b'tgstate-blob\n'):
                        results["is_manifest"] = True
                        logger.info("文件 %s 是清单文件，开始删除分块", file_id)
                        
                        manifest_content = response.content.decode('utf-8')
                        lines = manifest_content.strip().split('\n')
                        chunk_composite_ids = [cid for cid in lines[2:] if cid.strip()]

                        chunk_items: list[tuple[str, int]] = []
                        for chunk_id in chunk_composite_ids:
                            try:
                                chunk_message_id_str, _ = chunk_id.split(":", 1)
                                chunk_items.append((chunk_id, int(chunk_message_id_str)))
                            except Exception as e:
                                logger.warning("处理分块ID %s 时出错: %s", chunk_id, e)
                                results["failed_chunks"].append(chunk_id)

                        semaphore = asyncio.Semaphore(10)

                        async def delete_one(chunk_id: str, message_id: int) -> tuple[str, bool]:
                            async with semaphore:
                                ok, _ = await self.delete_message(message_id)
                                return chunk_id, ok

                        tasks = [asyncio.create_task(delete_one(chunk_id, mid)) for chunk_id, mid in chunk_items]
                        for fut in asyncio.as_completed(tasks):
                            try:
                                chunk_id, ok = await fut
                                if ok:
                                    results["deleted_chunks"].append(chunk_id)
                                else:
                                    results["failed_chunks"].append(chunk_id)
                            except Exception as e:
                                logger.error("删除分块时出错: %s", e)
            except Exception as e:
                error_message = f"下载或解析清单文件 {file_id} 时出错: {e}"
                logger.error(error_message)
                results["reason"] += " " + error_message
                # 即使清单处理失败，我们也要继续尝试删除主消息

        # 步骤 2: 删除主消息 (清单文件本身或单个文件)
        main_message_deleted, delete_reason = await self.delete_message(main_message_id)
        results["main_message_deleted"] = main_message_deleted
        results["main_delete_reason"] = delete_reason
        
        if main_message_deleted:
            if delete_reason == "deleted":
                logger.info("主消息 %s 已成功删除", main_message_id)
            elif delete_reason == "not_found":
                logger.info("主消息 %s 在 Telegram 中未找到，视为成功", main_message_id)
        else:
            logger.warning("删除主消息 %s 失败", main_message_id)

        # 步骤 3: 决定最终状态
        if results["main_message_deleted"] and (not results["is_manifest"] or not results["failed_chunks"]):
             results["status"] = "success"
        else:
             results["status"] = "partial_failure"
             if not results["main_message_deleted"]:
                 results["reason"] += " Failed to delete main message."
             if results["failed_chunks"]:
                 results["reason"] += f" Failed to delete {len(results['failed_chunks'])} chunks."


        return results


    async def list_files_in_channel(self) -> list[dict]:
        """
        遍历频道历史记录，智能地列出所有文件。
        - 小于 CHUNK_SIZE_BYTES 的文件直接显示。
        - 大于等于 CHUNK_SIZE_BYTES 且通过清单管理的文件，显示原始文件名。
        """
        files = []
        # Telegram API 限制 get_chat_history 一次最多返回 100 条
        # 我们需要循环获取，直到没有更多消息
        last_message_id = None
        
        # 为了避免无限循环，我们设置一个最大迭代次数
        MAX_ITERATIONS = 100
        
        logger.info("开始从频道获取历史消息")
        
        for i in range(MAX_ITERATIONS):
            try:
                # 获取一批消息
                messages = await self.bot.get_chat_history(
                    chat_id=self.channel_name,
                    limit=100,
                    offset_id=last_message_id if last_message_id else 0
                )
            except Exception as e:
                logger.error("获取聊天历史时出错: %s", e)
                break

            if not messages:
                logger.info("没有更多历史消息了")
                break

            for message in messages:
                if message.document:
                    doc = message.document
                    # 小于20MB的普通文件
                    if doc.file_size < CHUNK_SIZE_BYTES and not doc.file_name.endswith('.manifest'):
                        files.append({
                            "name": doc.file_name,
                            "file_id": doc.file_id,
                            "size": doc.file_size
                        })
                    # 清单文件
                    elif doc.file_name.endswith('.manifest'):
                        # 下载并解析清单文件以获取原始文件名和大小
                        manifest_url = await self.get_download_url(doc.file_id)
                        if not manifest_url: continue
                        
                        import httpx
                        async with httpx.AsyncClient() as client:
                            try:
                                resp = await client.get(manifest_url)
                                if resp.status_code == 200 and resp.content.startswith(b'tgstate-blob\n'):
                                    lines = resp.content.decode('utf-8').strip().split('\n')
                                    original_filename = lines[1]
                                    # 注意：这里我们无法轻易获得原始总大小，暂时留空
                                    files.append({
                                        "name": original_filename,
                                        "file_id": doc.file_id, # 关键：使用清单文件的ID
                                        "size": None # 标记为未知大小
                                    })
                            except httpx.RequestError:
                                continue
            
            # 设置下一次迭代的偏移量
            last_message_id = messages[-1].message_id
            logger.info("已处理批次 %s，最后的消息 ID: %s", i + 1, last_message_id)

        logger.info("文件列表获取完毕，共找到 %s 个有效文件", len(files))
        return files

@lru_cache()
def get_telegram_service() -> TelegramService:
    """
    TelegramService 的缓存工厂函数。
    """
    settings = get_app_settings()
    bot_token = (settings.get("BOT_TOKEN") or "").strip()
    channel_name = (settings.get("CHANNEL_NAME") or "").strip()
    if not bot_token or not channel_name:
        raise RuntimeError("Telegram 未配置完成")
    return TelegramService(bot_token=bot_token, channel_name=channel_name)
