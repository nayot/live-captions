"""Stub engines: no cloud account needed. Audio is accepted and counted; text comes from /api/inject."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import SttResult

_DEMO = {
    "hello": "สวัสดี",
    "welcome": "ยินดีต้อนรับ",
    "everyone": "ทุกคน",
    "thank you": "ขอบคุณ",
    "students": "นิสิต",
    "industry": "อุตสาหกรรม",
    "electronics": "อิเล็กทรอนิกส์",
}


class StubSession:
    def __init__(self) -> None:
        self.bytes_in = 0
        self._q: asyncio.Queue[SttResult | None] = asyncio.Queue()

    async def push_audio(self, pcm: bytes) -> None:
        self.bytes_in += len(pcm)

    async def results(self) -> AsyncIterator[SttResult]:
        while (r := await self._q.get()) is not None:
            yield r

    async def close(self) -> None:
        await self._q.put(None)


class StubStt:
    name = "stub"

    async def open(self) -> StubSession:
        return StubSession()


class StubTranslator:
    """Word-swap 'translation' so the Thai path and fonts can be tested offline."""

    name = "stub"

    async def translate(self, text: str, final: bool = True) -> str:
        out = text
        for en, th in _DEMO.items():
            out = out.replace(en, th).replace(en.capitalize(), th)
        return f"[TH] {out}"
