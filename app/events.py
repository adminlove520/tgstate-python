import logging
import asyncio
from typing import Optional

class BroadcastEventBus:
    def __init__(self, queue_maxsize: int = 200):
        self._queue_maxsize = queue_maxsize
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, data: str) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass

    async def put(self, data: str) -> None:
        await self.publish(data)


file_update_queue = BroadcastEventBus()


def build_file_event(
    *,
    action: str,
    file_id: str,
    filename: Optional[str] = None,
    filesize: Optional[int] = None,
    upload_date: Optional[str] = None,
    short_id: Optional[str] = None,
) -> dict:
    return {
        "action": action,
        "file_id": file_id,
        "filename": filename,
        "filesize": filesize,
        "upload_date": upload_date,
        "short_id": short_id,
    }
