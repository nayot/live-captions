# live-captions

Live English → Thai captions for hybrid events: room audio is transcribed and translated, then shown as
Zoom closed captions (via Zoom's third-party caption API) and on a second screen in the room.

Work in progress — see [PLAN.md](PLAN.md).

## Quick start

```
cp .env.example .env
uv sync
uv run python -m app
```

Open http://localhost:8765 (control: pick the audio input, paste the Zoom caption URL) and
http://localhost:8765/display on the second screen. With the default stub engines you can type lines to
test the whole path; set `STT_ENGINE=google` and `TRANSLATE_ENGINE=google` (plus `GOOGLE_CLOUD_PROJECT`,
and `uv sync --extra google`) for live speech.

## Licence

MIT
