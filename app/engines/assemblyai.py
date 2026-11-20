"""AssemblyAI Universal-Streaming (v3 websocket) speech-to-text.

Env: ASSEMBLYAI_API_KEY. Audio: PCM16 mono 16 kHz, sent as binary frames (50–1000 ms each).
Messages from the server: Begin, Turn {transcript, end_of_turn, turn_is_formatted, turn_order}, Termination.
With format_turns=true an end-of-turn arrives first unformatted, then again formatted; we emit the
formatted one as final, or the unformatted one if the formatted copy doesn't arrive within 1.5 s.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator
from urllib.parse import urlencode

from .base import SttResult

log = logging.getLogger("live_captions.assemblyai")

WS_URL = "wss://streaming.assemblyai.com/v3/ws"
FORMAT_WAIT_S = 1.5
# Reconnect at once after a dropped session (paid plan: 100+ new sessions/min). Only repeated failures
# with no session starting back off, so a refused key or an outage can't become a tight loop.
RETRY_DELAYS_S = (0.0, 0.5, 1, 2, 5, 10)
# Audio queued while reconnecting is trimmed to the last ~2 s (100 ms chunks), so captions resume live
# instead of replaying a backlog.
RESUME_BACKLOG_CHUNKS = 20


class AssemblyAISession:
    def __init__(self, api_key: str, keyterms: list[str], model: str = "") -> None:
        params = {"sample_rate": 16000, "encoding": "pcm_s16le", "format_turns": "true"}
        if model:
            params["speech_model"] = model
        if keyterms:
            params["keyterms_prompt"] = json.dumps(keyterms[:100])
        self._url = f"{WS_URL}?{urlencode(params)}"
        self._key = api_key
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=100)
        self._out: asyncio.Queue[SttResult | None] = asyncio.Queue()
        self._closed = False
        self._pending: dict[int, asyncio.Task] = {}  # turn_order -> fallback emit task
        self._finalised: set[int] = set()
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
        if self._audio.full():  # never block here: the sender may be gone (e.g. AssemblyAI unreachable)
            self._audio.get_nowait()
        self._audio.put_nowait(None)
        self._task.cancel()
        await self._out.put(None)

    async def _emit_final_later(self, order: int, text: str) -> None:
        await asyncio.sleep(FORMAT_WAIT_S)
        if order not in self._finalised:
            self._finalised.add(order)
            await self._out.put(SttResult(text, True))

    async def _handle(self, msg: dict) -> None:
        if msg.get("type") != "Turn":
            if msg.get("type") == "Termination":
                log.info("AssemblyAI session terminated")
            return
        text = (msg.get("transcript") or "").strip()
        order = int(msg.get("turn_order", -1))
        if not text or order in self._finalised:
            return
        if msg.get("end_of_turn") and msg.get("turn_is_formatted"):
            self._finalised.add(order)
            if t := self._pending.pop(order, None):
                t.cancel()
            await self._out.put(SttResult(text, True))
        elif msg.get("end_of_turn"):
            await self._out.put(SttResult(text, False))
            self._pending[order] = asyncio.create_task(self._emit_final_later(order, text))
        else:
            await self._out.put(SttResult(text, False))

    async def _run(self) -> None:
        from websockets.asyncio.client import connect

        failures = 0
        while not self._closed:
            reason = "closed by server"
            try:
                async with connect(self._url, additional_headers={"Authorization": self._key},
                                   max_size=2**22, open_timeout=5) as ws:
                    self._trim_backlog()

                    async def sender():
                        while True:
                            chunk = await self._audio.get()
                            if chunk is None:
                                await ws.send(json.dumps({"type": "Terminate"}))
                                return
                            await ws.send(chunk)

                    send_task = asyncio.create_task(sender())
                    try:
                        async for raw in ws:
                            msg = json.loads(raw)
                            if msg.get("type") == "Begin":
                                failures = 0  # a session really started
                            await self._handle(msg)
                    finally:
                        send_task.cancel()
                    if ws.close_code not in (None, 1000):
                        reason = f"close {ws.close_code} {ws.close_reason or ''}".strip()
            except asyncio.CancelledError:
                return
            except Exception as e:
                reason = type(e).__name__
            if self._closed:
                return
            delay = RETRY_DELAYS_S[min(failures, len(RETRY_DELAYS_S) - 1)]
            failures += 1
            log.warning("AssemblyAI stream ended (%s); reconnecting in %.1fs", reason, delay)
            if delay:
                await asyncio.sleep(delay)

    def _trim_backlog(self) -> None:
        while self._audio.qsize() > RESUME_BACKLOG_CHUNKS:
            if self._audio.get_nowait() is None:  # never drop the stop signal
                self._audio.put_nowait(None)
                break


class AssemblyAIStt:
    name = "assemblyai"

    def __init__(self, api_key: str, keyterms: list[str], model: str = "") -> None:
        if not api_key:
            raise SystemExit("ASSEMBLYAI_API_KEY is required for STT_ENGINE=assemblyai")
        self._key, self._terms, self._model = api_key, keyterms, model
        self.name = f"assemblyai:{model}" if model else "assemblyai"

    async def open(self) -> AssemblyAISession:
        return AssemblyAISession(self._key, self._terms, self._model)
