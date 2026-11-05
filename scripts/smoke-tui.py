"""Does the terminal app start from a build? Runs it under a real pseudo-terminal where the system has one.

    python scripts/smoke-tui.py <path to afh>

On Mac and Linux it opens the app in a pty, waits for the message box, and quits with Ctrl+C twice. Windows
has no pty in the standard library, so there it starts the app with Textual's headless driver.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


WORDS = b"sk anything"  # the cursor sits on the A, so the box's first letter arrives apart from the rest


def posix(exe: str) -> int:
    import fcntl
    import pty
    import select
    import struct
    import termios

    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execv(exe, [exe])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
    seen = b""
    end = time.time() + 90
    while time.time() < end and b"Ask anything" not in seen.replace(b"\x1b", b""):
        ready, _, _ = select.select([fd], [], [], 1)
        if ready:
            try:
                seen += os.read(fd, 65536)
            except OSError:
                break
    ok = WORDS in seen
    os.write(fd, b"\x03")
    time.sleep(0.4)
    os.write(fd, b"\x03")
    end = time.time() + 20
    while time.time() < end:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            print("started and quit" if ok else seen[-2000:].decode("utf-8", "replace"))
            return 0 if ok and os.waitstatus_to_exitcode(status) == 0 else 1
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                os.read(fd, 65536)
            except OSError:
                pass
    os.kill(pid, 9)
    print("started but didn't quit" if ok else "didn't start")
    return 1


def windows(exe: str) -> int:
    out = subprocess.run([exe, "--tui-check"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    print(out.stdout[-2000:], out.stderr[-2000:])
    return out.returncode


if __name__ == "__main__":
    sys.exit(windows(sys.argv[1]) if os.name == "nt" else posix(sys.argv[1]))
