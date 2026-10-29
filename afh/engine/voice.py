"""Voice input: speech recorded by the mic button becomes text in the composer.

The audio goes to the `/audio/transcriptions` endpoint (Whisper-style) of a provider you have
already set up: Groq or OpenAI by default, or any OpenAI-compatible provider picked in
Settings → Agent → Voice (a local Whisper server works too).
"""
from __future__ import annotations

import os

import httpx

from . import config as provcfg

DEFAULT_MODELS = {"groq": "whisper-large-v3-turbo", "openai": "gpt-4o-mini-transcribe"}
EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}


def pick(settings: dict) -> tuple[str, str, str]:
    """(base url, api key, model) for transcription, or a ValueError saying what to set up."""
    voice = settings.get("voice") or {}
    providers = provcfg.load()["providers"]
    wanted = voice.get("provider") or ""
    order = [wanted] if wanted else ["groq", "openai"]
    for pid in order:
        p = providers.get(pid) or {}
        key = p.get("api_key") or ""
        if not key and pid in ("groq", "openai"):
            key = os.environ.get(f"{pid.upper()}_API_KEY", "")
        base = p.get("base_url") or {"groq": "https://api.groq.com/openai/v1", "openai": "https://api.openai.com/v1"}.get(pid, "")
        if base and (key or wanted):  # a chosen provider may be a local server without a key
            return base.rstrip("/"), key, voice.get("model") or DEFAULT_MODELS.get(pid, "whisper-1")
    if wanted:
        raise ValueError(f"The voice provider {wanted!r} isn't set up any more — pick another in Settings → Agent → Voice")
    raise ValueError("Voice input needs a Groq or OpenAI key: add one in Settings → Models, or pick a provider in Settings → Agent → Voice")


async def transcribe(audio: bytes, mime: str, settings: dict) -> str:
    base, key, model = pick(settings)
    mime = mime.split(";")[0].strip() or "audio/webm"
    form = {"model": model, "response_format": "json"}
    language = ((settings.get("voice") or {}).get("language") or "").strip()
    if language:
        form["language"] = language
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{base}/audio/transcriptions", headers=headers, data=form,
                              files={"file": (f"speech.{EXTENSIONS.get(mime, 'webm')}", audio, mime)})
    if r.status_code >= 400:
        try:
            err = r.json().get("error")
            msg = err.get("message") if isinstance(err, dict) else err
        except ValueError:
            msg = r.text[:200]
        raise ValueError(f"Transcription failed ({r.status_code}): {msg or r.reason_phrase}")
    return str(r.json().get("text") or "").strip()
