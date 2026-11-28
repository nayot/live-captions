import wave

from fastapi.testclient import TestClient

from app.recorder import WavRecorder
from app.server import create_app
from tests.test_pipeline import settings

PCM = b"\x01\x00" * 1600  # 100 ms of 16 kHz mono PCM16


def frames(path) -> int:
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        return w.getnframes()


def test_wav_is_valid_and_appends(tmp_path):
    p = tmp_path / "a.wav"
    r = WavRecorder(p)
    for _ in range(5):
        r.write(PCM)
    r.close()
    assert frames(p) == 8000
    r = WavRecorder(p)  # reopen = continue the same file
    r.write(PCM)
    r.close()
    assert frames(p) == 9600


def test_unclosed_file_is_still_playable(tmp_path):
    p = tmp_path / "b.wav"
    r = WavRecorder(p)
    r.write(PCM)
    r._patch()          # what the periodic header update does
    r.write(PCM)        # written after the last update, then the process "dies" (no close)
    r._f.flush()
    assert frames(p) == 1600  # header still valid; audio up to the last update plays


def _stream(client, sid, chunks, close_code):
    with client.websocket_connect(f"/ws/audio?sid={sid}") as ws:
        for _ in range(chunks):
            ws.send_bytes(PCM)
        ws.close(close_code)


def test_stop_and_reconnect_keep_one_file(tmp_path):
    rec_dir = tmp_path / "rec"
    app = create_app(settings(record_dir=str(rec_dir)))
    with TestClient(app) as client:
        _stream(client, "s1", 3, 1001)  # connection dropped
        _stream(client, "s1", 2, 1000)  # reconnected with the same id, then Stop
        _stream(client, "s2", 1, 1000)  # a new Start = a new file
    files = sorted(rec_dir.glob("*.wav"))
    assert sorted(frames(f) for f in files) == [1600, 5 * 1600]
    # Server shutdown with a session still open is checked against a real process (TestClient can't).


def test_disabled_when_dir_empty(tmp_path):
    app = create_app(settings(record_dir=""))
    with TestClient(app) as client:
        _stream(client, "x", 2, 1000)
        assert client.get("/api/status").json()["recording"]["enabled"] is False


def test_transcript_saved_per_session(tmp_path):
    rec_dir = tmp_path / "rec"
    app = create_app(settings(record_dir=str(rec_dir)))
    with TestClient(app) as client:
        assert client.get("/api/transcript.txt").status_code == 404  # nothing yet
        with client.websocket_connect("/ws/audio?sid=t1") as ws:
            for _ in range(20):
                ws.send_bytes(PCM)
            client.post("/api/inject", json={"text": "Our goal is Net Zero by 2050.", "final": True})
            client.post("/api/inject", json={"text": "สวัสดีครับ", "final": True})
            for _ in range(3):
                if client.get("/api/status").json()["recording"]["transcript_lines"] == 2:
                    break
                import time; time.sleep(0.2)
            ws.close(1000)
        txt = client.get("/api/transcript.txt").text
        srt = client.get("/api/transcript.srt").text
    assert "EN: Our goal is Net Zero by 2050." in txt and "TH: สวัสดีครับ" in txt
    assert srt.startswith("1\n00:00:0") and "\n2\n" in srt
    assert sorted(p.suffix for p in rec_dir.iterdir()) == [".srt", ".txt", ".wav"]
