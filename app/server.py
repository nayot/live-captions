"""FastAPI app: audio websocket in, events websocket out, small JSON control API."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .engines.stub import StubStt, StubTranslator
from .engines.base import SttResult
from .pipeline import Pipeline
from .recorder import Recordings
from .zoom import ZoomPoster

log = logging.getLogger("live_captions")
STATIC = Path(__file__).parent / "static"


class Inject(BaseModel):
    text: str
    final: bool = True


class ZoomUrl(BaseModel):
    url: str
    reset_seq: bool = False


def build_engines(s: Settings):
    if s.stt_engine == "google":
        from .engines.google import GoogleStt

        stt = GoogleStt(s.stt_language, s.glossary.phrases)
    elif s.stt_engine == "assemblyai":
        from .engines.assemblyai import AssemblyAIStt

        stt = AssemblyAIStt(s.assemblyai_api_key, s.glossary.phrases, s.stt_model)
    elif s.stt_engine == "soniox":
        from .engines.soniox import SonioxStt

        stt = SonioxStt(s.soniox_api_key, s.glossary.phrases, s.soniox_model, s.max_line_chars)
    else:
        stt = StubStt()
    if s.translate_engine == "google":
        from .engines.google import GoogleTranslator

        tr = GoogleTranslator(s.google_project, s.target_language, s.glossary.keep)
    elif s.translate_engine == "openrouter":
        from .engines.openrouter import OpenRouterTranslator

        tr = OpenRouterTranslator(s.openrouter_api_key, s.translate_model, s.glossary.keep,
                                  speaker=s.speaker_gender)
    else:
        tr = StubTranslator()
    return stt, tr


LAN_PATHS = ("/display", "/ws/events", "/static/")
LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}


class LanDisplayOnly:
    """Other machines (HOST=0.0.0.0) get the display page only; the control page, audio and the
    Zoom API stay on this machine, so nobody on the network can read or change the caption URL."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = (scope.get("client") or ("127.0.0.1",))[0]
            path = scope["path"]
            if client not in LOCAL_CLIENTS and not (path == "/display" or path.startswith(LAN_PATHS)):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body",
                            "body": b"Only /display is available from other machines."})
                return
        await self.app(scope, receive, send)


def lan_ip() -> str:
    """This machine's address on the local network (re-read each call: the network can change)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        try:
            sk.connect(("10.255.255.255", 1))  # no packet sent; picks the outgoing interface
            return sk.getsockname()[0]
        except OSError:
            return ""


def create_app(settings: Settings | None = None, zoom: ZoomPoster | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    stt, translator = build_engines(s)
    zoom = zoom or ZoomPoster(s.zoom_lang, s.zoom_max_chars)
    if s.zoom_cc_url:
        zoom.set_url(s.zoom_cc_url)
    pipe = Pipeline(translator, zoom, s.transcript_dir)
    state = {"audio_clients": 0, "audio_bytes": 0}
    recordings = Recordings(s.record_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipe.start()
        try:
            yield
        finally:
            recordings.close_all()  # server shutdown: finalise any recording still open
            await zoom.stop()

    app = FastAPI(title="live-captions", lifespan=lifespan)
    app.add_middleware(LanDisplayOnly)
    app.state.pipeline, app.state.zoom, app.state.settings = pipe, zoom, s

    @app.get("/")
    async def control():
        return FileResponse(STATIC / "control.html")

    @app.get("/display")
    async def display():
        return FileResponse(STATIC / "display.html")

    @app.get("/static/{name}")
    async def static(name: str):
        p = (STATIC / name).resolve()
        if p.parent != STATIC.resolve() or not p.exists():
            return {"error": "not found"}
        return FileResponse(p)

    @app.websocket("/ws/events")
    async def events(ws: WebSocket):
        await ws.accept()
        await pipe.bus.add(ws)
        try:
            while True:
                await ws.receive_text()  # keepalive pings from the page
        except WebSocketDisconnect:
            pipe.bus.remove(ws)

    @app.websocket("/ws/audio")
    async def audio(ws: WebSocket):
        await ws.accept()
        session = await stt.open()
        state["audio_clients"] += 1
        sid = ws.query_params.get("sid", "")
        rec = recordings.attach(sid)
        final = True  # Stop pressed or server going down, unless we see a dropped connection

        async def pump():
            async for r in session.results():
                await pipe.on_stt(r)

        task = asyncio.create_task(pump())
        try:
            while True:
                pcm = await ws.receive_bytes()
                state["audio_bytes"] += len(pcm)
                if rec:
                    rec.write(pcm)
                await session.push_audio(pcm)
        except WebSocketDisconnect as e:
            final = e.code == 1000  # the control page closes with 1000 on Stop; drops are 1001/1006
        finally:
            recordings.detach(sid, final)
            state["audio_clients"] -= 1
            await session.close()
            task.cancel()

    @app.post("/api/inject")
    async def inject(body: Inject):
        """Typed English goes through the same path as speech (for tests and as a manual fallback)."""
        await pipe.on_stt(SttResult(body.text.strip(), body.final))
        return {"ok": True}

    @app.post("/api/zoom")
    async def set_zoom(body: ZoomUrl):
        if not body.url.strip().startswith("https://"):
            return {"ok": False, "error": "Expected the caption API URL copied from Zoom (https://...)"}
        zoom.set_url(body.url, body.reset_seq)
        return {"ok": True, "zoom": zoom.status()}

    @app.delete("/api/zoom")
    async def clear_zoom():
        zoom.clear()
        return {"ok": True}

    @app.post("/api/zoom/test")
    async def zoom_test():
        zoom.enqueue("ทดสอบคำบรรยาย (caption test)")
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {
            "stt": stt.name,
            "translate": translator.name,
            "audio_clients": state["audio_clients"],
            "audio_bytes": state["audio_bytes"],
            "display_clients": len(pipe.bus.clients),
            "finals": pipe.finals,
            "translate_errors": pipe.errors,
            "zoom": zoom.status(),
            "recording": recordings.status(),
            "lan_base": (f"http://{ip}:{s.port}" if s.host not in ("127.0.0.1", "localhost", "::1")
                         and (ip := lan_ip()) else ""),
        }

    return app
