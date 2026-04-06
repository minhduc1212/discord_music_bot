import asyncio
from enum import Enum
from typing import Any

import discord
import yt_dlp

from .logger import log
from .config import YTDL_SINGLE_OPTIONS

class LoopState(Enum):
    OFF   = 0
    SONG  = 1
    QUEUE = 2

    def next(self) -> "LoopState":
        vals = list(LoopState)
        return vals[(self.value + 1) % len(vals)]

    def label(self) -> str:
        return {LoopState.OFF: "Tắt", LoopState.SONG: "Bài", LoopState.QUEUE: "Queue"}[self]

    def emoji(self) -> str:
        return {LoopState.OFF: "➡️", LoopState.SONG: "🔂", LoopState.QUEUE: "🔁"}[self]


class Song:
    def __init__(self, data: dict, requester: discord.Member):
        is_flat = bool(data.get("ie_key"))
        if is_flat:
            vid = data.get("id") or ""
            self.webpage_url = data.get("url") or (
                f"https://www.youtube.com/watch?v={vid}" if vid else ""
            )
            self.stream_url = None
        else:
            self.webpage_url = data.get("webpage_url") or ""
            self.stream_url  = data.get("url")

        self.title     = data.get("title")    or "Không rõ tên"
        self.duration  = data.get("duration") or 0
        self.thumbnail = data.get("thumbnail")
        self.uploader  = data.get("uploader") or data.get("channel") or "Không rõ"
        self.requester = requester

    async def get_stream_url(self) -> str | None:
        if self.stream_url:
            return self.stream_url
        try:
            log.info(f"Fetching: {self.title}")
            loop = asyncio.get_event_loop()

            def _extract():
                with yt_dlp.YoutubeDL(YTDL_SINGLE_OPTIONS) as ydl: # type: ignore
                    info = ydl.extract_info(self.webpage_url, download=False)
                    if not self.thumbnail:
                        self.thumbnail = info.get("thumbnail")
                    if not self.duration:
                        self.duration = info.get("duration") or 0
                    return info.get("url")

            self.stream_url = await loop.run_in_executor(None, _extract)
            return self.stream_url
        except Exception as e:
            log.error(f"Không lấy được stream '{self.title}': {e}")
            return None

    def fmt_duration(self) -> str:
        if self.duration and self.duration > 0:
            m, s = divmod(int(self.duration), 60)
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        return "??:??"