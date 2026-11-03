"""Proof-of-work solver for OpenAI's sentinel challenges (the ChatGPT web backend).

A faithful port of the reference ``src/chatgpt/pow.ts``: a sha3-512 search over a
browser-fingerprint config array. The sentinel only validates that
``sha3_512(seed + base)`` has the required hex prefix, where ``base`` is the base64 of
the array we send — so the search always succeeds for the easy difficulties the backend
uses. The fingerprint is kept realistic (real UA, build id, script names) to avoid
tripping the anti-bot heuristics, exactly as the web client does.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

CORES = (8, 12, 16, 24)
SCREENS = (3000, 4000, 6000)
# The exact magic string the browser fingerprint uses (note the U+2212 minus sign).
WEBKIT_STR = "webkitGetUserMedia−function webkitGetUserMedia() { [native code] }"
FALLBACK_BUILD_ID = "prod-a696433ddfe0489db6696cae8c5778c2128f26e8"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_SHANGHAI = timezone(timedelta(hours=8))
_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MO = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class PoW:
    """Holds the per-process fingerprint (session uuid, cores, start time) and solves challenges.

    One instance per provider; ``user_agent`` and ``build_id`` are set from the signed-in
    session so the proof matches the request headers.
    """

    def __init__(self, user_agent: str = DEFAULT_UA, build_id: str = FALLBACK_BUILD_ID, scripts: list[str] | None = None):
        self.user_agent = user_agent or DEFAULT_UA
        self.build_id = build_id or FALLBACK_BUILD_ID
        self.scripts = scripts or []
        self.core = random.choice(CORES)
        self.screen = random.choice(SCREENS)
        self.sid = str(uuid.uuid4())
        self.start = time.time()
        self.start_ms = self.start * 1000 + (int(self.start * 1000) % 997) / 1000
        self._req_proof = ""

    def _time_string(self) -> str:
        now = datetime.now(_SHANGHAI)
        return f"{_WD[now.weekday()]} {_MO[now.month - 1]} {now.day} {now:%H:%M:%S} GMT+0800 (中国标准时间)"

    def _config(self) -> list:
        elapsed = (time.time() - self.start) * 1000
        script = random.choice(self.scripts) if self.scripts else None
        return [
            self.screen, self._time_string(), 4294705152, 0, self.user_agent, script, self.build_id,
            "en-US", "en-US", 0, WEBKIT_STR, "location", "ontransitionend", elapsed + random.random(),
            self.sid, "", self.core, self.start_ms,
        ]

    def answer(self, seed: str, difficulty: str) -> str:
        """Brute-force the base64 answer whose ``sha3_512(seed + base)`` meets the difficulty prefix."""
        cfg = self._config()
        dl = len(difficulty)
        t0 = time.time()
        for i in range(500_000):
            cfg[3] = i
            cfg[9] = round((time.time() - t0) * 1000)
            base = base64.b64encode(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()).decode()
            if hashlib.sha3_512((seed + base).encode()).hexdigest()[:dl] <= difficulty:
                return base
        return "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.b64encode(f'"{seed}"'.encode()).decode()

    def requirements_proof(self) -> str:
        """The ``p`` value for ``/sentinel/chat-requirements`` (difficulty "0" — solves at once). Cached."""
        if not self._req_proof:
            self._req_proof = "gAAAAAC" + self.answer(str(random.random()), "0")
        return self._req_proof

    def conversation_proof(self, seed: str, difficulty: str) -> str:
        """The per-conversation ``openai-sentinel-proof-token`` header value."""
        return "gAAAAAB" + self.answer(seed, difficulty)
