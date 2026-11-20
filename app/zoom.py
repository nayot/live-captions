"""Posts caption lines to Zoom's third-party caption API, in order, with an increasing `seq`."""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

log = logging.getLogger("live_captions.zoom")


def mask(url: str) -> str:
    return re.sub(r"(token|id|key|signature)=[^&]+", r"\1=****", url, flags=re.I) if url else ""


def chunk(text: str, max_chars: int) -> list[str]:
    """Split into pieces <= max_chars, preferring spaces (Thai often has few), then hard cuts."""
    text = " ".join(text.split())
    out: list[str] = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        if cut < max_chars // 2:
            cut = max_chars
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


class ZoomPoster:
    def __init__(self, lang: str, max_chars: int, client: httpx.AsyncClient | None = None) -> None:
        self.lang, self.max_chars = lang, max_chars
        self._url = ""
        self.seq = 1
        self.posted = 0
        self.last_status: int | None = None
        self.last_error = ""
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self._client = client or httpx.AsyncClient(timeout=8.0)
        self._task: asyncio.Task | None = None

    # --- control -------------------------------------------------------
    def set_url(self, url: str, reset_seq: bool = False) -> None:
        self._url = url.strip()
        if reset_seq:
            self.seq = 1
        self.last_error, self.last_status = "", None
        log.info("Zoom caption URL set: %s", mask(self._url))

    def clear(self) -> None:
        self._url = ""

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "url": mask(self._url),
            "seq": self.seq,
            "posted": self.posted,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "queued": self._q.qsize(),
        }

    # --- sending ------------------------------------------------------
    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self._client.aclose()

    def enqueue(self, text: str) -> None:
        if not self.enabled or not text.strip():
            return
        for piece in chunk(text, self.max_chars):
            if self._q.full():  # never fall far behind live speech
                self._q.get_nowait()
            self._q.put_nowait(piece)

    async def _post(self, text: str) -> bool:
        sep = "&" if "?" in self._url else "?"
        url = f"{self._url}{sep}seq={self.seq}&lang={quote(self.lang)}"
        try:
            r = await self._client.post(
                url, content=text.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"}
            )
            self.last_status = r.status_code
            if r.status_code < 300:
                self.posted += 1
                self.last_error = ""
                return True
            self.last_error = r.text[:120]
        except httpx.HTTPError as e:
            self.last_status, self.last_error = 0, type(e).__name__
        return False

    async def _worker(self) -> None:
        while True:
            text = await self._q.get()
            if not self.enabled:
                continue
            ok = await self._post(text)
            if not ok:
                await asyncio.sleep(1.0)
                ok = await self._post(text)
            self.seq += 1  # always advance: Zoom rejects repeated seq values
            if not ok:
                log.warning("Zoom post failed (status %s): %s", self.last_status, self.last_error)
