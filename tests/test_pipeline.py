import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.config import Glossary, Settings
from app.server import create_app
from app.zoom import ZoomPoster, chunk, mask

FAKE_URL = "https://wmcc.zoom.us/closedcaption?id=123&ns=abc&expire=999&signature=SECRET"


def settings(**kw) -> Settings:
    base = dict(port=0, stt_engine="stub", translate_engine="stub", google_project="", stt_language="en-US",
                target_language="th", zoom_lang="th-TH", zoom_max_chars=40, zoom_cc_url="", transcript_dir="",
                glossary=Glossary())
    base.update(kw)
    return Settings(**base)


def recording_poster(sent: list) -> ZoomPoster:
    def handler(req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(req.url)).query)
        sent.append({"seq": int(q["seq"][0]), "lang": q["lang"][0], "body": req.content.decode("utf-8")})
        return httpx.Response(200, text="2026-11-20T10:00:00.000")
    return ZoomPoster("th-TH", 40, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_mask_hides_secrets():
    m = mask(FAKE_URL)
    assert "SECRET" not in m and "123" not in m


def test_chunk_respects_limit_and_keeps_text():
    text = "อุตสาหกรรมอิเล็กทรอนิกส์และเซมิคอนดักเตอร์เป็นอุตสาหกรรมเป้าหมาย of Thailand and the EEC region"
    parts = chunk(text, 30)
    assert all(len(p) <= 30 for p in parts)
    assert "".join(parts).replace(" ", "") == text.replace(" ", "")


def test_inject_reaches_display_and_zoom_in_order():
    sent: list = []
    app = create_app(settings(), zoom=recording_poster(sent))
    with TestClient(app) as c:
        assert c.post("/api/zoom", json={"url": FAKE_URL}).json()["ok"]
        with c.websocket_connect("/ws/events") as ws:
            for line in ["Hello everyone", "Welcome students", "Thank you"]:
                c.post("/api/inject", json={"text": line})
            finals = []
            while len(finals) < 3:
                d = json.loads(ws.receive_text())
                if d["type"] == "final":
                    finals.append(d)
        assert [f["en"] for f in finals] == ["Hello everyone", "Welcome students", "Thank you"]
        assert finals[0]["th"].startswith("[TH] สวัสดี")
        for _ in range(50):
            if len(sent) >= 3:
                break
            asyncio.run(asyncio.sleep(0.02))
        assert [s["seq"] for s in sent] == [1, 2, 3]
        assert all(s["lang"] == "th-TH" for s in sent)
        assert "สวัสดี" in sent[0]["body"]
        st = c.get("/api/status").json()
        assert "SECRET" not in json.dumps(st)


def test_rejects_non_https_zoom_url():
    app = create_app(settings())
    with TestClient(app) as c:
        assert not c.post("/api/zoom", json={"url": "hello"}).json()["ok"]


def test_audio_socket_accepts_pcm():
    app = create_app(settings())
    with TestClient(app) as c:
        with c.websocket_connect("/ws/audio") as ws:
            ws.send_bytes(b"\x00\x00" * 1600)
        assert c.get("/api/status").json()["audio_bytes"] == 3200
