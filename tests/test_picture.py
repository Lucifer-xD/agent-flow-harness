"""The mark as a real image: what a terminal answers, the Sixel itself, and when the app may draw it."""
from __future__ import annotations

import asyncio
import gzip
import re
import time
from pathlib import Path

import pytest

from afh import cli
from afh.tui import mark, picture
from afh.tui.app import AFH
from test_tui import backend, screen_text, shows, until  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_TERMINAL = "\x1b[6;20;10t\x1b[?61;4;6;7;14;21;22;23;24;28;32;42;52c"


@pytest.fixture
def images(monkeypatch):
    monkeypatch.setattr(picture, "CELL", (10, 20))
    picture.film.cache_clear()
    yield
    picture.film.cache_clear()


def decoded(text: str) -> tuple[int, int, dict[tuple[int, int], int]]:
    """Reads Sixel the way a terminal does: every pixel ends up with the colour number that set it."""
    head = re.match(r'\x1bP0;1;0q"1;1;(\d+);(\d+)', text)
    assert head and text.endswith("\x1b\\")
    width, height = int(head.group(1)), int(head.group(2))
    pixels: dict[tuple[int, int], int] = {}
    x = y = colour = 0
    for token in re.findall(r"#\d+;2;\d+;\d+;\d+|#\d+|!\d+.|[?-~]|\$|-", text[head.end():-2]):
        if token.startswith("#"):
            if ";" not in token:
                colour = int(token[1:])
            continue
        if token == "$":
            x = 0
            continue
        if token == "-":
            x, y = 0, y + 6
            continue
        count, bits = (int(token[1:-1]), ord(token[-1]) - 63) if token[0] == "!" else (1, ord(token) - 63)
        for _ in range(count):
            for row in range(6):
                if bits >> row & 1:
                    pixels[x, y + row] = colour
            x += 1
    return width, height, pixels


def test_a_terminal_that_says_sixel_gets_images():
    assert picture.understood(WINDOWS_TERMINAL) == (10, 20)
    assert picture.answered(WINDOWS_TERMINAL)


@pytest.mark.parametrize("reply", ["", "\x1b[?61;6;7c", "\x1b[6;20;10t\x1b[?61;6;7;14c", "\x1b[?61;4c", "\x1b[6;0;0t\x1b[?61;4c", "\x1b[6;20;10t\x1b[?64;41;42c"])
def test_anything_else_stays_on_blocks(reply):
    assert picture.understood(reply) is None


def test_asking_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(picture, "CELL", None)
    monkeypatch.setenv("AFH_NO_IMAGES", "1")
    monkeypatch.setattr(picture, "ask_windows", lambda: WINDOWS_TERMINAL)
    monkeypatch.setattr(picture, "ask_posix", lambda: WINDOWS_TERMINAL)
    picture.probe()
    assert picture.CELL is None


def test_a_terminal_that_wont_be_asked_stays_on_blocks(monkeypatch):
    def broken():
        raise OSError("no console")

    monkeypatch.delenv("AFH_NO_IMAGES", raising=False)
    monkeypatch.setattr(picture, "CELL", (1, 1))
    monkeypatch.setattr(picture, "ask_windows", broken)
    monkeypatch.setattr(picture, "ask_posix", broken)
    picture.probe()
    assert picture.CELL is None


def test_sixel_holds_every_pixel():
    width, height = 23, 12
    data = bytes((x * 7 + y * 3) % 5 if y % 2 else 2 for y in range(height) for x in range(width))
    palette = [f"#{i};2;{i};{i};{i}" for i in range(5)]
    w, h, pixels = decoded(picture.sixel(data, width, height, palette))
    assert (w, h) == (width, height)
    assert all(pixels[x, y] == data[y * width + x] for y in range(height) for x in range(width))


def test_sixel_ends_without_a_new_line():
    """A new line after the last band, at the foot of the screen, scrolls the whole app up."""
    text = picture.sixel(bytes(6 * 4), 4, 6, ["#0;2;0;0;0"])
    assert "-" not in text.split("q", 1)[1]


def test_an_image_is_whole_bands(images):
    """The deck ends on the last row of the screen. 80 pixels is 13 bands and a bit, and the bit scrolled the app."""
    for rows in (4, 8, 13):
        film = picture.Film(rows * 3, rows, "#181616")
        width, height, pixels = decoded(film.encoded(None))
        assert height % 6 == 0 and rows * 20 - 6 < height <= rows * 20
        assert width == rows * 30
        assert len(pixels) == width * height  # opaque: a frame replaces the last one completely


def test_the_mark_is_smooth(images):
    """Many shades along its edges, the way the app's drawing has them. Blocks have two colours a cell."""
    film = picture.Film(12, 4, "#181616")
    picture_now = film.draw(None)
    assert picture_now.size == (120, 80)
    assert len(picture_now.getcolors(100000)) > 200
    assert picture_now.getpixel((0, 0)) == (0x18, 0x16, 0x16)


def test_the_mark_moves(images):
    film = picture.Film(12, 4, "#181616")
    assert film.encoded(0) != film.encoded(mark.LOOP // 2)
    assert film.encoded(None) != film.encoded(0)


def test_the_loop_fills_in_beside_the_app(images):
    film = picture.film(12, 4, "#181616")
    assert film.frame(0)
    assert film.frame(1) is None  # not yet, and nothing waits for it
    end = time.time() + 20
    while time.time() < end and len(film.frames) < mark.LOOP:
        time.sleep(0.02)
    assert all(film.frame(tick) for tick in range(mark.LOOP))


def test_without_images_nothing_is_written(backend, tmp_path):  # noqa: F811
    async def go():
        def opener():
            return cli.Client(backend["url"], backend["key"])

        app = AFH(None, None, str(tmp_path), home=backend["home"], opener=opener)
        written = []
        app.overlay = lambda *a: written.append(a)
        async with app.run_test(size=(100, 32)) as pilot:
            await until(pilot, lambda: app.scroller.query("#home"), what="the start screen")
            await pilot.pause(0.3)
            app.exit()
        app.client.close()
        assert not written

    assert picture.CELL is None
    asyncio.run(asyncio.wait_for(go(), 60))


def test_images_go_where_the_mark_is_and_nowhere_else(backend, tmp_path, images):  # noqa: F811
    async def go():
        def opener():
            return cli.Client(backend["url"], backend["key"])

        app = AFH(None, None, str(tmp_path), home=backend["home"], opener=opener)
        written = []
        app.overlay = lambda x, y, image: written.append((x, y, image))
        async with app.run_test(size=(100, 32)) as pilot:
            await until(pilot, lambda: app.scroller.query("#home"), what="the start screen")
            await pilot.pause(0.2)
            deck = app.composer.mark
            assert deck in app.marks
            assert deck.in_view()
            assert deck.paint()
            assert written[-1][:2] == (deck.region.x, deck.region.y)
            assert written[-1][2].startswith("\x1bP")

            written.clear()
            await pilot.press("f2")  # a screen over it: the dimmed blocks show, not an image on top of the dialog
            await pilot.pause(0.3)
            assert not deck.in_view()
            assert not deck.paint()
            assert not written
            await pilot.press("escape")
            await pilot.pause(0.3)
            assert deck.in_view()
            app.exit()
        app.client.close()

    asyncio.run(asyncio.wait_for(go(), 60))


def test_something_over_the_mark_keeps_the_image_off(backend, tmp_path, images):  # noqa: F811
    async def go():
        def opener():
            return cli.Client(backend["url"], backend["key"])

        app = AFH(None, None, str(tmp_path), home=backend["home"], opener=opener)
        app.overlay = lambda *a: None
        async with app.run_test(size=(100, 32)) as pilot:
            await until(pilot, lambda: app.scroller.query("#home"), what="the start screen")
            deck = app.composer.mark
            assert deck.in_view()
            from textual.widgets import Static

            cover = Static("over it")
            cover.styles.layer = "cover"
            cover.styles.position = "absolute"
            cover.styles.offset = (deck.region.x, deck.region.y)
            cover.styles.width, cover.styles.height = 4, 2
            app.screen.styles.layers = ("base", "cover")
            await app.screen.mount(cover)
            await pilot.pause(0.2)
            assert not deck.in_view()
            await cover.remove()
            await pilot.pause(0.2)
            assert deck.in_view()
            app.exit()
        app.client.close()

    asyncio.run(asyncio.wait_for(go(), 60))


def test_an_update_over_the_mark_brings_it_back(images):
    class Update:
        spans = [(5, 0, 40)]

    class Far:
        spans = [(2, 0, 40), (9, 0, 40), (5, 30, 40)]

    class Whole:  # a full repaint has no spans
        pass

    class Here(mark.Mark):
        region = type("R", (), {"x": 10, "y": 4, "right": 22, "bottom": 8})()

    m = Here(4)
    assert m.touched(Update())
    assert not m.touched(Far())
    assert m.touched(Whole())


def test_typing_during_boot_waits_for_the_app(backend, tmp_path):  # noqa: F811
    """Enter used to reach a backend that wasn't connected yet, and that ended the app."""
    async def go():
        def opener():
            time.sleep(1.2)
            return cli.Client(backend["url"], backend["key"])

        app = AFH(None, None, str(tmp_path), home=backend["home"], opener=opener)
        async with app.run_test(size=(100, 32)) as pilot:
            await shows(pilot, "Starting AFH", 5)
            app.composer.box.focus()
            await pilot.press("h", "i", "enter")
            await until(pilot, lambda: app.scroller.query("#home"), what="the start screen")
            await pilot.pause(0.2)
            assert app.thread is None
            assert "hi" in app.composer.box.text
            app.exit()
        app.client.close()

    asyncio.run(asyncio.wait_for(go(), 60))


def test_what_is_asked_for_during_boot_waits_for_the_connection(backend, tmp_path):  # noqa: F811
    async def go():
        release = []

        def opener():
            while not release:
                time.sleep(0.02)
            return cli.Client(backend["url"], backend["key"])

        app = AFH(None, None, str(tmp_path), home=backend["home"], opener=opener)
        async with app.run_test(size=(100, 32)) as pilot:
            await shows(pilot, "Starting AFH", 5)
            asked = asyncio.ensure_future(app.get("/api/bootstrap"))
            await pilot.pause(0.2)
            assert not asked.done()
            release.append(True)
            assert await asyncio.wait_for(asked, 20)
            await until(pilot, lambda: app.scroller.query("#home"), what="the start screen")
            assert "Starting AFH" not in screen_text(app)
            app.exit()
        app.client.close()

    asyncio.run(asyncio.wait_for(go(), 60))


def test_a_mark_half_out_of_view_is_cut_to_what_shows(images):
    film = picture.Film(12, 4, "#181616")
    width, height, pixels = decoded(film.part(1, 2))
    assert (width, height) == (120, 36)
    assert len(pixels) == width * height
    whole = decoded(film.encoded(None))[2]
    assert all(pixels[x, y] == whole[x, y + 20] for x in range(0, 120, 7) for y in range(0, 36, 5))


def test_the_installers_film_matches_their_blocks():
    frames = gzip.decompress((ROOT / "website/install-mark.gz").read_bytes()).decode().split("\n")
    baked = re.search(r"\$markFrames = @\((.*?)\n    \)", (ROOT / "website/install.ps1").read_text(encoding="utf-8"), re.S)
    assert len(frames) == baked.group(1).count("'") // 2
    for frame in frames:
        width, height, pixels = decoded(frame)
        assert (width, height) == (240, 156)
        assert len(pixels) == width * height
    assert len(set(frames)) > 20


@pytest.mark.parametrize("name", ["install.ps1", "install.sh"])
def test_the_installers_keep_the_blocks_as_their_fallback(name):
    source = (ROOT / "website" / name).read_text(encoding="utf-8")
    assert "install-mark.gz" in source and "AFH_MARK_URL" in source
    assert ("Get-Mark $n" if name.endswith("ps1") else 'draw_mark "$n"') in source
