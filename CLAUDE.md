# CLAUDE.md — live-captions

Live English → Thai captions: room audio → speech-to-text → translation → Zoom closed captions
(third-party caption API) + a second-screen display page. See `PLAN.md` for scope, phases and open decisions.

## Rules for this repo (public)

- **This repo is public.** Never commit secrets, Zoom caption tokens/URLs, meeting IDs or passcodes,
  cloud credentials, email addresses, or names of event staff. Config that holds any of these goes in
  `.env` (git-ignored); keep `.env.example` with placeholders only.
- The Zoom caption URL/token is passed at runtime (control page or `ZOOM_CC_URL`) and must never be
  logged or written to disk. Mask it in any log line (`…token=****`).
- Keep it cross-platform: Python (run with `uv`) + Chrome. No native audio dependencies; audio is
  captured in the browser and streamed to the local server.
- STT and translation sit behind small interfaces (`engines/`), with a stub engine so the whole path
  can be tested without cloud billing.
- Thai text: UTF-8 everywhere; display font Sarabun (Google Fonts) with a system Thai fallback.

## Layout

```
app/            FastAPI server: websocket audio in, broadcaster, Zoom poster
app/engines/    base.py (interfaces), stub.py, google.py
app/static/     control.html (/), display.html (/display); bar overlay later
config/         glossary.yaml, settings
scripts/        zoom_probe.py (one-off caption API test)
```

## Run

```
cp .env.example .env            # stub engines by default (no cloud needed)
uv sync                         # add --extra google for the Google engines
uv run python -m app            # http://localhost:8765  (control)  /display (second screen)
uv run pytest -q                # tests (stub engines + mocked Zoom endpoint)
uv run python scripts/zoom_probe.py   # Phase 1: post test lines to a live meeting's caption URL
```

## Status

- 20.11.2026 — repo created; plan written.
- 20.11.2026 — Phase 2 done: server, control page (mic capture → 16 kHz PCM over websocket), display page,
  Zoom poster (ordered, increasing seq, token masked), stub engines, tests passing. Google engines written
  (streaming STT v1 `latest_long` + phrase hints; Translation v3 with translate="no" for glossary terms)
  but **untested** — waiting for a cloud project. Zoom probe script ready but **not yet run against a real
  meeting** (Thai rendering, seq start, length limit unconfirmed). Overlay (Phase 5) not started.
