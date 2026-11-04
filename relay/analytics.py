"""Site analytics for the owner's admin page, read from nginx's access log of the website.

Nothing extra is collected: no cookies, no tracking script, no pings from the apps. Every few minutes
the relay reads the lines nginx added to the site's access log and keeps daily counts in
analytics.db, because the logs themselves rotate away after two weeks. People are counted by a
salted hash of address + browser; addresses are never stored.

What the log can tell:
- downloads of each installer (exe = Windows, apk = Android, ipa = iPhone), per version;
- Windows installs in use: the desktop app checks /downloads/latest.yml for updates (user agent
  "electron-builder"), so the distinct checkers per day are the desktop apps that were open;
- phones signed in to an account: the app asks /relay/api/me when it opens (user agent "Dart/...");
- website visitors, page views, the pages they read and the sites that sent them.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

LOG = Path(os.environ.get("AFH_ACCESS_LOG", "/var/log/nginx/afh-website.access.log"))
DB_PATH = Path(os.environ.get("AFH_ANALYTICS_DB", "/var/lib/afh-relay/analytics.db"))
OWN_HOSTS = {"agentflowharness.com", "www.agentflowharness.com"}

LINE = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) \S+ "([^"]*)" "([^"]*)"')
BOT = re.compile(r"bot|crawl|spider|slurp|curl|wget|python|go-http|httpx|okhttp|java/|headless|lighthouse|inspectiontool|"
                 r"preview|monitor|scan|fetch|axios|facebookexternalhit|semrush|ahrefs|dataprovider|zgrab|masscan", re.I)
DOWNLOAD = re.compile(r"^/downloads/AFH-(?:Setup|Remote)-(\d+(?:\.\d+)+)\.(exe|apk|ipa)$")
PLATFORM = {"exe": "windows", "apk": "android", "ipa": "ios"}
ASSET = re.compile(r"\.(?:css|js)$")
PAGE = re.compile(r"^/(?:[a-z0-9-]+(?:\.html)?)?$")
NOT_PAGES = {"/404", "/404.html", "/dashboard", "/dashboard.html", "/admin", "/admin.html", "/lab", "/lab.html", "/lab-sizes", "/lab-sizes.html"}


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS seen (
                day TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, who TEXT NOT NULL,
                PRIMARY KEY (day, kind, key, who)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)


def _state(con: sqlite3.Connection, name: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM state WHERE name = ?", (name,)).fetchone()
    return row["value"] if row else default


def _set_state(con: sqlite3.Connection, name: str, value: str) -> None:
    con.execute("INSERT INTO state VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (name, value))


# ---- reading the log ---------------------------------------------------------------------------


def classify(line: str, salt: str) -> list[tuple[str, str, str, str]]:
    """What one log line counts towards: (day, kind, key, who), each counted once per day."""
    m = LINE.match(line)
    if not m:
        return []
    ip, stamp, method, target, status, referer, agent = m.groups()
    if method != "GET":
        return []
    try:
        day = datetime.strptime(stamp, "%d/%b/%Y:%H:%M:%S %z").date().isoformat()
    except ValueError:
        return []
    path = urlsplit(target).path
    who = hashlib.sha256(f"{salt}|{ip}|{agent}".encode()).hexdigest()[:20]
    code = int(status)
    if path == "/downloads/latest.yml":
        return [(day, "desktop", "windows", who)] if agent.startswith("electron-builder") and code in (200, 304) else []
    if path == "/relay/api/me" and agent.startswith("Dart/"):
        return [(day, "phone", "app", who)] if code == 200 else []
    d = DOWNLOAD.match(path)
    if d:
        if code not in (200, 206) or BOT.search(agent):
            return []
        version, ext = d.groups()
        return [(day, "download", f"{PLATFORM[ext]} {version}", who)]
    if not agent.startswith("Mozilla/") or BOT.search(agent):
        return []
    # Most "browsers" asking for pages are scanners. A real one runs the page: it loads the styles
    # and scripts, and layout.js asks /relay/api/me. Only visitors that did count (see stats()).
    if path == "/relay/api/me" or (ASSET.search(path) and code in (200, 304)):
        return [(day, "browser", "site", who)]
    if code not in (200, 304):
        return []
    path = path.removesuffix(".html")
    path = "/" if path in ("/index", "") else path
    if not PAGE.match(path) or path in NOT_PAGES:
        return []
    out = [(day, "page", path, who)]
    host = (urlsplit(referer).hostname or "").lower() if referer not in ("", "-") else ""
    if host and host not in OWN_HOSTS:
        out.append((day, "ref", host.removeprefix("www."), who))
    return out


def ingest_lines(con: sqlite3.Connection, lines, salt: str) -> int:
    n = 0
    rows = set()
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        rows.update(classify(line, salt))
        n += 1
    con.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?,?)", list(rows))
    return n


def _read_from(path: Path, offset: int) -> tuple[list[bytes], int]:
    """Whole lines of `path` after `offset`, and the offset after the last whole line."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1
    return data[:end].splitlines(), offset + end


def ingest() -> int:
    """Read what nginx logged since the last call. The first call also takes in the rotated logs still on disk."""
    if not LOG.exists():
        return 0
    with db() as con:
        salt = _state(con, "salt")
        if not salt:
            salt = secrets.token_hex(16)
            _set_state(con, "salt", salt)
        con.execute("BEGIN IMMEDIATE")
        try:
            inode, offset = _state(con, "inode"), int(_state(con, "offset", "0"))
            st = LOG.stat()
            n = 0
            if not inode:  # first run: the history nginx still keeps, oldest first
                rotated = sorted(LOG.parent.glob(LOG.name + ".*"), key=lambda p: -int(p.name.split(".")[-2 if p.suffix == ".gz" else -1]))
                for p in rotated:
                    opener = gzip.open if p.suffix == ".gz" else open
                    with opener(p, "rb") as f:
                        n += ingest_lines(con, f, salt)
                offset = 0
            elif inode != str(st.st_ino):  # rotated: finish the old file (now .1), then start the new one
                old = LOG.with_name(LOG.name + ".1")
                if old.exists() and str(old.stat().st_ino) == inode:
                    lines, _ = _read_from(old, offset)
                    n += ingest_lines(con, lines, salt)
                offset = 0
            elif st.st_size < offset:  # truncated
                offset = 0
            lines, offset = _read_from(LOG, offset)
            n += ingest_lines(con, lines, salt)
            _set_state(con, "inode", str(st.st_ino))
            _set_state(con, "offset", str(offset))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return n


# ---- the numbers -------------------------------------------------------------------------------


def stats(days: int = 30, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    week = (today - timedelta(days=6)).isoformat()
    t = today.isoformat()
    with db() as con:
        def distinct(kind: str, start: str, key: str | None = None) -> int:
            q = "SELECT COUNT(DISTINCT who) FROM seen WHERE kind = ? AND day >= ?" + (" AND key = ?" if key else "")
            return con.execute(q, (kind, start, *([key] if key else []))).fetchone()[0]

        def daily(kind: str) -> dict[str, int]:
            return {r["day"]: r["n"] for r in con.execute("SELECT day, COUNT(DISTINCT who) AS n FROM seen WHERE kind = ? AND day >= ? GROUP BY day", (kind, since))}

        series = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        dl_rows = con.execute("SELECT day, key, COUNT(*) AS n FROM seen WHERE kind = 'download' GROUP BY day, key").fetchall()
        dl_total = {"windows": 0, "android": 0, "ios": 0}
        dl_versions: dict[str, int] = {}
        dl_daily = {d: {"windows": 0, "android": 0, "ios": 0} for d in series}
        for r in dl_rows:
            platform = r["key"].split(" ")[0]
            dl_total[platform] = dl_total.get(platform, 0) + r["n"]
            dl_versions[r["key"]] = dl_versions.get(r["key"], 0) + r["n"]
            if r["day"] in dl_daily:
                dl_daily[r["day"]][platform] += r["n"]
        desktop, phone = daily("desktop"), daily("phone")
        # website rows count only for visitors whose browser ran the page that day (see classify)
        real = "EXISTS (SELECT 1 FROM seen b WHERE b.day = s.day AND b.kind = 'browser' AND b.key = 'site' AND b.who = s.who)"
        site_daily = {r["day"]: r for r in con.execute(
            f"SELECT day, COUNT(DISTINCT who) AS visitors, COUNT(*) AS views FROM seen s WHERE kind = 'page' AND day >= ? AND {real} GROUP BY day", (since,))}

        def visitors(start: str) -> int:
            return con.execute(f"SELECT COUNT(DISTINCT who) FROM seen s WHERE kind = 'page' AND day >= ? AND {real}", (start,)).fetchone()[0]

        def top(kind: str, limit: int = 12) -> list[dict]:
            return [{"key": r["key"], "n": r["n"]} for r in con.execute(
                f"SELECT key, COUNT(*) AS n FROM seen s WHERE kind = ? AND day >= ? AND {real} GROUP BY key ORDER BY n DESC LIMIT ?", (kind, since, limit))]

        first = con.execute("SELECT MIN(day) FROM seen").fetchone()[0]
        return {
            "days": days, "today": t, "since": first, "updated": time.time(),
            "downloads": {
                "total": dl_total,
                "range": {p: sum(dl_daily[d][p] for d in series) for p in dl_total},
                "versions": [{"key": k, "n": n} for k, n in sorted(dl_versions.items(), key=lambda kv: -kv[1])],
                "daily": [{"day": d, **dl_daily[d]} for d in series],
            },
            "desktop": {"today": desktop.get(t, 0), "week": distinct("desktop", week), "range": distinct("desktop", since),
                        "daily": [{"day": d, "n": desktop.get(d, 0)} for d in series]},
            "phone": {"today": phone.get(t, 0), "week": distinct("phone", week), "range": distinct("phone", since),
                      "daily": [{"day": d, "n": phone.get(d, 0)} for d in series]},
            "site": {"today": site_daily[t]["visitors"] if t in site_daily else 0, "week": visitors(week), "range": visitors(since),
                     "views": sum(r["views"] for r in site_daily.values()),
                     "daily": [{"day": d, "visitors": site_daily[d]["visitors"] if d in site_daily else 0,
                                "views": site_daily[d]["views"] if d in site_daily else 0} for d in series],
                     "pages": top("page"), "referrers": top("ref")},
        }
