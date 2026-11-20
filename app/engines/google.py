"""Google Cloud engines: streaming Speech-to-Text (v1) and Translation (v3).

Credentials: Application Default Credentials (`gcloud auth application-default login`) or
GOOGLE_APPLICATION_CREDENTIALS pointing to a key file kept outside the repo. Needs GOOGLE_CLOUD_PROJECT with
the Speech-to-Text and Cloud Translation APIs enabled. Install with: uv sync --extra google
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import AsyncIterator

from .base import SttResult

log = logging.getLogger("live_captions.google")

STREAM_LIMIT_S = 280  # Google closes streams at ~305 s; restart before that


class GoogleSttSession:
    def __init__(self, language: str, phrases: list[str]) -> None:
        from google.cloud import speech  # imported lazily so the stub path needs no Google libs

        self._speech = speech
        self._client = speech.SpeechAsyncClient()
        self._config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=language,
                model="latest_long",
                enable_automatic_punctuation=True,
                speech_contexts=[speech.SpeechContext(phrases=phrases[:500], boost=12.0)] if phrases else [],
            ),
            interim_results=True,
        )
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._out: asyncio.Queue[SttResult | None] = asyncio.Queue()
        self._closed = False
        self._task = asyncio.create_task(self._run())

    async def push_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        if self._audio.full():  # drop oldest rather than build up latency
            self._audio.get_nowait()
        await self._audio.put(pcm)

    async def results(self) -> AsyncIterator[SttResult]:
        while (r := await self._out.get()) is not None:
            yield r

    async def close(self) -> None:
        self._closed = True
        await self._audio.put(None)
        self._task.cancel()
        await self._out.put(None)

    async def _requests(self, deadline: float):
        yield self._speech.StreamingRecognizeRequest(streaming_config=self._config)
        while time.monotonic() < deadline:
            try:
                chunk = await asyncio.wait_for(self._audio.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if chunk is None:
                return
            yield self._speech.StreamingRecognizeRequest(audio_content=chunk)

    async def _run(self) -> None:
        backoff = 1.0
        while not self._closed:
            deadline = time.monotonic() + STREAM_LIMIT_S
            try:
                stream = await self._client.streaming_recognize(requests=self._requests(deadline))
                async for resp in stream:
                    for res in resp.results:
                        if res.alternatives:
                            await self._out.put(SttResult(res.alternatives[0].transcript.strip(), res.is_final))
                backoff = 1.0
            except asyncio.CancelledError:
                return
            except Exception as e:  # network blips, stream limits: reconnect
                log.warning("STT stream ended: %s; reconnecting in %.0fs", type(e).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)


class GoogleStt:
    name = "google"

    def __init__(self, language: str, phrases: list[str]) -> None:
        self.language, self.phrases = language, phrases

    async def open(self) -> GoogleSttSession:
        return GoogleSttSession(self.language, self.phrases)


class GoogleTranslator:
    """Translation v3; glossary 'keep' terms are wrapped in translate="no" spans so they stay in English."""

    name = "google"

    def __init__(self, project: str, target: str, keep: list[str], source: str = "en") -> None:
        from google.cloud import translate_v3

        if not project:
            raise SystemExit("GOOGLE_CLOUD_PROJECT is required for TRANSLATE_ENGINE=google")
        self._client = translate_v3.TranslationServiceAsyncClient()
        self._parent = f"projects/{project}/locations/global"
        self._target, self._source = target, source
        self._keep_re = (
            re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in keep) + r")(?![\w-])") if keep else None
        )

    def _protect(self, text: str) -> str:
        t = html.escape(text, quote=False)
        if self._keep_re:
            t = self._keep_re.sub(r'<span translate="no">\1</span>', t)
        return t

    async def translate(self, text: str) -> str:
        resp = await self._client.translate_text(
            request={
                "parent": self._parent,
                "contents": [self._protect(text)],
                "mime_type": "text/html",
                "source_language_code": self._source,
                "target_language_code": self._target,
            }
        )
        out = resp.translations[0].translated_text
        out = re.sub(r"</?span[^>]*>", "", out)
        return html.unescape(out).strip()
