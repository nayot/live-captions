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
app/engines/    base.py (interfaces), stub.py, assemblyai.py (STT), openrouter.py (translation), google.py (both)
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
- 20.11.2026 — Cheaper engines added and chosen as default for the event: **AssemblyAI** Universal-Streaming
  (STT, keyterms from glossary) + **OpenRouter** chat model for translation (model id in
  `TRANSLATE_MODEL`; prompt keeps glossary terms in English, 2 previous lines as context). Unit-tested with
  mocks only; **not yet run against the live services** (waiting for keys in `.env`).
- 20.11 (evening) — Both keys in `.env` and tested live (speech clip → Thai, no Zoom needed). Pinned
  `STT_MODEL=assemblyai-stt-3-7-realtime-agent` (USD 0.45/h; AssemblyAI's default when unset, so pinned to stop
  silent changes); translation `anthropic/claude-haiku-5.5`. Card added to AssemblyAI (lifts 5 new sessions/min
  limit). Reconnect is immediate, backs off only on repeated failures. Draft Thai updates ~1 s while speaking
  (display + control page); Zoom gets finished lines only. Display options: size, lines, align, previous line,
  background (black/green/blue/custom), header on/off. Event glossary (speakers, companies) in
  `config/glossary.local.yaml` — git-ignored, copy it to the captions laptop.
- 23.11.2026 — `HOST=0.0.0.0` in `.env` lets other machines on the network open `http://<ip>:8765/display`.
  Other machines get the display only (control page, audio and Zoom API return 403 to non-local clients).
- 24.11.2026 — Control page shows the display link for other machines with the chosen options (incl. `fg` text
  colour). `SPEAKER_GENDER=male|female` sets ครับ/ผม or ค่ะ/ดิฉัน in the translation. GEA seminar terms added
  (standards in `glossary.yaml`; names/companies in the git-ignored `glossary.local.yaml` on the MacBook).
  STT keyterms are capped at 100 (base list first) — currently 92.
