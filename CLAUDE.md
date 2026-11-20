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

## Layout (planned)

```
app/            FastAPI server: websocket audio in, broadcaster, Zoom poster
app/engines/    stt_*.py, translate_*.py (stub, google)
app/static/     control page, /display, /bar
config/         glossary.yaml, settings
scripts/        zoom_probe.py (one-off caption API test)
```

## Run (once built)

```
uv sync
uv run python -m app            # serves http://localhost:8765
# control page: http://localhost:8765/        display: http://localhost:8765/display
```

## Status

- 20.11.2026 — repo created; plan written. Next: Phase 1 Zoom probe, then the stub pipeline.
