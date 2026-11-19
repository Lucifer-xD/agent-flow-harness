"""Windows UI Automation: what a window is made of — its buttons, fields, menus, tabs and list items,
by name, with where each one is on the screen. The same information screen readers use.

The computer tool's `elements` action lists them numbered (@1, @2…) so the model can click or type
into "@3" or "Save" instead of guessing pixels off a screenshot. One cross-process call per listing
(FindAllBuildCache with the properties cached), off the event loop, with a time limit.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

# UIA property ids
NAME, CONTROL_TYPE, RECT, ENABLED, OFFSCREEN, PASSWORD, AUTOMATION_ID = 30005, 30003, 30001, 30010, 30022, 30019, 30011
VALUE, TOGGLE, HAS_FOCUS, HELP = 30045, 30086, 30008, 30013
TYPES = {50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox", 50004: "field", 50005: "link", 50006: "image",
         50007: "list item", 50008: "list", 50009: "menu", 50010: "menu bar", 50011: "menu item", 50012: "progress bar",
         50013: "radio button", 50014: "scroll bar", 50015: "slider", 50016: "spinner", 50017: "status bar", 50018: "tab list",
         50019: "tab", 50020: "text", 50021: "toolbar", 50022: "tooltip", 50023: "tree", 50024: "tree item", 50025: "custom",
         50026: "group", 50027: "thumb", 50028: "grid", 50029: "row", 50030: "document", 50031: "split button", 50032: "window",
         50033: "pane", 50034: "header", 50035: "header item", 50036: "table", 50037: "title bar", 50038: "separator"}
# What a person clicks or types into (text is listed too, last, as it tells you where you are)
ACTIVE = {50000, 50002, 50003, 50004, 50005, 50007, 50011, 50013, 50015, 50016, 50019, 50024, 50029, 50030, 50031, 50035}
LABELS = {50020}
_local = threading.local()


class Unavailable(Exception):
    pass


@dataclass
class Element:
    kind: str
    name: str
    rect: tuple[int, int, int, int]  # physical screen pixels: left, top, right, bottom
    enabled: bool = True
    value: str = ""
    state: str = ""  # "checked" / "not checked" for toggles
    password: bool = False
    focused: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2

    @property
    def active(self) -> bool:
        return self.kind not in ("text",)


def _automation():
    """One IUIAutomation per thread (COM objects belong to the thread that made them)."""
    auto = getattr(_local, "auto", None)
    if auto is not None:
        return auto, _local.mod
    try:
        import comtypes
        import comtypes.client as cc
    except ImportError as err:
        raise Unavailable("UI Automation needs the comtypes package") from err
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    except OSError:
        pass  # already initialized on this thread
    mod = cc.GetModule("UIAutomationCore.dll")
    auto = cc.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=mod.IUIAutomation)
    _local.auto, _local.mod = auto, mod
    return auto, mod


def _variant_text(v) -> str:
    if v is None:
        return ""
    try:
        return str(v).strip()
    except Exception:
        return ""


def elements(hwnd: int, limit: int = 400) -> list[Element]:
    """The visible controls of one top-level window, in reading order (top to bottom, left to right)."""
    auto, mod = _automation()
    root = auto.ElementFromHandle(hwnd)
    cache = auto.CreateCacheRequest()
    for pid in (NAME, CONTROL_TYPE, RECT, ENABLED, PASSWORD, VALUE, TOGGLE, HAS_FOCUS, HELP, AUTOMATION_ID):
        cache.AddProperty(pid)
    cond = auto.CreatePropertyCondition(OFFSCREEN, False)
    found = root.FindAllBuildCache(mod.TreeScope_Descendants, cond, cache)
    out: list[Element] = []
    for i in range(min(found.Length, 3000)):
        e = found.GetElement(i)
        try:
            ct = int(e.CachedControlType)
            if ct not in ACTIVE and ct not in LABELS:
                continue
            r = e.CachedBoundingRectangle
            rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
            if rect[2] - rect[0] < 3 or rect[3] - rect[1] < 3:
                continue
            name = _variant_text(e.CachedName) or _variant_text(e.GetCachedPropertyValue(HELP)) or _variant_text(e.GetCachedPropertyValue(AUTOMATION_ID))
            if ct in LABELS and not name:
                continue
            password = bool(e.GetCachedPropertyValue(PASSWORD))
            value = "" if password else _variant_text(e.GetCachedPropertyValue(VALUE))
            toggle = e.GetCachedPropertyValue(TOGGLE)
            # only real toggles: other controls give back UIA's "not supported" marker, which reads as a number
            state = {0: "not checked", 1: "checked", 2: "mixed"}.get(toggle, "") if isinstance(toggle, int) and ct in (50002, 50013) else ""
            out.append(Element(TYPES.get(ct, "control"), name.replace("\n", " ")[:90], rect, bool(e.CachedIsEnabled), value[:60], state,
                               password, bool(e.GetCachedPropertyValue(HAS_FOCUS))))
        except Exception:
            continue
    # drop exact repeats (a list item and its own text), keep reading order
    seen, unique = set(), []
    for el in sorted(out, key=lambda x: (x.rect[1] // 8, x.rect[0])):
        key = (el.name, el.rect)
        if key in seen or (el.kind == "text" and any(o.kind != "text" and o.name == el.name and _inside(el.rect, o.rect) for o in out)):
            continue
        seen.add(key)
        unique.append(el)
    active = [e for e in unique if e.active]
    labels = [e for e in unique if not e.active]
    return (active + labels)[:limit]


def focus_at(x: int, y: int) -> bool:
    """Give the keyboard focus to the control at a screen point (for typing into a field by name)."""
    auto, _ = _automation()
    try:
        from ctypes import wintypes

        el = auto.ElementFromPoint(wintypes.POINT(x, y))
        el.SetFocus()
        return True
    except Exception:
        return False


def _inside(a, b) -> bool:
    return a[0] >= b[0] - 2 and a[1] >= b[1] - 2 and a[2] <= b[2] + 2 and a[3] <= b[3] + 2


def find(items: list[Element], query: str) -> Element | None:
    """By "@N" (from a listing), or by name: exact, then starts with, then contains; controls before text."""
    q = query.strip()
    if q.startswith("@") and q[1:].isdigit():
        n = int(q[1:])
        return items[n - 1] if 1 <= n <= len(items) else None
    want = " ".join(q.lower().split())
    best, score = None, 0
    for el in items:
        name = " ".join(el.name.lower().split())
        if not name:
            continue
        s = 4 if name == want else 3 if name.startswith(want) else 2 if want in name else 0
        if s and el.active:
            s += 0.5
        if s and el.enabled:
            s += 0.2
        if s > score:
            best, score = el, s
    return best
