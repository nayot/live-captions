"""Translation through any chat model on OpenRouter (OpenAI-compatible API).

Env: OPENROUTER_API_KEY, TRANSLATE_MODEL (an OpenRouter model id, e.g. a Claude Haiku / Gemini Flash /
GPT mini model — check https://openrouter.ai/models for current ids).
"""
from __future__ import annotations

import logging
from collections import deque

import httpx

log = logging.getLogger("live_captions.openrouter")

API = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = """You translate live speech transcripts from English into Thai for on-screen captions at an
engineering seminar (electronics manufacturing, PCB/PCBA, semiconductors, sustainability).
Rules:
- Output only the Thai translation of the CURRENT line. No quotes, notes or explanations.
- Lines are short pieces of continuous speech, often part of a longer sentence. Make the Thai continue
  naturally from the previous Thai lines, as one flowing talk: don't repeat what they already said, don't
  restart the sentence, and don't add an ending particle unless the sentence really ends here.
- Natural, concise spoken-style Thai that is easy to read quickly. Keep it about as short as the source.
- Keep these terms exactly as written, in English: {keep}.
- Keep person names, company names, model numbers and standards (e.g. IPC-A-610) in English.
- The transcript may contain recognition errors; translate the most likely intended meaning.
- If the line is only filler ("um", "okay so"), output it briefly in Thai or leave it nearly empty.{speaker}"""

SYSTEM_TH_EN = """You translate live speech transcripts from Thai into English for on-screen captions at an
engineering seminar (electronics manufacturing, PCB/PCBA, semiconductors, sustainability).
Rules:
- Output only the English translation of the CURRENT line. No quotes, notes or explanations.
- Lines are short pieces of continuous speech, often part of a longer sentence. Make the English continue
  naturally from the previous English lines, as one flowing talk: don't repeat or restart the sentence.
- Natural, concise English that is easy to read quickly. Keep it about as short as the source.
- Thai speakers often say technical terms in English; keep them as they are: {keep}.
- Write person names and company names in their usual English spelling; keep standards (e.g. IPC-A-610) as written.
- Drop Thai polite particles (ครับ, ค่ะ, นะครับ) unless they carry meaning.
- The transcript may contain recognition errors; translate the most likely intended meaning.
- If the line is only filler, output it briefly or leave it nearly empty."""

SPEAKER = {
    "male": "\n- The speaker is male: when Thai needs a polite particle or first-person pronoun, use ครับ and ผม.",
    "female": "\n- The speaker is female: when Thai needs a polite particle or first-person pronoun, use ค่ะ/คะ and ดิฉัน.",
}


class OpenRouterTranslator:
    name = "openrouter"

    def __init__(self, api_key: str, model: str, keep: list[str], context_lines: int = 4,
                 speaker: str = "", client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY is required for TRANSLATE_ENGINE=openrouter")
        if not model:
            raise SystemExit("TRANSLATE_MODEL is required for TRANSLATE_ENGINE=openrouter")
        self.model = model
        self.name = f"openrouter:{model}"
        self._system = SYSTEM.format(keep=", ".join(keep) if keep else "(none)",
                                     speaker=SPEAKER.get(speaker.strip().lower(), ""))
        self._system_th = SYSTEM_TH_EN.format(keep=", ".join(keep) if keep else "(none)")
        self._ctx: deque[tuple[str, str]] = deque(maxlen=context_lines)  # (said, shown)
        self._client = client or httpx.AsyncClient(timeout=8.0)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Title": "live-captions",
        }

    async def translate(self, text: str, final: bool = True, source: str = "en") -> str:
        context = "\n".join(f"{said}\n  -> {shown}" for said, shown in self._ctx)
        user = (f"Previous lines and how they were shown (context only, do not translate again):\n{context}\n\n"
                if context else "") + f"CURRENT line to translate:\n{text}"
        r = await self._client.post(API, headers=self._headers, json={
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 400,
            "messages": [{"role": "system", "content": self._system_th if source == "th" else self._system},
                         {"role": "user", "content": user}],
        })
        if r.status_code >= 300:
            raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:160]}")
        out = (r.json()["choices"][0]["message"]["content"] or "").strip().strip('"“”')
        if final:  # interim drafts would duplicate context
            self._ctx.append((text, out))
        return out
