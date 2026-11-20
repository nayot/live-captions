"""Settings from environment (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip()  # inline comments need a space before '#'
        os.environ.setdefault(k.strip(), v)


@dataclass
class Glossary:
    phrases: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, *paths: Path) -> "Glossary":
        g = cls()
        for p in paths:
            if p.exists():
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                g.phrases += [str(x) for x in d.get("phrases") or []]
                g.keep += [str(x) for x in d.get("keep") or []]
        g.phrases = list(dict.fromkeys(g.phrases))
        g.keep = sorted(set(g.keep), key=len, reverse=True)  # longest first for matching
        return g


@dataclass
class Settings:
    port: int
    stt_engine: str
    translate_engine: str
    google_project: str
    stt_language: str
    target_language: str
    zoom_lang: str
    zoom_max_chars: int
    zoom_cc_url: str
    transcript_dir: str
    glossary: Glossary

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(ROOT / ".env")
        e = os.environ.get
        return cls(
            port=int(e("PORT", "8765")),
            stt_engine=e("STT_ENGINE", "stub"),
            translate_engine=e("TRANSLATE_ENGINE", "stub"),
            google_project=e("GOOGLE_CLOUD_PROJECT", ""),
            stt_language=e("STT_LANGUAGE", "en-US"),
            target_language=e("TARGET_LANGUAGE", "th"),
            zoom_lang=e("ZOOM_LANG", "th-TH"),
            zoom_max_chars=int(e("ZOOM_MAX_CHARS", "120")),
            zoom_cc_url=e("ZOOM_CC_URL", ""),
            transcript_dir=e("TRANSCRIPT_DIR", "transcripts"),
            glossary=Glossary.load(ROOT / "config/glossary.yaml", ROOT / "config/glossary.local.yaml"),
        )
