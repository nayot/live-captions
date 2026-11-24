"""Soniox real-time speech-to-text (WebSocket). Hears English and Thai in one stream, mixed sentences included.

Env: SONIOX_API_KEY, SONIOX_MODEL (default stt-rt-v6). Audio: PCM16 mono 16 kHz, sent as binary frames.
Protocol: the first text frame is the config; each response carries `tokens`. Final tokens arrive once and never
change; non-final tokens are re-sent (replaced) in every response. A final "<end>" token closes a segment
(endpoint detection), which we emit as one finished line. An empty text frame ends the stream.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from .base import SttResult

log = logging.getLogger("live_captions.soniox")

WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
DEFAULT_MODEL = "stt-rt-v6"
RETRY_DELAYS_S = (0.0, 0.5, 1, 2, 5, 10)
RESUME_BACKLOG_CHUNKS = 20  # ~2 s of 100 ms chunks kept while reconnecting
MARKERS = {"<end>", "<fin>"}
# Speakers who don't pause would otherwise produce one endless line (endpoints come only at pauses).
# Once a line reaches max_chars we end it at the next word or sentence boundary; at 1.5x we end it anyway.
DEFAULT_MAX_CHARS = 50
SENTENCE_END = (".", "?", "!", "。")


class SonioxSession:
    def __init__(self, api_key: str, terms: list[str], model: str = "", languages: list[str] | None = None,
                 max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self._key = api_key
        self._max = max_chars
        self._config = {
            "model": model or DEFAULT_MODEL,
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
            "language_hints": languages or ["en", "th"],
            "enable_language_identification": True,
            "enable_endpoint_detection": True,
            "client_reference_id": "live-captions",
        }
        if terms:
            self._config["context"] = {"terms": terms}
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=100)
        self._out: asyncio.Queue[SttResult | None] = asyncio.Queue()
        self._closed = False
        self._final = ""        # final text of the current segment, not yet emitted
        self._last_interim = ""
        self._task = asyncio.create_task(self._run())

    async def push_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        if self._audio.full():
            self._audio.get_nowait()
        await self._audio.put(pcm)

    async def results(self) -> AsyncIterator[SttResult]:
        while (r := await self._out.get()) is not None:
            yield r

    async def close(self) -> None:
        self._closed = True
        if self._audio.full():
            self._audio.get_nowait()
        self._audio.put_nowait(None)
        self._task.cancel()
        await self._flush()
        await self._out.put(None)

    async def _flush(self) -> None:
        """Emit whatever final text is pending as a finished line."""
        text = self._final.strip()
        self._final, self._last_interim = "", ""
        if text:
            await self._out.put(SttResult(text, True))

    async def handle(self, msg: dict) -> None:
        if msg.get("error_code") or msg.get("error_type"):
            log.warning("Soniox error %s %s: %s", msg.get("error_code"), msg.get("error_type"),
                        msg.get("error_message", ""))
            return
        nonfinal = ""
        for t in msg.get("tokens") or []:
            text = t.get("text", "")
            if t.get("is_final"):
                if text == "<end>":
                    await self._flush()
                elif text not in MARKERS:
                    if self._should_break(text):
                        await self._flush()
                    self._final += text
            elif text not in MARKERS:
                nonfinal += text
        interim = (self._final + nonfinal).strip()
        if interim and interim != self._last_interim:
            self._last_interim = interim
            await self._out.put(SttResult(interim, False))

    def _should_break(self, next_text: str) -> bool:
        """End the current line before `next_text`? Only at a boundary unless the line is far too long."""
        n = len(self._final.strip())
        if not self._max or n < self._max:
            return False
        boundary = next_text[:1].isspace() or self._final.rstrip().endswith(SENTENCE_END + (",",))
        return boundary or n >= self._max * 1.5

    async def _run(self) -> None:
        from websockets.asyncio.client import connect

        failures = 0
        while not self._closed:
            reason = "closed by server"
            try:
                async with connect(WS_URL, additional_headers={"Authorization": f"Bearer {self._key}"},
                                   max_size=2**22, open_timeout=5) as ws:
                    await ws.send(json.dumps(self._config))
                    self._trim_backlog()

                    async def sender():
                        while True:
                            chunk = await self._audio.get()
                            if chunk is None:
                                await ws.send("")  # empty text frame = end of stream
                                return
                            await ws.send(chunk)

                    send_task = asyncio.create_task(sender())
                    try:
                        async for raw in ws:
                            msg = json.loads(raw)
                            if msg.get("tokens"):
                                failures = 0  # the stream is really working
                            await self.handle(msg)
                            if msg.get("finished"):
                                break
                    finally:
                        send_task.cancel()
                    if ws.close_code not in (None, 1000):
                        reason = f"close {ws.close_code} {ws.close_reason or ''}".strip()
            except asyncio.CancelledError:
                return
            except Exception as e:
                reason = type(e).__name__
            await self._flush()  # don't lose a half-finished line across a reconnect
            if self._closed:
                return
            delay = RETRY_DELAYS_S[min(failures, len(RETRY_DELAYS_S) - 1)]
            failures += 1
            log.warning("Soniox stream ended (%s); reconnecting in %.1fs", reason, delay)
            if delay:
                await asyncio.sleep(delay)

    def _trim_backlog(self) -> None:
        while self._audio.qsize() > RESUME_BACKLOG_CHUNKS:
            if self._audio.get_nowait() is None:
                self._audio.put_nowait(None)
                break


class SonioxStt:
    name = "soniox"

    def __init__(self, api_key: str, terms: list[str], model: str = "", max_chars: int = DEFAULT_MAX_CHARS) -> None:
        if not api_key:
            raise SystemExit("SONIOX_API_KEY is required for STT_ENGINE=soniox")
        self._key, self._terms, self._model = api_key, terms, model or DEFAULT_MODEL
        self._max_chars = max_chars
        self.name = f"soniox:{self._model}"

    async def open(self) -> SonioxSession:
        return SonioxSession(self._key, self._terms, self._model, max_chars=self._max_chars)
