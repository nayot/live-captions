"""Audio recording: one WAV file per listening session (Start listening → Stop / server shutdown).

The file is valid at every moment: the WAV header's sizes are rewritten every few seconds and on close,
so even if the process is killed, everything up to the last header update plays back normally.
A brief reconnect (same browser session id) appends to the same file instead of starting a new one.
"""
from __future__ import annotations

import logging
import os
import re
import struct
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("live_captions.recorder")

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # PCM16
HEADER_BYTES = 44
PATCH_EVERY_S = 2.0


def _header(data_bytes: int) -> bytes:
    byte_rate = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate,
                                    CHANNELS * SAMPLE_WIDTH, SAMPLE_WIDTH * 8)
            + b"data" + struct.pack("<I", data_bytes))


class WavRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists() and path.stat().st_size >= HEADER_BYTES:
            self._f = path.open("r+b")
            self._data = path.stat().st_size - HEADER_BYTES
            self._data -= self._data % SAMPLE_WIDTH
            self._f.seek(HEADER_BYTES + self._data)
            self._f.truncate()
        else:
            self._f = path.open("w+b")
            self._data = 0
            self._f.write(_header(0))
        self._last_patch = time.monotonic()

    @property
    def seconds(self) -> float:
        return self._data / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)

    def write(self, pcm: bytes) -> None:
        if self._f.closed:
            return
        self._f.write(pcm)
        self._data += len(pcm)
        if time.monotonic() - self._last_patch >= PATCH_EVERY_S:
            self._patch()

    def _patch(self) -> None:
        end = self._f.tell()
        self._f.seek(0)
        self._f.write(_header(self._data))
        self._f.seek(end)
        self._f.flush()
        os.fsync(self._f.fileno())
        self._last_patch = time.monotonic()

    def close(self) -> None:
        if self._f.closed:
            return
        self._patch()
        self._f.close()
        log.info("Recording saved: %s (%.0f s)", self.path, self.seconds)


class Recordings:
    """Keeps one recorder per browser listening session; a reconnect with the same id appends."""

    def __init__(self, directory: str) -> None:
        self.dir = Path(directory) if directory else None
        self._open: dict[str, WavRecorder] = {}
        self._clients: dict[str, int] = {}
        self._names: dict[str, Path] = {}

    @property
    def enabled(self) -> bool:
        return self.dir is not None

    def attach(self, session_id: str) -> WavRecorder | None:
        if not self.dir:
            return None
        sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:40] or "anon"
        rec = self._open.get(sid)
        if rec is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self._names.get(sid) or self._new_path()
            self._names[sid] = path
            rec = WavRecorder(path)
            self._open[sid] = rec
            log.info("Recording to %s", path)
        self._clients[sid] = self._clients.get(sid, 0) + 1
        return rec

    def _new_path(self) -> Path:
        stem = f"recording-{datetime.now():%Y%m%d-%H%M%S}"
        path, n = self.dir / f"{stem}.wav", 2
        while path.exists() or path in self._names.values():
            path, n = self.dir / f"{stem}-{n}.wav", n + 1
        return path

    def detach(self, session_id: str, final: bool) -> None:
        """Called when an audio socket closes. Finalise the file now; a reconnect reopens and appends."""
        sid = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:40] or "anon"
        self._clients[sid] = max(0, self._clients.get(sid, 1) - 1)
        if self._clients[sid] == 0 and (rec := self._open.pop(sid, None)):
            rec.close()
        if final:
            self._names.pop(sid, None)

    def close_all(self) -> None:
        for sid, rec in list(self._open.items()):
            rec.close()
        self._open.clear()

    def status(self) -> dict:
        recs = list(self._open.values())
        return {"enabled": self.enabled, "recording": bool(recs),
                "file": recs[-1].path.name if recs else "", "seconds": round(recs[-1].seconds) if recs else 0}
