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


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SessionText:
    """Transcript of one listening session, saved next to its recording as .txt (readable) and .srt
    (subtitles timed to the WAV). Each line is appended and flushed as it is finalised."""

    def __init__(self, wav_path: Path) -> None:
        self.txt, self.srt = wav_path.with_suffix(".txt"), wav_path.with_suffix(".srt")
        self.lines = 0
        if not self.txt.exists():
            with self.txt.open("w", encoding="utf-8") as f:
                f.write(f"Transcript — {wav_path.name}\nStarted {datetime.now():%d.%m.%Y %H:%M:%S}\n\n")

    def add(self, start: float, end: float, lang: str, en: str, th: str) -> None:
        first, second = (("TH", th), ("EN", en)) if lang == "th" else (("EN", en), ("TH", th))
        with self.txt.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {first[0]}: {first[1]}\n")
            if second[1]:
                f.write(f"           {second[0]}: {second[1]}\n")
            f.write("\n")
        end = max(end, start + 1.5)  # keep very short lines readable
        self.lines += 1
        with self.srt.open("a", encoding="utf-8") as f:
            f.write(f"{self.lines}\n{_srt_time(start)} --> {_srt_time(end)}\n{th or en}\n")
            if th and en:
                f.write(f"{en}\n")
            f.write("\n")


class Recordings:
    """Keeps one recorder per browser listening session; a reconnect with the same id appends."""

    def __init__(self, directory: str) -> None:
        self.dir = Path(directory) if directory else None
        self._open: dict[str, WavRecorder] = {}
        self._clients: dict[str, int] = {}
        self._names: dict[str, Path] = {}
        self._text: dict[str, SessionText] = {}
        self._pos: dict[str, float] = {}   # last known recording position per session (kept across gaps)
        self._current = ""                 # session that receives transcript lines
        self.last_text: SessionText | None = None

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
            if sid not in self._text:
                self._text[sid] = SessionText(path)
            self.last_text = self._text[sid]
            log.info("Recording to %s", path)
        self._clients[sid] = self._clients.get(sid, 0) + 1
        self._current = sid
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
            self._pos[sid] = rec.seconds
            rec.close()
        if final:
            self._names.pop(sid, None)
            self._text.pop(sid, None)
            self._pos.pop(sid, None)
            if self._current == sid:
                self._current = ""

    # --- transcript hooks (called by the pipeline) ---------------------------------------------
    def position(self) -> float | None:
        """Seconds into the current recording, or None when no listening session is running."""
        sid = self._current
        if sid not in self._text:
            return None
        rec = self._open.get(sid)
        return rec.seconds if rec else self._pos.get(sid, 0.0)

    def add_line(self, start: float | None, lang: str, en: str, th: str) -> None:
        text = self._text.get(self._current)
        if text is None:
            return
        end = self.position() or 0.0
        text.add(start if start is not None else max(0.0, end - 3), end, lang, en, th)

    def close_all(self) -> None:
        for sid, rec in list(self._open.items()):
            rec.close()
        self._open.clear()
        self._text.clear()
        self._current = ""

    def status(self) -> dict:
        recs = list(self._open.values())
        return {"enabled": self.enabled, "recording": bool(recs),
                "transcript_lines": self.last_text.lines if self.last_text else 0,
                "file": recs[-1].path.name if recs else "", "seconds": round(recs[-1].seconds) if recs else 0}
