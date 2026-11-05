"""AFH's own look in the terminal. One idea: the harness.

Nothing is outlined. Surfaces are filled and meet with soft half-cell edges, lines are light, and every
line connects: a strand runs down the conversation with each event a point on it, ends in the living mark
at the message box, and a run is light moving along it. Colours come from the theme, so all 46 keep working.
"""
from __future__ import annotations

import colorsys
from bisect import bisect_right
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterable, Iterator

from rich.color import Color
from rich.segment import Segment
from rich.style import Style
from textual.color import Color as Parsed
from pygments.token import Token
from textual.content import Content
from textual.geometry import Region
from textual.highlight import HighlightTheme
from textual.strip import Strip
from textual.widget import MountError, Widget

from .mark import FPS

Rgb = tuple[int, int, int]
LIGHT_SECONDS = 2.6  # one pass of light along a line
SPINE_X = 2  # the column the strand runs down, and the column of the mark's left points
BAND = 3  # cells of a line of light that share a colour: the eye can't tell, and it's a third of the bytes


def parse(value: Any, default: Rgb = (128, 128, 128)) -> Rgb:
    try:
        return Parsed.parse(str(value)).rgb
    except Exception:
        return default


def mixed(a: Rgb, b: Rgb, amount: float) -> Rgb:
    return tuple(round(a[i] + (b[i] - a[i]) * amount) for i in range(3))


@lru_cache(maxsize=64)
def stops(accent: Rgb) -> tuple[Rgb, Rgb, Rgb]:
    """A theme's gradient: its accent turned a little each way. Sunset's lands on the brand's amber and pink."""
    h, lum, s = colorsys.rgb_to_hls(*(v / 255 for v in accent))

    def turned(degrees: float) -> Rgb:
        return tuple(round(v * 255) for v in colorsys.hls_to_rgb((h + degrees / 360) % 1, lum, s))

    return turned(30), accent, turned(-30)


def along(ramp: tuple[Rgb, Rgb, Rgb], t: float) -> Rgb:
    t = max(0.0, min(1.0, t)) * 2
    lo = min(1, int(t))
    return mixed(ramp[lo], ramp[lo + 1], t - lo)


def hexed(c: Rgb) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


@lru_cache(maxsize=2048)
def ink(colour: Rgb, back: Rgb | None = None, bold: bool = False) -> Style:
    return Style(color=Color.from_rgb(*colour), bgcolor=Color.from_rgb(*back) if back else None, bold=bold or None)


class Palette:
    """The theme's colours as numbers, for the widgets that paint their own cells."""

    def __init__(self, app: Any):
        v = app.theme_variables
        self.back = parse(v.get("background"), (14, 13, 13))
        self.surface = parse(v.get("surface"), (23, 21, 21))
        self.panel = parse(v.get("panel"), (30, 27, 26))
        self.accent = parse(v.get("primary"), (255, 106, 42))
        self.text = parse(v.get("foreground"), (242, 239, 236))
        self.text2 = parse(v.get("afh-text2"), (180, 173, 166))
        self.text3 = parse(v.get("afh-text3"), (126, 119, 111))
        self.good = parse(v.get("success"), (74, 222, 128))
        self.bad = parse(v.get("error"), (248, 113, 113))
        self.warn = parse(v.get("warning"), (251, 191, 36))
        self.ramp = stops(self.accent)
        self.dark = sum(self.back) < 384

    @classmethod
    def of(cls, app: Any) -> "Palette":
        """One per theme: the strand repaints every frame of a run, and a new theme is a new dict of variables."""
        found = getattr(app, "palette_cache", None)
        if found is None or found[0] is not app.theme_variables:
            found = app.palette_cache = (app.theme_variables, cls(app))
        return found[1]


@contextmanager
def unless_gone(widget: Widget) -> Iterator[None]:
    """For adding to a widget that quitting can take away first. That is no fault, so nothing prints on the way out."""
    try:
        yield
    except MountError:
        if widget.is_attached:
            raise


def chip(text: Any, fg: str = "$afh-text2", back: str = "$panel") -> Content:
    """A filled pill. Its half-cell ends read as rounded at terminal sizes."""
    return Content.assemble(("▐", back), (text if isinstance(text, str) else str(text), f"{fg} on {back}"), ("▌", back))


def keys(hint: str, back: str = "$panel") -> Content:
    """"Enter pick   Esc close" with each key as a small filled cap."""
    parts: list[Any] = []
    for piece in [x for x in hint.split("   ") if x.strip()]:
        key, _, label = piece.strip().partition(" ")
        parts += [(f" {key} ", f"$afh-text2 on {back}"), (f" {label}   " if label else "   ", "$afh-text3")]
    return Content.assemble(*parts)


def shimmer(text: str, ramp: tuple[Rgb, Rgb, Rgb], moment: float, base: Rgb) -> Content:
    """Words with light passing through them, for whatever is happening right now."""
    n = max(1, len(text))
    head = (moment % 1.0) * (n + 16) - 8
    pieces = []
    for i, ch in enumerate(text):
        glow = max(0.0, 1 - abs(i - head) / 7)
        pieces.append((ch, hexed(mixed(base, along(ramp, i / n), glow))))
    return Content.assemble(*pieces)


class Flowline(Widget):
    """The line of light along the top of the deck. Bright up to how full the context is; a run sends light along it."""

    DEFAULT_CSS = "Flowline { height: 1; width: 1fr; }"
    can_focus = False

    def __init__(self, join: int | None = None, **kw: Any):
        super().__init__(**kw)
        self.fill = 0.0
        self.tone = ""
        self.tick = 0
        self.timer: Any = None
        self.join = join

    def set_fill(self, fill: float, tone: str = "") -> None:
        if (fill, tone) != (self.fill, self.tone):
            self.fill, self.tone = fill, tone
            self.refresh()

    def run(self, on: bool) -> None:
        if on == (self.timer is not None):
            return
        if on:
            self.timer = self.set_interval(1 / FPS, self.step)
        else:
            self.timer.stop()
            self.timer = None
        self.refresh()

    def step(self) -> None:
        self.tick += 1
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if not width:
            return Strip.blank(0)
        p = Palette.of(self.app)
        under = self.background_colors[1]
        behind = (under.r, under.g, under.b)
        tone = getattr(p, self.tone) if self.tone else None
        ramp = (tone, tone, mixed(tone, p.accent, 0.6)) if tone else p.ramp
        moment = (self.tick / FPS / LIGHT_SECONDS) % 1 if self.timer is not None else None
        head = None if moment is None else moment * (width + 40) - 20
        segments: list[Segment] = []
        for x in range(0, width, BAND):
            c = along(ramp, x / max(1, width - 1))
            if x / width >= self.fill:
                c = mixed(behind, c, 0.5 if p.dark else 0.6)
            if head is not None:
                glow = max(0.0, 1 - abs(x - head) / 20)
                c = mixed(c, (255, 255, 255) if p.dark else along(ramp, 0.5), glow * glow * 0.85)
            cells = "".join("┷" if i == self.join else "━" for i in range(x, min(x + BAND, width)))
            segments.append(Segment(cells, ink(c, behind)))
        return Strip(segments, width)


STEPS = {"step": ("•", "text3"), "think": ("·", "text3"), "edit": ("•", "good"), "plan": ("•", "accent"), "fail": ("×", "bad"), "warn": ("•", "warn")}


def code_colours() -> None:
    """Code in the app's colours: names stay plain, keywords and functions take the two ends of the gradient."""
    styles = HighlightTheme.STYLES
    styles[Token.Name] = ""
    styles[Token.Keyword] = styles[Token.Keyword.Namespace] = styles[Token.Operator.Word] = "$text-accent"
    styles[Token.Name.Function] = styles[Token.Name.Function.Magic] = styles[Token.Name.Builtin] = "$text-secondary"
    styles[Token.Name.Class] = "$text-secondary bold"
    styles[Token.Name.Decorator] = "$text-accent"
    styles[Token.Name.Constant] = "$text-warning"
    styles[Token.Name.Variable] = ""
    styles[Token.Operator] = ""


class Spine(Widget):
    """The strand down the left of the conversation. Every row of the thread that has a `node` is a point on it."""

    DEFAULT_CSS = "Spine { width: 4; height: 1fr; } Spine.-off { display: none; }"
    can_focus = False

    def __init__(self, view: Any, **kw: Any):
        super().__init__(**kw)
        self.view = view
        self.map: list[tuple[int, str]] | None = None
        self.turns: list[int] = []
        self.seen: Any = None
        self.tick = 0
        self.timer: Any = None
        self.running = False
        self.lit = 0

    def on_mount(self) -> None:
        self.set_interval(1 / 10, self.check)

    def check(self) -> None:
        """Layout moves without telling anyone: a fold opening, a reply growing, the wheel."""
        v = self.view
        now = (v.scroll_y, v.virtual_size.height, v.size.height, len(v.rows), self.app.theme)
        if now != self.seen:
            self.seen = now
            self.redraw()

    def redraw(self) -> None:
        self.map = None
        self.refresh()

    def run(self, on: bool) -> None:
        if on == self.running:
            return
        self.running = on
        if on:
            self.timer = self.set_interval(1 / FPS, self.step)
        elif self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.redraw()

    def step(self) -> None:
        """Only the rows the light is on: the working point blinks every fifth frame, and the rest stands still."""
        self.tick += 1
        if self.tick % 5 == 0 or not self.map:
            self.refresh()
            return
        y = round(self.head())
        top, bottom = max(0, min(y, self.lit) - 5), min(self.size.height, max(y, self.lit) + 6)
        self.lit = y
        if bottom > top:
            self.refresh(Region(0, top, 4, bottom - top))

    def head(self) -> float:
        """Where the light is on the last turn's strand."""
        start = self.turns[-1] if self.turns else 0
        end = max(self.map[-1][0] if self.map else 0, self.size.height)
        return start + (self.tick / FPS / LIGHT_SECONDS) % 1 * (end - start + 8) - 4

    def build(self) -> None:
        top = self.region.y
        points: list[tuple[int, str]] = []
        for row, kind in self.view.points():
            region = row.region
            if region.height:
                points.append((region.y - top + getattr(row, "node_row", 0), kind))
        points.sort(key=lambda p: p[0])
        self.map = points
        self.turns = [y for y, kind in points if kind == "you"]
        if points and (not self.turns or points[0][0] < self.turns[0]):
            self.turns.insert(0, points[0][0])

    def strand(self, y: int, p: Palette) -> Rgb | None:
        """The colour of the line on this row: each turn is one strand, from your colour to the reply's."""
        if not self.map or y < self.map[0][0]:
            return None
        at = bisect_right(self.turns, y) - 1
        start = self.turns[max(0, at)]
        last = at >= len(self.turns) - 1
        end = max(self.map[-1][0], self.size.height) if last else self.turns[at + 1]
        t = (y - start) / max(1, end - start)
        c = along(p.ramp, t)
        c = mixed(p.back, c, 0.5 if p.dark else 0.62)
        if self.running and last:
            glow = max(0.0, 1 - abs(y - self.head()) / 4)
            c = mixed(c, (255, 255, 255) if p.dark else along(p.ramp, 0.5), glow * 0.9)
        return c

    def render_line(self, y: int) -> Strip:
        if self.map is None:
            self.build()
        p = Palette.of(self.app)
        cells: list[tuple[str, Style]] = [(" ", ink(p.back, p.back))] * 4
        line = self.strand(y, p)
        if line:
            cells[SPINE_X] = ("│", ink(line, p.back))
        for kind in self.here(y):
            if kind in ("you", "reply"):
                cells[SPINE_X] = ("●", ink(p.ramp[0] if kind == "you" else p.ramp[2], p.back))
            elif kind == "fork":
                cells[SPINE_X], cells[3] = ("├", ink(p.accent, p.back)), ("─", ink(p.accent, p.back))
            elif kind == "work":
                cells[SPINE_X] = ("●" if (self.tick // 5) % 2 else "•", ink(p.accent, p.back))
            elif kind in STEPS:
                glyph, tone = STEPS[kind]
                cells[SPINE_X] = (glyph, ink(getattr(p, tone), p.back))
        return Strip([Segment(ch, style) for ch, style in cells], 4)

    def here(self, y: int) -> Iterable[str]:
        points = self.map or []
        i = bisect_right(points, (y, "\uffff"))
        while i > 0 and points[i - 1][0] == y:
            i -= 1
            yield points[i][1]


__all__ = ["Flowline", "Spine", "Palette", "chip", "keys", "shimmer", "stops", "along", "hexed", "mixed", "parse"]
