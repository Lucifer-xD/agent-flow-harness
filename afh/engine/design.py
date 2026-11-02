"""Design first: the ``design`` tool shows the user design options (A, B, C…) for what they asked to build,
as mockups of its main screens in the right device frames (phone, tablet, desktop, app window…), and
waits for them to pick one, mix them, or ask for new ones.

The model writes each screen as one self-contained HTML file under ``<project>/.afh/designs/<name>/``,
then calls ``design``. The card goes through the same pending-request flow as questions, so it waits in
every approval mode, survives a reload, and Stop cancels it. The chosen direction becomes the project's
design system in ``<project>/.afh/design.md``, which goes into the system prompt of every later thread.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .types import PermissionDenied, ToolContext, ToolResult, ToolSpec

MAX_OPTIONS = 4
MAX_SCREENS = 8
MAX_FILE = 3 * 1024 * 1024
DESIGN_MD = Path(".afh") / "design.md"
LETTERS = "ABCD"
LEAD_LETTER = re.compile(r"^(?:option\s+)?[A-D]\s*[—–:.)\-]\s*", re.I)  # "A — Calm", "Option B: Bold" (the card shows the letter)

# The frame each screen is shown in: CSS size of the viewport. Platform picks the phone/tablet/watch flavour.
DEVICES: dict[str, dict[str, tuple[int, int]]] = {
    "phone": {"ios": (393, 852), "android": (412, 915), "default": (390, 844)},
    "tablet": {"ios": (820, 1180), "android": (800, 1280), "default": (820, 1180)},
    "desktop": {"default": (1440, 900)},
    "laptop": {"default": (1280, 800)},
    "window": {"default": (1200, 780)},
    "watch": {"ios": (205, 251), "android": (227, 227), "default": (205, 251)},
    "tv": {"default": (1920, 1080)},
}
PLATFORMS = ("web", "android", "ios", "windows", "macos", "linux", "cross-platform", "other")


def device_size(device: str, platform: str) -> tuple[int, int]:
    sizes = DEVICES.get(device) or DEVICES["desktop"]
    key = "ios" if platform in ("ios", "macos") else "android" if platform == "android" else "default"
    return sizes.get(key) or sizes["default"]


def clean(raw: dict, directory: str) -> dict:
    """The validated request: {title, platform, options: [{letter, name, summary, screens: [{name, device, file, path, width, height}]}]}."""
    if not isinstance(raw, dict):
        raise ValueError("expected an object")
    platform = str(raw.get("platform") or "web").strip().lower()
    if platform not in PLATFORMS:
        platform = "other"
    options = raw.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
        raise ValueError(f"give 2-{MAX_OPTIONS} options")
    root = Path(directory).resolve()
    out = []
    for i, o in enumerate(options):
        if not isinstance(o, dict):
            raise ValueError(f"option {i + 1} is not an object")
        name = LEAD_LETTER.sub("", " ".join(str(o.get("name") or "").split()))[:60] or f"Option {LETTERS[i]}"
        screens = o.get("screens")
        if not isinstance(screens, list) or not 1 <= len(screens) <= MAX_SCREENS:
            raise ValueError(f"option {LETTERS[i]} needs 1-{MAX_SCREENS} screens")
        shown = []
        for s in screens:
            if not isinstance(s, dict) or not str(s.get("file") or "").strip():
                raise ValueError(f"every screen of option {LETTERS[i]} needs a file")
            path = (root / str(s["file"]).strip()).resolve()
            if root not in path.parents and path != root:
                raise ValueError(f"{s['file']} is outside the project")
            if path.suffix.lower() not in (".html", ".htm") or not path.is_file():
                raise ValueError(f"{s['file']} is not an HTML file in the project (write it first)")
            if path.stat().st_size > MAX_FILE:
                raise ValueError(f"{s['file']} is over 3 MB; keep mockups self-contained and light")
            device = str(s.get("device") or ("phone" if platform in ("android", "ios") else "window" if platform in ("windows", "macos", "linux") else "desktop")).lower()
            if device not in DEVICES:
                device = "desktop"
            w, h = device_size(device, platform)
            shown.append({"name": " ".join(str(s.get("name") or path.stem).split())[:40], "device": device, "file": str(s["file"]).strip(),
                          "path": str(path), "width": w, "height": h})
        out.append({"letter": LETTERS[i], "name": name, "summary": " ".join(str(o.get("summary") or "").split())[:400], "screens": shown})
    return {"title": " ".join(str(raw.get("title") or "Design options").split())[:80], "platform": platform, "options": out}


def report(req: dict, answer: dict) -> str:
    letters = {o["letter"]: o for o in req["options"]}
    choice = str(answer.get("choice") or "").upper()[:1]
    notes = " ".join(str(answer.get("notes") or "").split())[:2000]
    if choice not in letters:
        return (f'The user wants different options. Their notes: "{notes or "(none)"}". Make new directions that follow the notes and differ '
                "from the ones shown, write their screens, and call `design` again.")
    o = letters[choice]
    files = "\n".join(f"   - {s['name']} ({s['device']}): {s['file']}" for s in o["screens"])
    return (f"The user chose option {choice}: {o['name']}." + (f' Their notes: "{notes}".' if notes else "") + "\n"
            f"Its screens:\n{files}\n"
            "Now: 1) write the project's design system to `.afh/design.md` from this option (and the notes): the look in a sentence, "
            "colours (with hex), type (families, sizes, weights), spacing and radius scale, elevation, components and their states, "
            "platform conventions to follow, dark mode, and these mockup files as the reference. 2) Build following it exactly, matching "
            "the mockups screen by screen, then check the result against them (the browser tool for web).")


def prompt_section(directory: str) -> str:
    """The project's design system for the system prompt, when it has one."""
    path = Path(directory) / DESIGN_MD
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()[:12_000]
    except OSError:
        return ""
    if not text:
        return ""
    return ("# Project design system (.afh/design.md)\n\nThe user chose this design. Follow it in every screen and component you build "
            "here; change it only when they ask, and keep the file current when they do.\n\n" + text)


class DesignTool:
    spec = ToolSpec(
        name="design",
        description=(
            "Design first: show the user 2-4 design options (A, B, C…) for what they asked you to build, as mockups of its main screens in "
            "device frames, and wait for them to choose, mix or ask for new ones. Use it before building any new app, website, or screen "
            "set, or a redesign - for every platform (web, Android, iOS, Windows, macOS…). First write each screen as ONE self-contained "
            "HTML file (inline CSS/JS, realistic content, images as inline SVG or https URLs; no local assets) under "
            ".afh/designs/<short-name>/<a|b|c>/<screen>.html, sized for its device: phone 390-412 wide, tablet ~820, desktop 1440, app "
            "window ~1200×780 (draw the platform's title bar). Make the options truly different (layout, colour, type, density, mood), "
            "each internally consistent across its screens, and true to the platform (Material 3 on Android, Apple HIG on iOS/macOS, "
            "Fluent on Windows). Cover the 3-5 screens that matter most, on every screen type the product targets. The answer tells "
            "you which option won and what to do next."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What is being designed, e.g. \"Recipe app — Android\"."},
                "platform": {"type": "string", "enum": list(PLATFORMS)},
                "options": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": MAX_OPTIONS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "A short name for the direction, e.g. \"Calm & airy\"."},
                            "summary": {"type": "string", "description": "One or two sentences: the idea, palette, type, feel."},
                            "screens": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": MAX_SCREENS,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "description": "Screen name, e.g. Home, Detail, Settings."},
                                        "device": {"type": "string", "enum": list(DEVICES)},
                                        "file": {"type": "string", "description": "The HTML file, relative to the project."},
                                    },
                                    "required": ["file"],
                                },
                            },
                        },
                        "required": ["name", "screens"],
                    },
                },
            },
            "required": ["title", "platform", "options"],
        },
    )

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        try:
            req = clean(input, ctx.directory)
        except ValueError as err:
            return ToolResult(text=f"design: {err}", is_error=True)
        decision, message, answers = await ctx.permissions.ask_user("design", {"title": req["title"], "design": req})
        if decision == "reject":  # Stop pressed while the card was open
            raise PermissionDenied(message or "Interrupted")
        answer: Any = (answers or [{}])[0] if isinstance(answers, list) else {}
        if decision == "dismiss" or not isinstance(answer, dict):
            return ToolResult(text="The user closed the design options without choosing. Go on with the option you think fits best, say which "
                                   "and why in one line, and write `.afh/design.md` from it before building.",
                              metadata={"design": req, "dismissed": True})
        return ToolResult(text=report(req, answer), metadata={"design": req, "answer": {"choice": str(answer.get("choice") or "").upper()[:1],
                                                                                         "notes": str(answer.get("notes") or "")[:2000]}})
