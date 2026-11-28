# live-captions

Live English ↔ Thai captions for hybrid events: room audio is transcribed and translated, then shown on
screens in the room and as Zoom closed captions (via Zoom's third-party caption API). The language of each
line is detected automatically: English is shown in Thai, Thai in English.

See [PLAN.md](PLAN.md) for background.

## Quick start

```
cp .env.example .env
uv sync
uv run python -m app
```

Open http://localhost:8765 (control page: pick the audio input, start, optionally paste the Zoom caption
URL) and http://localhost:8765/display on the caption screen. With the default stub engines you can type
lines to test the whole path without any cloud account.

For live speech, set in `.env`:

| Setting | Engine | Notes |
|---|---|---|
| `STT_ENGINE=soniox` + `SONIOX_API_KEY` | Soniox speech-to-text | English and Thai in one stream (recommended) |
| `STT_ENGINE=assemblyai` + `ASSEMBLYAI_API_KEY` | AssemblyAI | English only |
| `TRANSLATE_ENGINE=openrouter` + `OPENROUTER_API_KEY`, `TRANSLATE_MODEL` | any chat model on OpenRouter | e.g. a Claude Haiku model |
| `STT_ENGINE=google`, `TRANSLATE_ENGINE=google` + `GOOGLE_CLOUD_PROJECT` | Google Cloud | needs `uv sync --extra google`; untested |

Other useful settings: `SPEAKER_GENDER` (ครับ/ผม or ค่ะ/ดิฉัน in Thai), `MAX_LINE_CHARS` (caption line
length), `HOST=0.0.0.0` (let other machines on the network open the display). Event terms that must stay in
English go in `config/glossary.yaml`; private names in `config/glossary.local.yaml` (git-ignored).

## Caption screen

The control page builds the display link with your choices; the same link works on other machines on the
network (they get the display only). Options: text size, number of lines, alignment, background
(black/green/blue/custom, for chroma key), text colour, header on/off, show the original or the translation
only, and the changing draft while speaking (off by default: lines appear once, finished).

## Recording

Each **Start listening** records the room audio to `recordings/recording-YYYYMMDD-HHMMSS.wav` until **Stop**
or until the server shuts down; a short network drop continues the same file. The file stays playable even if
the server is killed. About 115 MB per hour (16 kHz mono). Set `RECORD_DIR=` (empty) in `.env` to turn it off.
The English/Thai text log goes to `transcripts/`. Both folders are git-ignored.

## Windows

1. Install [Google Chrome](https://www.google.com/chrome/) and [Git](https://git-scm.com/download/win)
   (or download this repo as a ZIP from GitHub).
2. Install [uv](https://docs.astral.sh/uv/) in PowerShell; it installs Python for you:
   ```
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   Then open a new PowerShell window so `uv` is on the PATH.
3. Get the code and install the dependencies:
   ```
   git clone https://github.com/nayot/live-captions.git
   cd live-captions
   uv sync
   ```
4. Create `.env`: `copy .env.example .env`, then edit it in Notepad (engines and API keys). If you
   already have a working `.env` on another machine, copy that file over instead, by USB or a password
   manager — not by email or chat. Do the same for an event glossary in `config\glossary.local.yaml`.
5. Start the app with `uv run python -m app` and open http://localhost:8765 in Chrome. Allow the
   microphone when Chrome asks.
6. Other screens on the network (`HOST=0.0.0.0` in `.env`): set the Windows network to **Private**
   (Settings → Network & internet → your connection) and click **Allow** when Windows Firewall asks
   about Python. The control page shows the link to open on the other screens.

## Licence

MIT
