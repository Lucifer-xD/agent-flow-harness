"""Which app a window belongs to, how much the agent may do in it, and the user's approvals.

Tiers (the most the agent may do in an app, even once it is approved):
- full: see, click, type, press keys, drag;
- click: see, left-click and scroll — terminals and code editors, where typing could run commands
  outside the thread's approval rules;
- read: see only — web browsers (the agent has its own `browser` tool; Settings can lift this).
Some apps are never available: AFH itself (so the agent can't approve its own requests), Windows
security and sign-in screens, and password managers.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe", "vivaldi.exe", "arc.exe", "iexplore.exe",
            "librewolf.exe", "waterfox.exe", "chromium.exe", "thorium.exe", "zen.exe", "floorp.exe", "yandex.exe", "duckduckgo.exe"}
CLICK_ONLY = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe", "openconsole.exe", "mintty.exe",
              "alacritty.exe", "wezterm-gui.exe", "hyper.exe", "tabby.exe", "warp.exe", "code.exe", "code - insiders.exe", "cursor.exe",
              "windsurf.exe", "devenv.exe", "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "clion64.exe", "goland64.exe",
              "phpstorm64.exe", "rubymine64.exe", "datagrip64.exe", "studio64.exe", "zed.exe", "sublime_text.exe", "fleet.exe", "bash.exe",
              "wsl.exe", "putty.exe", "mobaxterm.exe", "kitty.exe"}
NEVER = {"agent flow harness.exe", "afh-backend.exe", "consent.exe", "credentialuibroker.exe", "logonui.exe", "lockapp.exe",
         "securityhealthsystray.exe", "securityhealthhost.exe", "useraccountcontrolsettings.exe", "1password.exe", "bitwarden.exe",
         "keepass.exe", "keepassxc.exe", "dashlane.exe", "lastpass.exe", "nordpass.exe", "enpass.exe", "proton pass.exe", "roboform.exe",
         "keeper password manager.exe", "claude.exe", "chatgpt.exe", "codex.exe"}
# Parts of Windows itself that the user would call "the taskbar" or "the desktop".
SHELL = {"explorer.exe", "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe", "textinputhost.exe",
         "shellhost.exe", "applicationframehost.exe"}
SHELL_ID = "windows-shell"
SHELL_NAME = "File Explorer, the desktop and taskbar"
# Common names people use → the exe, for apps whose Start menu entry doesn't name one.
ALIASES = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe", "microsoft edge": "msedge.exe", "firefox": "firefox.exe",
    "word": "winword.exe", "microsoft word": "winword.exe", "excel": "excel.exe", "microsoft excel": "excel.exe",
    "powerpoint": "powerpnt.exe", "outlook": "outlook.exe", "onenote": "onenote.exe", "teams": "ms-teams.exe", "vs code": "code.exe",
    "vscode": "code.exe", "visual studio code": "code.exe", "notepad": "notepad.exe", "paint": "mspaint.exe", "calculator": "calculatorapp.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe", "terminal": "windowsterminal.exe",
    "windows terminal": "windowsterminal.exe", "settings": "systemsettings.exe", "task manager": "taskmgr.exe", "spotify": "spotify.exe",
    "discord": "discord.exe", "slack": "slack.exe", "telegram": "telegram.exe", "whatsapp": "whatsapp.exe", "steam": "steam.exe",
    "obs": "obs64.exe", "zoom": "zoom.exe", "photos": "photos.exe", "snipping tool": "snippingtool.exe", "blender": "blender.exe",
    "photoshop": "photoshop.exe", "figma": "figma.exe", "notion": "notion.exe", "obsidian": "obsidian.exe", "vlc": "vlc.exe",
}
TIER_RANK = {"read": 0, "click": 1, "full": 2}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def tier_for(exe_name: str, settings: dict | None = None) -> str:
    cfg = (settings or {}).get("computer") or {}
    if exe_name in BROWSERS:
        return "full" if cfg.get("browserControl") else "read"
    if exe_name in CLICK_ONLY:
        return "click"
    return "full"


def never(exe_name: str, exe_path: str = "") -> bool:
    if exe_name in NEVER:
        return True
    # AFH running from source (electron.exe in desktop/node_modules) is AFH too
    p = exe_path.replace("\\", "/").lower()
    return exe_name == "electron.exe" and "/desktop/node_modules/" in p


@dataclass
class App:
    """One app the user may approve: matched by exe name and/or AppUserModelID (Store apps)."""
    id: str
    name: str
    exes: list[str] = field(default_factory=list)  # lowercase exe names
    aumid: str = ""
    path: str = ""  # an exe to show the icon of and to launch
    tier: str = "full"

    def matches(self, exe_name: str, aumid: str = "") -> bool:
        if self.id == SHELL_ID:
            return exe_name in SHELL
        return (bool(exe_name) and exe_name in self.exes) or (bool(aumid) and aumid == self.aumid)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "exes": self.exes, "aumid": self.aumid, "path": self.path, "tier": self.tier}

    @classmethod
    def from_dict(cls, d: dict) -> "App":
        return cls(str(d.get("id") or ""), str(d.get("name") or d.get("id") or ""), [str(e).lower() for e in d.get("exes") or []],
                   str(d.get("aumid") or ""), str(d.get("path") or ""), str(d.get("tier") or "full"))


def shell_app() -> App:
    return App(SHELL_ID, SHELL_NAME, sorted(SHELL), "", os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe"), "full")


def app_for_window(w, describe_exe) -> App:
    """The App a window belongs to (named the way the exe names itself)."""
    if w.exe_name in SHELL:
        return shell_app()
    name = describe_exe(w.exe) or (os.path.splitext(os.path.basename(w.exe))[0] if w.exe else w.title or "Unknown app")
    return App(w.aumid or w.exe_name or name.lower(), name, [w.exe_name] if w.exe_name else [], w.aumid, w.exe)


def resolve(query: str, running: list[App], start: list[dict], start_exe) -> App | None:
    """An app the model named ("Notepad", "chrome", "Spotify.exe", a path) → App, preferring open apps."""
    q = norm(query.removesuffix(".exe").removesuffix(".EXE"))
    if not q:
        return None
    if q in ("desktop", "taskbar", "start menu", "windows shell", "file explorer", "explorer", "files", norm(SHELL_NAME)):
        return shell_app()
    if os.path.isabs(query) and query.lower().endswith(".exe") and os.path.isfile(query):
        exe = os.path.basename(query).lower()
        return App(exe, os.path.splitext(os.path.basename(query))[0], [exe], "", query)
    alias = ALIASES.get(q)

    def score(names: list[str]) -> int:
        best = 0
        for n in names:
            n = norm(n)
            if not n:
                continue
            if n == q:
                best = max(best, 3)
            elif n.startswith(q) or q.startswith(n):
                best = max(best, 2)
            elif q in n.split() or all(t in n.split() for t in q.split()):
                best = max(best, 1)
        return best

    ranked = sorted(((score([a.name, *(e.removesuffix(".exe") for e in a.exes)]) + (2 if alias and alias in a.exes else 0), a) for a in running),
                    key=lambda x: -x[0])
    if ranked and ranked[0][0] >= 2:
        return ranked[0][1]
    best_start = max(start, key=lambda s: score([s["name"]]), default=None)
    if best_start and score([best_start["name"]]) >= 1 and (not ranked or score([best_start["name"]]) >= ranked[0][0]):
        exe_path = start_exe(best_start["id"])
        exe = os.path.basename(exe_path).lower() if exe_path else (alias or "")
        aumid = best_start["id"] if "!" in best_start["id"] or not exe_path else ""
        guessed = [exe] if exe else []
        if not guessed:  # a desktop app with a registered id ("Chrome"): guess its exe from the name
            stem = norm(best_start["name"]).replace(" ", "")
            guessed = [ALIASES.get(norm(best_start["name"]), f"{stem}.exe")]
        return App(aumid or guessed[0], best_start["name"], guessed, aumid, exe_path, "full") if guessed or aumid else None
    if ranked and ranked[0][0] >= 1:
        return ranked[0][1]
    if alias:
        return App(alias, query.strip(), [alias], "", "")
    return None
