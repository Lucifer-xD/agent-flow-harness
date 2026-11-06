"""Writes the animated mark into website/install.ps1 and website/install.sh, and the real one to website/install-mark.gz.

    python scripts/bake-mark.py

An installer has nothing to draw with, so it carries the frames: the same mark and the same loop as the app,
from afh/tui/mark.py. Three letters are a cell: its block and its two colours. The mark sits on its own dark
card, so it looks the same on any terminal, a white one included. The last frame is the mark at rest.
Terminals that take images get those instead, from afh/tui/picture.py: the same frames, one Sixel image to a line.
They'd make an installer ten times the size, so they stay beside it and the installers fetch them only when they can use them.
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from afh.tui import picture as images  # noqa: E402
from afh.tui.mark import BLOCKS, CYCLE, FPS, raster  # noqa: E402

COLS, ROWS = 24, 8
FRAMES = 32  # at ten a second, one loop is CYCLE seconds
BACK = (14, 13, 13)
LINE = ((255, 177, 31), (255, 74, 104), (224, 22, 154))  # the mark's gradient, for the line under it
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
START, END = "# mark:start, written by scripts/bake-mark.py", "# mark:end"
GLYPHS = list(BLOCKS)
Rgb = tuple[int, int, int]
Cell = tuple[str, Rgb, Rgb]


def picture(seconds: float | None) -> list[Cell]:
    return [cell for row in raster(COLS, ROWS).paint(BACK, seconds) for cell in row]


def pictures() -> list[list[Cell]]:
    return [picture(i * CYCLE / FRAMES) for i in range(FRAMES)] + [picture(None)]


def xterm(c: Rgb) -> int:
    """The closest of the 256 colours, for terminals without true colour."""
    levels = (0, 95, 135, 175, 215, 255)
    cube = [(sum((a - b) ** 2 for a, b in zip(c, (r, g, b))), 16 + 36 * i + 6 * j + k) for i, r in enumerate(levels) for j, g in enumerate(levels) for k, b in enumerate(levels)]
    greys = [(sum((a - v) ** 2 for a in c), 232 + i) for i, v in enumerate(range(8, 248, 10))]
    return min(cube + greys)[1]


def bake() -> tuple[list[Rgb], list[str]]:
    """Every colour of every frame in one picture, so one palette serves them all."""
    frames = pictures()
    colours = [c for frame in frames for _, ink, behind in frame for c in (ink, behind)]
    whole = Image.new("RGB", (len(colours), 1))
    whole.putdata(colours)
    small = whole.quantize(colors=len(LETTERS), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    flat = small.getpalette()
    palette = [tuple(flat[i * 3:i * 3 + 3]) for i in range(len(flat) // 3)][:len(LETTERS)]
    data = iter(small.tobytes())
    return palette, ["".join(LETTERS[GLYPHS.index(cell[0])] + LETTERS[next(data)] + LETTERS[next(data)] for cell in frame) for frame in frames]


def line() -> list[Rgb]:
    width = COLS + 2
    out = []
    for x in range(width):
        t = x / (width - 1) * 2
        lo = min(1, int(t))
        out.append(tuple(round(LINE[lo][i] + (LINE[lo + 1][i] - LINE[lo][i]) * (t - lo)) for i in range(3)))
    return out


def rgbs(colours: list[Rgb], quote: str, join: str) -> str:
    return join.join(f"{quote}{r};{g};{b}{quote}" for r, g, b in colours)


def powershell(palette: list[Rgb], frames: list[str]) -> str:
    rows = ",\n".join(f"        '{f}'" for f in frames)
    lines = [START, f"$markCols = {COLS}", f"$markRows = {ROWS}", f"$markLetters = '{LETTERS[:max(len(palette), len(GLYPHS))]}'", f"$markBack = '{';'.join(map(str, BACK))}'",
             f"$markBlocks = {', '.join(str(ord(g)) for g in GLYPHS)}",
             f"$markColors = {rgbs(palette, chr(39), ', ')}", f"$markLine = {rgbs(line(), chr(39), ', ')}", "$markFrames = @("]
    return "".join(f"    {x}\n" for x in lines) + rows + f"\n    )\n    {END}\n"


def shell(palette: list[Rgb], frames: list[str]) -> str:
    rows = "\n".join(f"  '{f}'" for f in frames)
    lines = [START, f"mark_cols={COLS}", f"mark_rows={ROWS}", f"mark_letters='{LETTERS[:max(len(palette), len(GLYPHS))]}'", f"mark_back_true='{';'.join(map(str, BACK))}'", f"mark_back_256={xterm(BACK)}",
             "mark_blocks=(" + " ".join(f"'{g}'" for g in GLYPHS) + ")",
             f"mark_true=({rgbs(palette, chr(39), ' ')})", f"mark_256=({' '.join(str(xterm(c)) for c in palette)})",
             f"mark_line_true=({rgbs(line(), chr(39), ' ')})", f"mark_line_256=({' '.join(str(xterm(c)) for c in line())})", "mark_frames=("]
    return "\n".join(lines) + "\n" + rows + f"\n)\n{END}\n"


def blocks() -> dict[Path, str]:
    palette, frames = bake()
    return {ROOT / "website/install.ps1": powershell(palette, frames), ROOT / "website/install.sh": shell(palette, frames)}


def carried(path: Path) -> str:
    source = path.read_bytes().decode()
    found = re.search(rf"^[ ]*{re.escape(START)}\n.*?^[ ]*{re.escape(END)}\n", source, re.S | re.M)
    return found.group(0) if found else ""


def film() -> bytes:
    """Sized for Windows Terminal's cells, which it scales to whatever the font is. Other terminals work out the rows it takes."""
    images.CELL = (10, 20)
    card = images.Film(COLS, ROWS, "#%02x%02x%02x" % BACK)
    frames = [card.encoded(i * FPS * CYCLE / FRAMES) for i in range(FRAMES)] + [card.encoded(None)]
    images.CELL = None
    return gzip.compress("\n".join(frames).encode(), 9, mtime=0)


def main() -> None:
    reel = film()
    (ROOT / "website/install-mark.gz").write_bytes(reel)
    print(f"install-mark.gz: {len(reel)} bytes")
    for path, block in blocks().items():
        source = path.read_bytes().decode()
        old = carried(path)
        if not old:
            sys.exit(f"{path.name} has no place for the mark")
        path.write_bytes(source.replace(old, block).encode())
        print(f"{path.name}: {len(block)} bytes of mark")


if __name__ == "__main__":
    main()
