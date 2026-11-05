"""The AFH mark in the terminal, from the same paths and timing as web/js/logo.js and app.css.

A terminal has no vector drawing, but it does have block elements: halves, quarters and eighths of a cell,
drawn as exact shapes. The real shapes are worked out at eight by eight samples a cell and each cell takes the
block closest to them, in the two colours it holds. Edges stay hard, because a soft edge at this size is a blur.
Idle, the three strands are connected. Working, each strand draws across to its right point,
holds, then lets go from the left and reconnects, staggered so the mark looks alive.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from functools import lru_cache
from typing import Iterable

from rich.color import Color
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

Rgb = tuple[float, float, float]
Cell = tuple[str, tuple[int, int, int], tuple[int, int, int]]  # a block, its colour and the colour behind it

STRANDS = (
    (28, "#ffb11f", "#ff7a3d", ((46, 28), (104, 28), (108, 74), (134, 74), (160, 74), (164, 28), (194, 28))),
    (70, "#ff7747", "#ff4a68", ((46, 70), (92, 70), (98, 58), (120, 60), (150, 63), (152, 82), (194, 70))),
    (112, "#ff3d8a", "#e0169a", ((46, 112), (108, 112), (116, 66), (146, 66), (172, 66), (170, 112), (194, 112))),
)
LEFT, RIGHT, RADIUS, STROKE, OPACITY = 46, 194, 15, 9, 0.92
VIEW = (24.0, 6.0, 192.0, 128.0)  # the mark's own box, with room for the points to swell
CYCLE = 3.2
DELAYS = (2.1, 1.05, 0.0)  # strand 0 runs 2.1 s ahead of strand 2, as in app.css
SAMPLES = 8  # per cell on each axis, one for each eighth a block can show
POINT_STEP = 3  # view units between the discs that trace a strand: closer changes nothing you can see
FPS = 15


def rgb(colour: str) -> Rgb:
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def ease(t: float) -> float:
    """cubic-bezier(0.65, 0, 0.35, 1), solved for x."""
    lo, hi = 0.0, 1.0
    for _ in range(18):
        u = (lo + hi) / 2
        x = 3 * (1 - u) ** 2 * u * 0.65 + 3 * (1 - u) * u * u * 0.35 + u ** 3
        if x < t:
            lo = u
        else:
            hi = u
    u = (lo + hi) / 2
    return 3 * (1 - u) * u * u + u ** 3


def between(t: float, stops: Iterable[tuple[float, float]]) -> float:
    """A value along keyframes [(at, value), ...]."""
    stops = list(stops)
    for (a, va), (b, vb) in zip(stops, stops[1:]):
        if a <= t <= b:
            return va + (vb - va) * ((t - a) / (b - a) if b > a else 1)
    return stops[-1][1]


def window(phase: float) -> tuple[float, float]:
    """The part of a strand drawn at this point of the cycle, from afh-link: 0 to 100 along the path."""
    if phase < 0.38:
        offset = 100 - 100 * ease(phase / 0.38)
    elif phase < 0.58:
        offset = 0
    else:
        offset = -100 * ease((phase - 0.58) / 0.42)
    return max(0.0, -offset), min(100.0, 100 - offset)


def left_scale(phase: float) -> float:
    return between(phase, ((0, 1), (0.06, 1.25), (0.2, 1), (1, 1)))


def right_point(phase: float) -> tuple[float, float]:
    return between(phase, ((0, 0.85), (0.3, 0.85), (0.4, 1.3), (0.58, 1), (1, 0.85))), between(phase, ((0, 0.6), (0.3, 0.6), (0.4, 1), (0.58, 1), (1, 0.6)))


def path_points(c: tuple) -> list[tuple[float, float, float]]:
    """Points along two cubic curves, one unit apart, each with how far along it is (0 to 100)."""
    raw: list[tuple[float, float]] = []
    for seg in (c[0:4], c[3:7]):
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg
        for i in range(201):
            u = i / 200
            a, b, d, e = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3
            raw.append((a * x0 + b * x1 + d * x2 + e * x3, a * y0 + b * y1 + d * y2 + e * y3))
    lengths = [0.0]
    for (ax, ay), (bx, by) in zip(raw, raw[1:]):
        lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
    total = lengths[-1]
    out, step = [], 0.0
    for (x, y), length in zip(raw, lengths):
        if length >= step:
            out.append((x, y, 100 * length / total))
            step += 1.0
    return out


def block(left: int, top: int, right: int, bottom: int) -> int:
    """The samples of a cell inside this box, one bit each."""
    return sum(1 << (y * SAMPLES + x) for y in range(top, bottom) for x in range(left, right))


FULL = block(0, 0, SAMPLES, SAMPLES)
BLOCKS = {" ": 0, "▀": block(0, 0, 8, 4), "▘": block(0, 0, 4, 4), "▝": block(4, 0, 8, 4), "▖": block(0, 4, 4, 8), "▗": block(4, 4, 8, 8)}
BLOCKS |= {"▚": BLOCKS["▘"] | BLOCKS["▗"], "▞": BLOCKS["▝"] | BLOCKS["▖"]}
BLOCKS |= {glyph: block(0, 8 - n, 8, 8) for n, glyph in enumerate("▁▂▃▄▅▆▇", 1)}
BLOCKS |= {glyph: block(0, 0, n, 8) for n, glyph in enumerate("▏▎▍▌▋▊▉", 1)}


@lru_cache(maxsize=16384)
def fit(shape: int) -> tuple[str, bool]:
    """The block closest to these samples, and whether its two colours swap to show them."""
    best = (SAMPLES * SAMPLES + 1, " ", False)
    for glyph, drawn in BLOCKS.items():
        for swapped, seen in ((False, drawn), (True, FULL ^ drawn)):
            wrong = (shape ^ seen).bit_count()
            if wrong < best[0]:
                best = (wrong, glyph, swapped)
    return best[1], best[2]


def distance(a: Rgb, b: Rgb) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def whole(colour: Rgb) -> tuple[int, int, int]:
    return int(colour[0] + 0.5), int(colour[1] + 0.5), int(colour[2] + 0.5)


def mixed(back: Rgb, colour: Rgb, amount: float) -> Rgb:
    return tuple(back[i] + (colour[i] - back[i]) * amount for i in range(3))


def settle(pieces: list[tuple[int, Rgb]]) -> Cell:
    """What covers a cell, as the block that shows it best. A cell only has two colours, so a third joins the closer one."""
    if len(pieces) == 1:
        return " ", whole(pieces[0][1]), whole(pieces[0][1])
    best: tuple[float, int, Rgb, Rgb] | None = None
    for i, (_, first) in enumerate(pieces):
        for _, second in pieces[i + 1:]:
            cost, shape = 0.0, 0
            for samples, colour in pieces:
                near, far = distance(colour, first), distance(colour, second)
                cost += samples.bit_count() * min(near, far)
                if near <= far:
                    shape |= samples
            if best is None or cost < best[0]:
                best = (cost, shape, first, second)
    _, shape, first, second = best
    glyph, swapped = fit(shape)
    return (glyph, whole(second), whole(first)) if swapped else (glyph, whole(first), whole(second))


class Raster:
    """One size of the mark: which samples of which cell every strand covers, worked out once."""

    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        vx, vy, vw, vh = VIEW
        self.unit = max(vw / cols, vh / (rows * 2))  # view units across a cell, and half of one down it
        self.x0 = vx - (cols * self.unit - vw) / 2
        self.y0 = vy - (rows * 2 * self.unit - vh) / 2
        self.step_x, self.step_y = self.unit / SAMPLES, self.unit * 2 / SAMPLES
        self.strands = [self.cover(c) for _, _, _, c in STRANDS]
        self.ink = [[self.tint(frm, to, x) for x in range(cols)] for _, frm, to, _ in STRANDS]
        self.discs: dict[tuple[float, float, float], dict[int, int]] = {}

    def tint(self, frm: str, to: str, x: int) -> Rgb:
        u = min(1, max(0, (self.x0 + (x + 0.5) * self.unit - LEFT) / (RIGHT - LEFT)))
        a, b = rgb(frm), rgb(to)
        return tuple(a[i] + (b[i] - a[i]) * u for i in range(3))

    def spot(self, sx: int, sy: int) -> tuple[int, int]:
        return (sy // SAMPLES) * self.cols + sx // SAMPLES, 1 << ((sy % SAMPLES) * SAMPLES + sx % SAMPLES)

    def around(self, cx: float, cy: float, radius: float) -> Iterable[tuple[int, int, float]]:
        """The samples in a disc, each with how far it is from the middle, squared."""
        width, height = self.cols * SAMPLES, self.rows * SAMPLES
        for sy in range(max(0, int((cy - radius - self.y0) / self.step_y) - 1), min(height, int((cy + radius - self.y0) / self.step_y) + 2)):
            dy = self.y0 + (sy + 0.5) * self.step_y - cy
            for sx in range(max(0, int((cx - radius - self.x0) / self.step_x) - 1), min(width, int((cx + radius - self.x0) / self.step_x) + 2)):
                dx = self.x0 + (sx + 0.5) * self.step_x - cx
                d = dx * dx + dy * dy
                if d <= radius * radius:
                    yield sx, sy, d

    def cover(self, curve: tuple) -> tuple[list[float], list[tuple[int, int]]]:
        """The strand's samples in order along it: how far along each one is, and where it is."""
        best: dict[tuple[int, int], tuple[float, float]] = {}
        for x, y, t in path_points(curve)[::POINT_STEP]:
            for sx, sy, d in self.around(x, y, STROKE):
                seen = best.get((sx, sy))
                if seen is None or d < seen[0]:
                    best[sx, sy] = (d, t)
        order = sorted((t, sx, sy) for (sx, sy), (_, t) in best.items())
        return [t for t, _, _ in order], [self.spot(sx, sy) for _, sx, sy in order]

    def disc(self, cx: float, cy: float, radius: float) -> dict[int, int]:
        key = (cx, cy, round(radius, 1))
        if key not in self.discs:
            shape: dict[int, int] = {}
            for sx, sy, _ in self.around(cx, cy, key[2]):
                cell, bit = self.spot(sx, sy)
                shape[cell] = shape.get(cell, 0) | bit
            self.discs[key] = shape
        return self.discs[key]

    def drawn(self, i: int, lo: float, hi: float) -> dict[int, int]:
        ts, places = self.strands[i]
        shape: dict[int, int] = {}
        for cell, bit in places[bisect_left(ts, lo):bisect_right(ts, hi)]:
            shape[cell] = shape.get(cell, 0) | bit
        return shape

    def paint(self, back: Rgb, seconds: float | None) -> list[list[Cell]]:
        """The picture at this moment of the loop, one row of cells at a time; None is the mark at rest."""
        covered: dict[int, int] = {}
        pieces: dict[int, list[tuple[int, Rgb]]] = {}

        def lay(shape: dict[int, int], colour: Rgb | list[Rgb]) -> None:
            """Top first, so whatever is already there hides what comes after."""
            for cell, samples in shape.items():
                seen = samples & ~covered.get(cell, 0)
                if seen:
                    covered[cell] = covered.get(cell, 0) | seen
                    pieces.setdefault(cell, []).append((seen, colour[cell % self.cols] if isinstance(colour, list) else colour))

        for i in (0, 1, 2):
            y, frm, to, _ = STRANDS[i]
            phase = None if seconds is None else ((seconds + DELAYS[i]) % CYCLE) / CYCLE
            a, b = (0.0, 100.0) if phase is None else window(phase)
            grow = 1.0 if phase is None else left_scale(phase)
            size, seen = (1.0, 1.0) if phase is None else right_point(phase)
            lay(self.disc(RIGHT, y, RADIUS * size), mixed(back, rgb(to), seen))
            lay(self.disc(LEFT, y, RADIUS * grow), rgb(frm))
            if b > a:
                cap = 100 * STROKE / 230  # a dash's round end, roughly
                lay(self.drawn(i, a - cap if a > 0 else -1, b + cap if b < 100 else 101), [mixed(back, c, OPACITY) for c in self.ink[i]])
        rows = []
        for y in range(self.rows):
            row: list[Cell] = []
            for x in range(self.cols):
                cell = y * self.cols + x
                mine = list(pieces.get(cell, ()))
                left = FULL ^ covered.get(cell, 0)
                if left:
                    mine.append((left, back))
                row.append(settle(mine))
            rows.append(row)
        return rows


@lru_cache(maxsize=8)
def raster(cols: int, rows: int) -> Raster:
    return Raster(cols, rows)


@lru_cache(maxsize=4096)
def style(colour: tuple[int, int, int], behind: tuple[int, int, int]) -> Style:
    return Style(color=Color.from_rgb(*colour), bgcolor=Color.from_rgb(*behind))


def strips(picture: list[list[Cell]], width: int) -> list[Strip]:
    rows = []
    for cells in picture:
        segments: list[Segment] = []
        run, last = "", None
        for glyph, colour, behind in cells:
            look = style(colour, behind)
            if look is last:
                run += glyph
                continue
            if last is not None:
                segments.append(Segment(run, last))
            last, run = look, glyph
        if last is not None:
            segments.append(Segment(run, last))
        rows.append(Strip(segments, width))
    return rows


@lru_cache(maxsize=512)
def frame(cols: int, rows: int, back: str, tick: int | None) -> list[Strip]:
    """One frame of the loop, kept: a run of the app only ever draws these few dozen."""
    seconds = None if tick is None else tick / FPS
    return strips(raster(cols, rows).paint(rgb(back), seconds), cols)


LOOP = round(CYCLE * FPS)


class Mark(Widget):
    """The mark. Set `working` and it flows, exactly like the app's. It sizes itself: 3 columns per row."""

    DEFAULT_CSS = "Mark { width: 12; height: 4; }"

    def __init__(self, rows: int = 4, working: bool = False, back: str = "", **kw):
        super().__init__(**kw)
        self.back = back
        self.resize(rows)
        self.tick = 0
        self.working = False
        self.speed = 1.0
        self.timer = None
        self.first = working

    def resize(self, rows: int) -> None:
        self.rows, self.cols = rows, rows * 3
        self.styles.width, self.styles.height = self.cols, rows

    def on_mount(self) -> None:
        self.flow(self.first)

    def flow(self, working: bool, speed: float = 1.0) -> None:
        if working == self.working and (self.timer is not None) == working and speed == self.speed:
            return
        self.working, self.speed = working, speed
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if working:
            self.timer = self.set_interval(1 / (FPS * speed), self.step)
        self.refresh()

    def step(self) -> None:
        self.tick = (self.tick + 1) % LOOP
        self.refresh()

    def backdrop(self) -> str:
        if self.back:
            return self.back
        colour = self.background_colors[1]
        return f"#{colour.r:02x}{colour.g:02x}{colour.b:02x}"

    def render_line(self, y: int) -> Strip:
        lines = frame(self.cols, self.rows, self.backdrop(), self.tick if self.working else None)
        return lines[y] if y < len(lines) else Strip.blank(self.cols)
