"""The mark as a real image, in terminals that can show one.

Blocks can only ever look like blocks. A terminal with Sixel takes true pixels, so there the mark is the app's own
anti-aliased drawing. The blocks from mark.py stay in the cells underneath, for whatever dims or covers the image
and for every other terminal. Text written over a cell wipes the image there, so AFH puts it back after any update
that touched it.
"""
from __future__ import annotations

import math
import os
import re
import sys
import threading
import time
from bisect import bisect_left
from functools import lru_cache
from typing import Any

from .mark import CYCLE, DELAYS, FPS, LEFT, LOOP, OPACITY, RADIUS, RIGHT, STRANDS, STROKE, VIEW, left_scale, path_points, rgb, right_point, window

CELL: tuple[int, int] | None = None  # pixels across and down a cell, once the terminal has said it takes Sixel
ASK = "\x1b[16t\x1b[c"  # the cell size, then what it can do: everything answers the second, so nothing waits on the first
PATIENCE = 0.4  # seconds for a terminal that answers neither
SUPER = 4  # drawn this many times bigger, then brought down: that's the anti-aliasing
COLOURS = 255
FADE = [int(v * OPACITY + 0.5) for v in range(256)]
TO_TEXT = bytes((v + 63) & 255 for v in range(256))
RUNS = re.compile(r"(.)\1{3,}")


def understood(reply: str) -> tuple[int, int] | None:
    """The cell size in a terminal's answer, if it says it has Sixel."""
    attributes = re.search(r"\x1b\[\?([\d;]*)c", reply)
    cell = re.search(r"\x1b\[6;(\d+);(\d+)t", reply)
    if not attributes or not cell or "4" not in attributes.group(1).split(";"):
        return None
    height, width = int(cell.group(1)), int(cell.group(2))
    return (width, height) if width and height else None


def answered(reply: str) -> bool:
    return re.search(r"\x1b\[\?[\d;]*c", reply) is not None


def ask_windows() -> str:
    import ctypes
    import msvcrt

    kernel = ctypes.windll.kernel32
    keyboard, screen = kernel.GetStdHandle(-10), kernel.GetStdHandle(-11)
    keyboard_mode, screen_mode = ctypes.c_uint(), ctypes.c_uint()
    if not kernel.GetConsoleMode(keyboard, ctypes.byref(keyboard_mode)) or not kernel.GetConsoleMode(screen, ctypes.byref(screen_mode)):
        return ""
    try:
        kernel.SetConsoleMode(screen, screen_mode.value | 0x4)  # escape sequences out
        kernel.SetConsoleMode(keyboard, 0x200)  # and the answer back in
        sys.stdout.write(ASK)
        sys.stdout.flush()
        reply, end = "", time.monotonic() + PATIENCE
        while time.monotonic() < end and not answered(reply):
            while msvcrt.kbhit():
                reply += msvcrt.getwch()
            time.sleep(0.002)
        return reply
    finally:
        kernel.SetConsoleMode(keyboard, keyboard_mode.value)
        kernel.SetConsoleMode(screen, screen_mode.value)


def ask_posix() -> str:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    keep = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(ASK)
        sys.stdout.flush()
        reply, end = "", time.monotonic() + PATIENCE
        while time.monotonic() < end and not answered(reply):
            if select.select([fd], [], [], 0.02)[0]:
                reply += os.read(fd, 256).decode("ascii", "replace")
        return reply
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, keep)


def probe() -> None:
    """Find out if this terminal takes images. Asked before the app starts, while the input is still ours to read."""
    global CELL
    if os.environ.get("AFH_NO_IMAGES") or os.environ.get("SSH_CONNECTION"):  # over a slow link a moving image would drag the app
        return
    try:
        CELL = understood(ask_windows() if os.name == "nt" else ask_posix())
    except (OSError, ValueError, ImportError):
        CELL = None


@lru_cache(maxsize=256)
def only(colour: int) -> bytes:
    """A table that keeps one colour as a 1 and turns the rest to 0."""
    return bytes(1 if v == colour else 0 for v in range(256))


def sixel(data: bytes, width: int, height: int, palette: list[str]) -> str:
    """Palette-indexed pixels as a Sixel image. Six rows make a band, and each colour in it is a line of bit patterns."""
    out = [f'\x1bP0;1;0q"1;1;{width};{height}']
    out += [palette[c] for c in sorted(set(data))]
    for top in range(0, height, 6):
        rows = [data[y * width:(y + 1) * width] for y in range(top, min(top + 6, height))]
        band = []
        for colour in sorted(set(b"".join(rows))):
            bits = 0
            for shift, row in enumerate(rows):
                bits |= int.from_bytes(row.translate(only(colour)), "little") << shift
            line = bits.to_bytes(width, "little").translate(TO_TEXT).rstrip(b"?").decode()
            band.append(f"#{colour}" + RUNS.sub(lambda m: f"!{len(m.group())}{m.group(1)}", line))
        out.append("$".join(band))
        out.append("-")
    out[-1] = "\x1b\\"  # no new line after the last band: at the foot of the screen, that would scroll it
    return "".join(out)


class Film:
    """The mark at one size on one background: its frames, drawn once. The loop fills in beside the app."""

    def __init__(self, cols: int, rows: int, back: str):
        from PIL import Image, ImageDraw

        self.Image, self.ImageDraw = Image, ImageDraw
        self.back = rgb(back)
        self.w, self.h = cols * CELL[0], rows * CELL[1]
        self.bands = self.h // 6 * 6  # a band past the foot of the screen would scroll it, so an image is whole bands
        vx, vy, vw, vh = VIEW
        self.unit = max(vw / self.w, vh / self.h)  # view units in a pixel
        self.x0 = vx - (self.w * self.unit - vw) / 2
        self.y0 = vy - (self.h * self.unit - vh) / 2
        self.paths = [path_points(curve) for _, _, _, curve in STRANDS]
        self.along = [[t for _, _, t in path] for path in self.paths]
        self.traces = [self.trace(path) for path in self.paths]
        self.ramps = [self.ramp(frm, to) for _, frm, to, _ in STRANDS]
        self.spots: dict[tuple[float, float, float], tuple[tuple[int, int, int, int], Any]] = {}
        self.frames: dict[Any, str] = {}
        self.filling: threading.Thread | None = None
        self.palette = self.sample()
        flat = self.palette.getpalette()
        self.registers = [f"#{i};2;{round(flat[i * 3] / 2.55)};{round(flat[i * 3 + 1] / 2.55)};{round(flat[i * 3 + 2] / 2.55)}" for i in range(len(flat) // 3)]

    def place(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x0) / self.unit, (y - self.y0) / self.unit

    def trace(self, path: list[tuple[float, float, float]]) -> Any:
        """The strand, big, each pixel holding how far along the strand reaches it. A frame is a threshold of this."""
        image = self.Image.new("L", (self.w * SUPER, self.h * SUPER), 0)
        pen = self.ImageDraw.Draw(image)
        radius = STROKE / self.unit * SUPER
        for x, y, t in path:
            cx, cy = self.place(x, y)
            cx, cy = cx * SUPER, cy * SUPER
            pen.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=1 + round(t * 2.5))
        return image

    def ramp(self, frm: str, to: str) -> Any:
        a, b = rgb(frm), rgb(to)
        row = self.Image.new("RGB", (self.w, 1))
        for x in range(self.w):
            u = min(1, max(0, (self.x0 + (x + 0.5) * self.unit - LEFT) / (RIGHT - LEFT)))
            row.putpixel((x, 0), tuple(round(a[i] + (b[i] - a[i]) * u) for i in range(3)))
        return row.resize((self.w, self.h))

    def strand(self, i: int, a: float, b: float) -> Any:
        first, last = 1 + round(a * 2.5), 1 + round(b * 2.5)
        mask = self.traces[i].point([255 if first <= v <= last else 0 for v in range(256)])
        if b < 100:  # the head of a dash is as round as its tail
            x, y, _ = self.paths[i][min(bisect_left(self.along[i], b), len(self.paths[i]) - 1)]
            cx, cy = self.place(x, y)
            radius = STROKE / self.unit * SUPER
            self.ImageDraw.Draw(mask).ellipse((cx * SUPER - radius, cy * SUPER - radius, cx * SUPER + radius, cy * SUPER + radius), fill=255)
        return mask.reduce(SUPER).point(FADE)

    def spot(self, x: float, y: float, radius: float) -> tuple[tuple[int, int, int, int], Any]:
        key = (x, y, round(radius, 1))
        if key not in self.spots:
            cx, cy = self.place(x, y)
            r = key[2] / self.unit
            left, top = math.floor(cx - r) - 1, math.floor(cy - r) - 1
            size = math.ceil(2 * r) + 4
            big = self.Image.new("L", (size * SUPER, size * SUPER), 0)
            self.ImageDraw.Draw(big).ellipse(((cx - r - left) * SUPER, (cy - r - top) * SUPER, (cx + r - left) * SUPER, (cy + r - top) * SUPER), fill=255)
            self.spots[key] = ((left, top, left + size, top + size), big.reduce(SUPER))
        return self.spots[key]

    def draw(self, seconds: float | None) -> Any:
        """The picture at this moment of the loop; None is the mark at rest."""
        canvas = self.Image.new("RGB", (self.w, self.h), self.back)
        for i in (2, 1, 0):
            y, frm, to, _ = STRANDS[i]
            phase = None if seconds is None else ((seconds + DELAYS[i]) % CYCLE) / CYCLE
            a, b = (0.0, 100.0) if phase is None else window(phase)
            if b > a:
                canvas.paste(self.ramps[i], (0, 0), self.strand(i, a, b))
            grow = 1.0 if phase is None else left_scale(phase)
            size, seen = (1.0, 1.0) if phase is None else right_point(phase)
            box, mask = self.spot(LEFT, y, RADIUS * grow)
            canvas.paste(rgb(frm), box, mask)
            box, mask = self.spot(RIGHT, y, RADIUS * size)
            canvas.paste(rgb(to), box, mask.point(lambda v: int(v * seen)))
        return canvas

    def sample(self) -> Any:
        """One palette for every frame, so a colour doesn't shift between them."""
        moments = (None, 0.4, 1.2, 2.0)
        sheet = self.Image.new("RGB", (self.w * len(moments), self.h), self.back)
        for n, seconds in enumerate(moments):
            sheet.paste(self.draw(seconds), (n * self.w, 0))
        return sheet.quantize(colors=COLOURS, method=self.Image.Quantize.MEDIANCUT, dither=self.Image.Dither.NONE)

    def encoded(self, tick: int | None, top: int = 0, rows: int | None = None) -> str:
        picture = self.draw(None if tick is None else tick / FPS)
        indexed = picture.quantize(palette=self.palette, dither=self.Image.Dither.NONE).tobytes()
        bands = self.bands if rows is None else rows * CELL[1] // 6 * 6
        start = top * CELL[1] * self.w
        return sixel(indexed[start:start + self.w * bands], self.w, bands, self.registers)

    def part(self, top: int, rows: int) -> str:
        """The mark at rest, cut down to the rows of it that show."""
        key = ("part", top, rows)
        if key not in self.frames:
            self.frames[key] = self.encoded(None, top, rows)
        return self.frames[key]

    def fill(self) -> None:
        for tick in range(LOOP):
            if tick not in self.frames:
                self.frames[tick] = self.encoded(tick)

    def frame(self, tick: int | None) -> str | None:
        """A frame if it's ready. The first one to be asked for always is; the rest of the loop comes in beside the app."""
        if tick in self.frames:
            return self.frames[tick]
        if tick is None or not self.frames:
            self.frames[tick] = self.encoded(tick)
            return self.frames[tick]
        if self.filling is None:
            self.filling = threading.Thread(target=self.fill, daemon=True, name="afh-mark")
            self.filling.start()
        return None


@lru_cache(maxsize=4)
def film(cols: int, rows: int, back: str) -> Film:
    return Film(cols, rows, back)
