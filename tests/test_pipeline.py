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


async def test_openrouter_translator_prompt_and_context():
    from app.engines.openrouter import OpenRouterTranslator

    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append((req.headers["authorization"], body))
        return httpx.Response(200, json={"choices": [{"message": {"content": "สวัสดีครับ"}}]})

    tr = OpenRouterTranslator("sk-test", "some/model", ["PCBA", "IPC-A-610"],
                              client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await tr.translate("Hello", final=True) == "สวัสดีครับ"
    await tr.translate("draft words", final=False)
    await tr.translate("Next line")
    auth, body = calls[-1]
    assert auth == "Bearer sk-test" and body["model"] == "some/model"
    assert "PCBA" in body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    assert "Hello" in user and "draft words" not in user and user.endswith("Next line")


async def test_assemblyai_turn_handling():
    from app.engines.assemblyai import AssemblyAISession

    s = AssemblyAISession.__new__(AssemblyAISession)  # no network: test the message handler only
    s._out, s._pending, s._finalised = asyncio.Queue(), {}, set()
    await s._handle({"type": "Turn", "turn_order": 0, "transcript": "hello every", "end_of_turn": False})
    await s._handle({"type": "Turn", "turn_order": 0, "transcript": "hello everyone", "end_of_turn": True,
                     "turn_is_formatted": False})
    await s._handle({"type": "Turn", "turn_order": 0, "transcript": "Hello, everyone.", "end_of_turn": True,
                     "turn_is_formatted": True})
    got = [s._out.get_nowait() for _ in range(3)]
    assert [g.final for g in got] == [False, False, True] and got[-1].text == "Hello, everyone."
    await asyncio.sleep(1.6)
    assert s._out.empty()  # fallback cancelled, no duplicate final


def test_lan_clients_get_display_only():
    from app.server import create_app as mk
    app = mk(Settings.from_env())
    with TestClient(app, client=("10.0.0.9", 5000)) as c:
        assert c.get("/display").status_code == 200
        assert c.get("/").status_code == 403
        assert c.get("/api/status").status_code == 403
        assert c.post("/api/zoom", json={"url": "https://x"}).status_code == 403
    with TestClient(app) as c:
        assert c.get("/").status_code == 200


def test_detect_lang():
    from app.engines.base import detect_lang
    assert detect_lang("Hello everyone") == "en"
    assert detect_lang("สวัสดีครับ วันนี้จะพูดเรื่อง IPC-A-610") == "th"   # English terms inside Thai stay Thai
    assert detect_lang("We follow มาตรฐาน IPC Class 3 for medical devices") == "en"


def test_thai_speech_is_translated_to_english():
    app = create_app(settings())
    with TestClient(app) as c:
        with c.websocket_connect("/ws/events") as ws:
            c.post("/api/inject", json={"text": "สวัสดีครับ"})
            c.post("/api/inject", json={"text": "Hello everyone"})
            finals = []
            while len(finals) < 2:
                d = json.loads(ws.receive_text())
                if d["type"] == "final":
                    finals.append(d)
    th_line, en_line = finals
    assert th_line["lang"] == "th" and th_line["th"] == "สวัสดีครับ" and th_line["en"] == "[EN] สวัสดีครับ"
    assert en_line["lang"] == "en" and en_line["en"] == "Hello everyone" and en_line["th"].startswith("[TH]")


def test_soniox_tokens_become_lines():
    from app.engines.soniox import SonioxSession

    async def run():
        s = SonioxSession.__new__(SonioxSession)  # no network: feed messages straight to the parser
        s._out, s._final, s._last_interim = asyncio.Queue(), "", ""
        await s.handle({"tokens": [{"text": "สวัส", "is_final": True}, {"text": "ดีครับ", "is_final": False}]})
        await s.handle({"tokens": [{"text": "ดี", "is_final": True}, {"text": "ครับ", "is_final": True},
                                   {"text": "<end>", "is_final": True}, {"text": " Hello", "is_final": False}]})
        await s.handle({"tokens": [], "error_code": 503, "error_type": "service_unavailable"})
        out = []
        while not s._out.empty():
            r = s._out.get_nowait()
            out.append((r.text, r.final))
        return out

    assert asyncio.run(run()) == [("สวัสดีครับ", False), ("สวัสดีครับ", True), ("Hello", False)]
