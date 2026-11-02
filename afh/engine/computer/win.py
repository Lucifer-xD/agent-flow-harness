"""The Windows side of computer use: screens, input, windows and apps, all through ctypes.

Coordinates here are physical pixels on the virtual desktop (the process is per-monitor DPI
aware), so a point means the same pixel for capture, input and window rectangles on every
monitor whatever its scale.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
version = ctypes.WinDLL("version")

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

_dpi_done = False


def init_dpi() -> None:
    """Per-monitor v2 DPI awareness, so every coordinate is a physical pixel. Once per process."""
    global _dpi_done
    if _dpi_done:
        return
    _dpi_done = True
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            pass


# ---- monitors ------------------------------------------------------------------------------


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


@dataclass
class Display:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool
    name: str

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def to_dict(self) -> dict:
        return {"index": self.index, "left": self.left, "top": self.top, "width": self.width, "height": self.height, "primary": self.primary, "name": self.name}


MonitorEnumProc = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)
user32.EnumDisplayMonitors.argtypes = [W.HDC, ctypes.c_void_p, MonitorEnumProc, W.LPARAM]
user32.GetMonitorInfoW.argtypes = [W.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]


def displays() -> list[Display]:
    init_dpi()
    found: list[Display] = []

    def cb(hmon, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(Display(0, r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.dwFlags & 1), info.szDevice))
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    found.sort(key=lambda d: (not d.primary, d.left, d.top))  # the primary display is 0
    for i, d in enumerate(found):
        d.index = i
    return found


def virtual_screen() -> tuple[int, int, int, int]:
    init_dpi()
    g = user32.GetSystemMetrics
    return g(76), g(77), g(78), g(79)  # x, y, width, height


def capture(rect: tuple[int, int, int, int]):
    """A PIL image of a screen rectangle (left, top, right, bottom). Windows that exclude
    themselves from capture (AFH's overlay) are not in it."""
    init_dpi()
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=rect, all_screens=True).convert("RGB")


# ---- input -----------------------------------------------------------------------------------


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [W.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = W.UINT
user32.MapVirtualKeyW.argtypes = [W.UINT, W.UINT]
user32.VkKeyScanW.argtypes = [W.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short

MOVE, LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP, MIDDLEDOWN, MIDDLEUP = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40
WHEEL, HWHEEL, VIRTUALDESK, ABSOLUTE = 0x800, 0x1000, 0x4000, 0x8000
KEYUP, UNICODE, EXTENDED, SCANCODE = 0x2, 0x4, 0x1, 0x8
BUTTONS = {"left": (LEFTDOWN, LEFTUP), "right": (RIGHTDOWN, RIGHTUP), "middle": (MIDDLEDOWN, MIDDLEUP)}

# Marks input AFH sends itself (dwExtraInfo), so apps and logs can tell it from the user's.
AFH_TAG = 0xAF4A


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError("Windows blocked the input (an elevated window or a secure screen like UAC is in front)")


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(0, _INPUTUNION(mi=MOUSEINPUT(dx, dy, ctypes.c_uint32(data).value, flags, 0, AFH_TAG)))


def _key(vk: int, up: bool = False) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = (KEYUP if up else 0) | (EXTENDED if vk in EXTENDED_VKS else 0)
    return INPUT(1, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, AFH_TAG)))


def _unicode(unit: int, up: bool = False) -> INPUT:
    return INPUT(1, _INPUTUNION(ki=KEYBDINPUT(0, unit, UNICODE | (KEYUP if up else 0), 0, AFH_TAG)))


def cursor_pos() -> tuple[int, int]:
    init_dpi()
    p = W.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_to(x: int, y: int) -> None:
    vx, vy, vw, vh = virtual_screen()
    nx = int(((x - vx) + 0.5) * 65536 / vw)
    ny = int(((y - vy) + 0.5) * 65536 / vh)
    _send(_mouse(MOVE | ABSOLUTE | VIRTUALDESK, nx, ny))
    if cursor_pos() != (x, y):  # rounding on odd layouts: put it exactly there
        user32.SetCursorPos(x, y)


def glide_to(x: int, y: int, duration: float = 0.22) -> None:
    """Move the pointer to (x, y) the way a hand does: quick at first, easing in at the end, so apps
    see the hover on the way and the user can follow it. Short hops jump straight there."""
    sx, sy = cursor_pos()
    dist = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
    if dist < 6 or duration <= 0:
        move_to(x, y)
        return
    duration = min(0.5, duration * (0.6 + min(dist, 1600) / 1600))
    steps = max(8, int(duration * 120))
    for i in range(1, steps + 1):
        t = i / steps
        e = 1 - (1 - t) ** 3  # ease-out cubic
        move_to(round(sx + (x - sx) * e), round(sy + (y - sy) * e))
        time.sleep(duration / steps)


def button(name: str, down: bool) -> None:
    d, u = BUTTONS[name]
    _send(_mouse(d if down else u))


def click(name: str = "left", count: int = 1, mods: list[int] | None = None) -> None:
    """Click `count` times (2 = double, 3 = triple), holding the modifier keys `mods` throughout."""
    d, u = BUTTONS[name]
    if mods:
        keys_down(mods)
    try:
        for i in range(count):
            _send(_mouse(d), _mouse(u))
            if i < count - 1:
                time.sleep(0.04)
    finally:
        if mods:
            keys_up(mods)


def wheel(dx: int, dy: int) -> None:
    """Scroll by notches: positive dy is up (away from the user), positive dx is right."""
    if dy:
        _send(_mouse(WHEEL, data=120 * dy))
    if dx:
        _send(_mouse(HWHEEL, data=120 * dx))


VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "option": 0x12, "pause": 0x13, "capslock": 0x14, "escape": 0x1B, "esc": 0x1B, "space": 0x20, "pageup": 0x21, "page_up": 0x21,
    "prior": 0x21, "pagedown": 0x22, "page_down": 0x22, "next": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28, "arrowleft": 0x25, "arrowup": 0x26, "arrowright": 0x27, "arrowdown": 0x28, "printscreen": 0x2C,
    "print": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E, "win": 0x5B, "windows": 0x5B, "super": 0x5B, "meta": 0x5B,
    "menu": 0x5D, "apps": 0x5D, "contextmenu": 0x5D, "numlock": 0x90, "scrolllock": 0x91,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplaypause": 0xB3,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{f"num{i}": 0x60 + i for i in range(10)}, **{f"numpad{i}": 0x60 + i for i in range(10)},
}
# On Windows, "cmd" from a Mac habit means Ctrl (Cmd+C → Ctrl+C).
VK["cmd"] = VK["command"] = VK["ctrl"]
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0xA3, 0xA5, 0x90, 0x2C}
MODIFIERS = {0x10, 0x11, 0x12, 0x5B, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def parse_combo(combo: str) -> list[int]:
    """'ctrl+shift+s' → virtual keys in press order. Raises ValueError on an unknown key."""
    parts = [p for p in combo.replace(" ", "").split("+") if p] if combo.strip() != "+" else ["+"]
    if not parts and "+" in combo:
        parts = ["+"]
    out: list[int] = []
    for p in parts:
        name = p.lower().replace("-", "_")
        if name in VK:
            out.append(VK[name])
        elif len(p) == 1:
            code = user32.VkKeyScanW(p)
            if code == -1:
                raise ValueError(f"'{p}' has no key on this keyboard layout; use the type action for it")
            vk, shift = code & 0xFF, (code >> 8) & 0xFF
            if shift & 1 and 0x10 not in out:
                out.append(0x10)
            if shift & 2 and 0x11 not in out:
                out.append(0x11)
            if shift & 4 and 0x12 not in out:
                out.append(0x12)
            out.append(vk)
        else:
            raise ValueError(f"Unknown key '{p}'. Use names like ctrl, shift, alt, win, enter, tab, escape, f5, pageup, or single characters.")
    return out


def _mark_esc(vks: list[int]) -> None:
    global _injected_esc_until
    if 0x1B in vks:
        _injected_esc_until = time.time() + 0.4


def press_combo(vks: list[int]) -> None:
    _mark_esc(vks)
    _send(*[_key(v) for v in vks], *[_key(v, up=True) for v in reversed(vks)])


def keys_down(vks: list[int]) -> None:
    _mark_esc(vks)
    _send(*[_key(v) for v in vks])


def keys_up(vks: list[int]) -> None:
    _mark_esc(vks)
    _send(*[_key(v, up=True) for v in reversed(vks)])


def type_text(text: str, per_key: float = 0.012) -> None:
    """Types any text as Unicode keystrokes; newlines press Enter and tabs press Tab. One key at a
    time with a short gap: modern apps (the Windows 11 Notepad, WinUI text boxes) drop or garble
    keystrokes that arrive in one burst."""
    for ch in text.replace("\r\n", "\n"):
        if ch in "\n\r":
            _send(_key(0x0D), _key(0x0D, True))
        elif ch == "\t":
            _send(_key(0x09), _key(0x09, True))
        else:
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "little")
                _send(_unicode(unit), _unicode(unit, True))
        time.sleep(per_key)


TEXT_FORMATS = {1, 7, 13, 16}  # CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE


def clipboard_is_text_only() -> bool:
    """True when the clipboard holds nothing or only text, so it can be put back exactly after a paste."""
    _open_clipboard()
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                return True
            if fmt not in TEXT_FORMATS:
                return False
    finally:
        user32.CloseClipboard()


def paste_text(text: str) -> bool:
    """Types long text in one go: put it on the clipboard, press Ctrl+V, then put back what the
    clipboard held. Returns False (nothing done) when the clipboard holds more than text (an image,
    files), which a paste would lose."""
    if not clipboard_is_text_only():
        return False
    old = read_clipboard()
    write_clipboard(text.replace("\r\n", "\n").replace("\n", "\r\n"))
    time.sleep(0.06)
    press_combo([0x11, 0x56])  # Ctrl+V
    time.sleep(0.35)  # let the app read the clipboard before it changes back
    if old:
        write_clipboard(old)
    else:
        _open_clipboard()
        try:
            user32.EmptyClipboard()
        finally:
            user32.CloseClipboard()
    return True


# ---- windows and processes ------------------------------------------------------------------

EnumWindowsProc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, W.LPARAM]
user32.EnumChildWindows.argtypes = [W.HWND, EnumWindowsProc, W.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.WindowFromPoint.argtypes = [W.POINT]
user32.WindowFromPoint.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
user32.GetAncestor.restype = W.HWND
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowDisplayAffinity.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsIconic.argtypes = [W.HWND]
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
user32.BringWindowToTop.argtypes = [W.HWND]
dwmapi.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
kernel32.CloseHandle.argtypes = [W.HANDLE]
try:
    kernel32.GetApplicationUserModelId.argtypes = [W.HANDLE, ctypes.POINTER(ctypes.c_uint32), W.LPWSTR]
except AttributeError:  # older Windows
    pass

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x20, 0x80, 0x08000000


@dataclass
class Window:
    hwnd: int
    pid: int
    exe: str  # full path ("" when Windows won't say)
    title: str
    cls: str
    rect: tuple[int, int, int, int]
    aumid: str = ""  # packaged (Store) apps
    tool: bool = False  # a tool window (menus, tooltips, palettes) rather than an app window

    @property
    def exe_name(self) -> str:
        return os.path.basename(self.exe).lower() if self.exe else ""


_exe_cache: dict[int, tuple[str, str, float]] = {}


def process_info(pid: int) -> tuple[str, str]:
    """(exe path, AppUserModelID) of a process, cached for a minute."""
    hit = _exe_cache.get(pid)
    if hit and time.time() - hit[2] < 60:
        return hit[0], hit[1]
    exe, aumid = "", ""
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = W.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                exe = buf.value
            if hasattr(kernel32, "GetApplicationUserModelId"):
                ln = ctypes.c_uint32(256)
                ab = ctypes.create_unicode_buffer(256)
                if kernel32.GetApplicationUserModelId(h, ctypes.byref(ln), ab) == 0:
                    aumid = ab.value
        finally:
            kernel32.CloseHandle(h)
    _exe_cache[pid] = (exe, aumid, time.time())
    return exe, aumid


def _pid(hwnd) -> int:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _text(fn, hwnd, n=512) -> str:
    buf = ctypes.create_unicode_buffer(n)
    fn(hwnd, buf, n)
    return buf.value


def _frame(hwnd) -> tuple[int, int, int, int]:
    r = W.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # DWMWA_EXTENDED_FRAME_BOUNDS
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _cloaked(hwnd) -> bool:
    v = W.DWORD()
    return dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v)) == 0 and v.value != 0


def describe(hwnd) -> Window | None:
    if not hwnd:
        return None
    pid = _pid(hwnd)
    exe, aumid = process_info(pid)
    cls = _text(user32.GetClassNameW, hwnd, 256)
    if os.path.basename(exe).lower() == "applicationframehost.exe":  # a Store app's frame: find the app inside
        inner: list[int] = []

        def cb(child, _):
            if _pid(child) != pid:
                inner.append(child)
                return False
            return True

        user32.EnumChildWindows(hwnd, EnumWindowsProc(cb), 0)
        if inner:
            pid = _pid(inner[0])
            exe, aumid = process_info(pid)
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    return Window(int(hwnd), pid, exe, _text(user32.GetWindowTextW, hwnd), cls, _frame(hwnd), aumid, bool(ex & WS_EX_TOOLWINDOW))


def windows() -> list[Window]:
    """Visible top-level windows on screen, topmost first. Skips windows that are cloaked (other
    virtual desktops, suspended Store apps), minimized, click-through overlays and windows that
    keep themselves out of screen capture (AFH's own overlay)."""
    init_dpi()
    out: list[Window] = []

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or _cloaked(hwnd):
                return True
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if ex & WS_EX_TRANSPARENT:
                return True
            aff = W.DWORD()
            if user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(aff)) and aff.value:
                return True
            w = describe(hwnd)
            if w and w.rect[2] - w.rect[0] > 1 and w.rect[3] - w.rect[1] > 1:
                out.append(w)
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def window_at(x: int, y: int) -> Window | None:
    """The top-level window under a point. AFH's overlay can catch the mouse for a moment (its Stop
    button, a lesson tooltip), so a hit on a window that hides from capture looks past it."""
    init_dpi()
    hwnd = user32.WindowFromPoint(W.POINT(x, y))
    root = user32.GetAncestor(hwnd, 2) if hwnd else None  # GA_ROOT
    root = root or hwnd
    aff = W.DWORD()
    if root and user32.GetWindowDisplayAffinity(root, ctypes.byref(aff)) and aff.value:
        return next((w for w in windows() if w.rect[0] <= x < w.rect[2] and w.rect[1] <= y < w.rect[3]), None)
    return describe(root)


def display_at(x: int, y: int) -> Display | None:
    return next((d for d in displays() if d.left <= x < d.left + d.width and d.top <= y < d.top + d.height), None)


def foreground() -> Window | None:
    init_dpi()
    return describe(user32.GetForegroundWindow())


user32.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]


def focus_window(hwnd: int) -> bool:
    """Bring a window to the front. Windows only lets the foreground app hand over the focus, so
    first borrow the foreground thread's input state; only if that fails, tap Alt (it can open the
    menu bar of the window in front, so never when the window is already there)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    if fg and int(fg) == int(hwnd):
        return True
    me = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(other and other != me and user32.AttachThreadInput(me, other, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, other, False)
    if not ok:
        press_combo([0x12])  # goes to the old window, which drops any menu mode once it loses the focus
        ok = bool(user32.SetForegroundWindow(hwnd))
    time.sleep(0.05)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd) or ok


# ---- app names and installed apps -------------------------------------------------------------

version.GetFileVersionInfoSizeW.argtypes = [W.LPCWSTR, ctypes.POINTER(W.DWORD)]
version.GetFileVersionInfoW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p]
version.VerQueryValueW.argtypes = [ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(W.UINT)]
_desc_cache: dict[str, str] = {}


def file_description(exe: str) -> str:
    """The name an exe calls itself ("Google Chrome", "Notepad"), from its version info."""
    if not exe:
        return ""
    if exe in _desc_cache:
        return _desc_cache[exe]
    name = ""
    try:
        size = version.GetFileVersionInfoSizeW(exe, None)
        if size:
            data = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(exe, 0, size, data):
                ptr, ln = ctypes.c_void_p(), W.UINT()
                langs = []
                if version.VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value >= 4:
                    arr = ctypes.cast(ptr, ctypes.POINTER(W.WORD * (ln.value // 2))).contents
                    langs = [f"{arr[i]:04x}{arr[i + 1]:04x}" for i in range(0, len(arr) - 1, 2)]
                for lang in [*langs, "040904b0", "040904e4", "000004b0"]:
                    for key in ("FileDescription", "ProductName"):
                        if version.VerQueryValueW(data, f"\\StringFileInfo\\{lang}\\{key}", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value > 1:
                            name = ctypes.wstring_at(ptr, ln.value - 1).strip()
                            if name:
                                break
                    if name:
                        break
    except Exception:
        name = ""
    _desc_cache[exe] = name
    return name


_start_cache: tuple[float, list[dict]] = (0.0, [])


def start_apps() -> list[dict]:
    """Apps in the Start menu: [{name, id}] where id is the AppUserModelID (Store and desktop apps
    alike). `explorer shell:AppsFolder\\<id>` launches any of them. Cached for two minutes."""
    global _start_cache
    if time.time() - _start_cache[0] < 120 and _start_cache[1]:
        return _start_cache[1]
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        items = json.loads(out.stdout.decode("utf-8", errors="replace") or "[]")
        if isinstance(items, dict):
            items = [items]
        apps = [{"name": str(i.get("Name") or ""), "id": str(i.get("AppID") or "")} for i in items if i.get("Name") and i.get("AppID")]
    except Exception:
        apps = []
    _start_cache = (time.time(), apps)
    return apps


_KNOWN_FOLDERS = {
    "{6D809377-6AF0-444B-8957-A3773F02200E}": os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files"),
    "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": os.environ.get("SystemRoot", r"C:\Windows"),
}


def start_app_exe(app_id: str) -> str:
    """The exe behind a Start menu id when it names one ("{known folder}\\app\\x.exe" or a path)."""
    if not app_id.lower().endswith(".exe"):
        return ""
    for guid, base in _KNOWN_FOLDERS.items():
        if app_id.upper().startswith(guid):
            return os.path.join(base, app_id[len(guid):].lstrip("\\"))
    return app_id


def launch(app_id: str = "", path: str = "") -> None:
    flags = subprocess.CREATE_NO_WINDOW
    if path:
        os.startfile(path)  # noqa: S606 - the user approved this app
    else:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=flags)


# ---- clipboard ---------------------------------------------------------------------------------

user32.OpenClipboard.argtypes = [W.HWND]
user32.EnumClipboardFormats.argtypes = [W.UINT]
user32.EnumClipboardFormats.restype = W.UINT
user32.GetClipboardData.argtypes = [W.UINT]
user32.GetClipboardData.restype = W.HANDLE
user32.SetClipboardData.argtypes = [W.UINT, W.HANDLE]
user32.SetClipboardData.restype = W.HANDLE
kernel32.GlobalLock.argtypes = [W.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [W.HGLOBAL]
kernel32.GlobalAlloc.argtypes = [W.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = W.HGLOBAL


def _open_clipboard() -> None:
    for _ in range(20):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("The clipboard is busy (another app has it open)")


def read_clipboard() -> str:
    _open_clipboard()
    try:
        h = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def write_clipboard(text: str) -> None:
    data = (text + "\0").encode("utf-16-le")
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(13, h):
            raise OSError("Couldn't put the text on the clipboard")
    finally:
        user32.CloseClipboard()


# ---- the user taking over -------------------------------------------------------------------------

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def escape_pressed() -> bool:
    """True if Esc is down right now (a fallback for when the keyboard hook can't be installed)."""
    return bool(user32.GetAsyncKeyState(0x1B) & 0x8000)


_injected_esc_until = 0.0  # while AFH itself holds Esc down, the watch ignores it


class EscWatch:
    """Calls `on_escape()` when the user presses Esc, while a computer task runs.

    It checks the Esc key's state every few milliseconds (nothing else on the keyboard is looked
    at), and ignores the moments when AFH presses Esc itself, so closing a menu never stops a task."""

    def __init__(self, on_escape):
        import threading

        self.on_escape = on_escape
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        import threading

        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="afh-esc-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        was_down = escape_pressed()
        while not self._stop.is_set():
            down = escape_pressed()
            if down and not was_down and time.time() > _injected_esc_until:
                try:
                    self.on_escape()
                except Exception:
                    pass
            was_down = down
            self._stop.wait(0.03)


# ---- app icons ------------------------------------------------------------------------------------


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD), ("biBitCount", W.WORD),
                ("biCompression", W.DWORD), ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateCompatibleDC.argtypes = [W.HDC]
gdi32.CreateCompatibleDC.restype = W.HDC
gdi32.CreateDIBSection.argtypes = [W.HDC, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.DWORD]
gdi32.CreateDIBSection.restype = W.HBITMAP
gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi32.SelectObject.restype = W.HGDIOBJ
gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
gdi32.DeleteDC.argtypes = [W.HDC]
user32.PrivateExtractIconsW.argtypes = [W.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(W.HICON),
                                        ctypes.POINTER(W.UINT), W.UINT, W.UINT]
user32.DrawIconEx.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, W.HICON, ctypes.c_int, ctypes.c_int, W.UINT, W.HBRUSH, W.UINT]
user32.DestroyIcon.argtypes = [W.HICON]
_icon_cache: dict[tuple[str, int], bytes | None] = {}


def exe_icon_png(path: str, size: int = 64) -> bytes | None:
    """An exe's own icon as PNG bytes (None when it has none), for the app approval cards."""
    key = (path.lower(), size)
    if key in _icon_cache:
        return _icon_cache[key]
    png = None
    hicon = W.HICON()
    try:
        if path and os.path.isfile(path) and user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(hicon), None, 1, 0) > 0 and hicon:
            from PIL import Image
            import io

            hdc = gdi32.CreateCompatibleDC(None)
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            old = gdi32.SelectObject(hdc, hbmp)
            user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 3)  # DI_NORMAL
            raw = ctypes.string_at(bits, size * size * 4)
            gdi32.SelectObject(hdc, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc)
            img = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1)
            if not img.getchannel("A").getbbox():  # an old icon without alpha: opaque wherever it drew
                img.putalpha(img.convert("L").point(lambda v: 255 if v else 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
    except Exception:
        png = None
    finally:
        if hicon:
            user32.DestroyIcon(hicon)
    _icon_cache[key] = png
    return png


def any_mouse_button_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))  # L/R/M


def is_supported() -> bool:
    return os.name == "nt"

