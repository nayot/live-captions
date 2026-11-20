"""Engine interfaces. Each engine is small so it can be swapped or stubbed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class SttResult:
    text: str
    final: bool


class SttSession(Protocol):
    """One live audio stream: PCM16 mono 16 kHz in, transcripts out."""

    async def push_audio(self, pcm: bytes) -> None: ...

    def results(self) -> AsyncIterator[SttResult]: ...

    async def close(self) -> None: ...


class SttEngine(Protocol):
    name: str

    async def open(self) -> SttSession: ...


class Translator(Protocol):
    name: str

    async def translate(self, text: str, final: bool = True) -> str: ...
