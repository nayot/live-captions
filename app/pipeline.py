"""Glue: STT results -> translation -> display broadcast + Zoom captions + transcript log."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import WebSocket

from .engines.base import SttResult, Translator, detect_lang
from .zoom import ZoomPoster

log = logging.getLogger("live_captions.pipeline")

# Each line's language is detected from its script: English is translated to Thai, Thai to English.
# Events carry `src` (what was said), `lang` ("en"/"th") and, once translated, `tr`; finals also carry
# `en` and `th` (the English and the Thai text, whichever was spoken), so the display can always show
# Thai large and English small.
# Draft translation while the speaker is still talking: re-translate the growing sentence at most this often,
# once it has a few words. Only finished sentences go to Zoom (its captions can't be edited in place).
INTERIM_TRANSLATE_EVERY_S = 1.0
INTERIM_MIN_CHARS = 15


class Broadcaster:
    def __init__(self, history: int = 6) -> None:
        self.clients: set[WebSocket] = set()
        self.history: deque[dict] = deque(maxlen=history)

    async def add(self, ws: WebSocket) -> None:
        self.clients.add(ws)
        for msg in self.history:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    def remove(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, msg: dict, keep: bool = False) -> None:
        if keep:
            self.history.append(msg)
        data = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                self.clients.discard(ws)


class Pipeline:
    def __init__(self, translator: Translator, zoom: ZoomPoster, transcript_dir: str = "") -> None:
        self.translator, self.zoom = translator, zoom
        self.bus = Broadcaster()
        self.utterance = 0  # increments on every final result
        self.finals = 0
        self.errors = 0
        self._finals_q: asyncio.Queue[tuple[int, str, str]] = asyncio.Queue()
        self._last_interim_tr = 0.0
        self._interim_task: asyncio.Task | None = None
        self._worker: asyncio.Task | None = None
        self._log_path = None
        if transcript_dir:
            d = Path(transcript_dir)
            d.mkdir(parents=True, exist_ok=True)
            self._log_path = d / f"transcript-{datetime.now():%Y%m%d-%H%M%S}.tsv"

    def start(self) -> None:
        self.zoom.start()
        if not self._worker:
            self._worker = asyncio.create_task(self._finals_worker())

    async def on_stt(self, r: SttResult) -> None:
        if not r.text:
            return
        if r.final:
            uid = self.utterance
            self.utterance += 1
            self._last_interim_tr = 0.0
            lang = detect_lang(r.text)
            await self.bus.send({"type": "final_src", "id": uid, "src": r.text, "lang": lang})
            await self._finals_q.put((uid, r.text, lang))
        else:
            await self.bus.send({"type": "interim", "id": self.utterance, "src": r.text,
                                 "lang": detect_lang(r.text)})
            now = time.monotonic()
            if (
                len(r.text) >= INTERIM_MIN_CHARS
                and now - self._last_interim_tr >= INTERIM_TRANSLATE_EVERY_S
                and not (self._interim_task and not self._interim_task.done())
            ):
                self._last_interim_tr = now
                self._interim_task = asyncio.create_task(self._interim_translate(self.utterance, r.text))

    async def _interim_translate(self, uid: int, text: str) -> None:
        try:
            lang = detect_lang(text)
            tr = await self.translator.translate(text, final=False, source=lang)
        except Exception as e:
            log.warning("interim translate failed: %s", e)
            return
        if uid == self.utterance:  # still the same utterance
            await self.bus.send({"type": "interim_tr", "id": uid, "tr": tr, "lang": lang})

    async def _finals_worker(self) -> None:
        """Translate finals strictly in order, so captions never arrive out of sequence."""
        while True:
            uid, src, lang = await self._finals_q.get()
            try:
                tr = await self.translator.translate(src, source=lang)
            except Exception as e:
                self.errors += 1
                log.warning("translate failed: %s", e)
                tr = ""
            self.finals += 1
            en, th = (tr, src) if lang == "th" else (src, tr)
            await self.bus.send({"type": "final", "id": uid, "lang": lang, "src": src, "tr": tr,
                                 "en": en, "th": th}, keep=True)
            self.zoom.enqueue(th or en)  # Zoom gets the Thai line: the translation, or what a Thai speaker said
            if self._log_path:
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(f"{datetime.now():%H:%M:%S}\t{lang}\t{en}\t{th}\n")
