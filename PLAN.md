# Plan — live-captions

Live English → Thai captions for a hybrid seminar: speech from the room mixer is transcribed, translated,
and shown (1) as Zoom closed captions through Zoom's third-party caption API and (2) on a second screen
in the room. A subtitle overlay on the presentation laptop comes later.

First target: a one-day hybrid seminar on **Tue 24.11.2026**, with a full tech check on **Mon 23.11.2026, 15:00**.

## Scope and order

"API version first" is read as: **Zoom caption-API output first**, laptop overlay second.
(If it meant "cloud speech APIs rather than local models", the plan is the same — v1 uses cloud APIs.)

| Phase | Deliverable | Target |
|---|---|---|
| 0 | Repo, plan, CLAUDE.md | 20.11 |
| 1 | **Zoom probe**: post one Thai line to a live meeting's caption token; confirm Thai renders, `seq` rules, length limit, token re-copy behaviour | 20–21.11 |
| 2 | **Pipeline with stub engines**: typed text / audio file → (stub) STT → (stub) translate → Zoom poster + display page. Runs end to end with no cloud account | 21.11 |
| 3 | **Cloud engines**: streaming speech-to-text (en-US) + EN→TH translation, glossary for event terms | 21–22.11 (needs credentials) |
| 4 | **Display page**: second screen, EN line + TH line, large type, BUU Grey/Gold + Engineering dark red | 22.11 |
| 5 | **Overlay**: Chrome Document Picture-in-Picture subtitle bar (always on top); Electron transparent overlay only if PiP fails over PowerPoint | after 24.11 unless time allows |

## Architecture (v1)

```
mixer AUX/USB ──► captions laptop: Chrome control page (getUserMedia, 16 kHz PCM)
                        │ WebSocket (localhost)
                        ▼
                 local Python server (FastAPI)
                  ├─ STT engine   (interface; stub | Google Cloud streaming)
                  ├─ translator   (interface; stub | Google Cloud Translation, glossary)
                  ├─ Zoom poster  ─► POST {caption_url}&seq=N&lang=th-TH  (text/plain)
                  └─ broadcaster  ─► /display (second screen), /bar (overlay, later)
```

- **Runs locally on the captions laptop.** Browser mic capture needs HTTPS or `localhost`; a local server
  gives `localhost` for free and avoids depending on campus network access to an internal server.
  Needs Python (via `uv`) and Chrome on that laptop. OS of the venue laptops is still unknown, so keep it
  cross-platform (pure Python + browser, no native audio libraries).
- **Latency strategy.** Show interim English on the display at once; translate on final STT results
  (and every ~2 s inside a long utterance, so Thai never lags a whole paragraph). Send only finalised
  Thai lines to Zoom, ≤ ~2 short lines per post, `seq` strictly increasing.
- **Glossary / phrase hints**: GEA, IPC, IPC-A-610, PCB, PCBA, EEC, EEC HDC, UNEP, Carl Zeiss, Fabrinet,
  Star Microelectronics, Net Zero, speaker names. Kept in `config/glossary.yaml`.
- **Zoom token**: pasted on the control page or passed by env var `ZOOM_CC_URL`; held in memory only,
  never written to disk or logs.
- **Transcript log**: optional local file of EN/TH pairs (git-ignored) for post-event review.

## Open decisions

1. **Cloud project and billing** for speech-to-text + translation (blocking Phase 3; needed by **Sat 21.11**
   to make Monday's test). Options: an existing Google Cloud project with billing, or a new one.
   Estimated cost for one 8-hour day: ~USD 10–15. A Gemini API key is a possible alternative engine.
2. **Captions laptop**: which machine and OS; how it gets mixer audio (USB interface or 3.5 mm line-in).
3. **Zoom caption language**: one stream only (Thai). English speakers online get no captions from us.

## Monday 23.11 tech check — go / no-go

Pass if all hold for a 10-minute recorded talk (accented English, technical terms) played through the mixer:
- Thai captions appear in Zoom on a second device, lag ≤ 5 s, no stalls > 15 s.
- Second screen shows EN + TH legibly from the back row.
- Glossary terms (PCBA, IPC-A-610, GEA, EEC) come out right ≥ 80 % of the time.
- Survives a network blip (hotspot switch) by reconnecting on its own.

If it fails: run the second screen only (no Zoom captions), or drop live translation for the day.

## Out of scope for v1

Spoken (audio) interpretation; multiple caption languages; per-viewer language choice; speaker diarisation.
