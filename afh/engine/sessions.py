"""Session storage: SQLite under the AFH data dir. Messages are stored as JSON in the same
shape the UI renders, so the API hands them over untouched."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .types import new_id, now_ms

SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
  id TEXT PRIMARY KEY, directory TEXT NOT NULL, title TEXT, parent_id TEXT, agent TEXT, model TEXT,
  permissions TEXT, metadata TEXT, archived INTEGER DEFAULT 0, tokens TEXT, cost REAL DEFAULT 0,
  created INTEGER NOT NULL, updated INTEGER NOT NULL, idle INTEGER
);
CREATE INDEX IF NOT EXISTS session_dir ON session(directory, updated);
CREATE TABLE IF NOT EXISTS message (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL,
  created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS message_session ON message(session_id, seq);
CREATE TABLE IF NOT EXISTS snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, message_id TEXT NOT NULL, seq INTEGER NOT NULL,
  path TEXT NOT NULL, existed INTEGER NOT NULL, content BLOB, created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshot_session ON snapshot(session_id, seq);
"""


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Rows(list):
    """A query's rows, already fetched."""

    def fetchone(self) -> Any:
        return self[0] if self else None

    def fetchall(self) -> list:
        return list(self)


class Shared:
    """One connection for every thread. They would also share its prepared statements, so two running the same query
    at once get each other's results, or SQLite's "API misuse". Here each query runs alone and has its rows before the next."""

    def __init__(self, db: sqlite3.Connection, lock: Any):
        self.db, self.lock = db, lock

    def execute(self, sql: str, args: Any = ()) -> Rows:
        with self.lock:
            return Rows(self.db.execute(sql, args).fetchall())

    def executescript(self, sql: str) -> None:
        with self.lock:
            self.db.executescript(sql)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db = Shared(db, self.lock)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(session)")}
        if "project" not in cols:  # 1.4: a worktree thread lives in another folder but belongs to its project
            self.db.execute("ALTER TABLE session ADD COLUMN project TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS message_created ON message(type, created)")

    # ---- sessions ---------------------------------------------------------------------

    def create_session(self, directory: str, *, title: str | None = None, agent: str | None = None, model: dict | None = None,
                       permissions: list | None = None, metadata: dict | None = None, parent_id: str | None = None, id: str | None = None,
                       project: str | None = None) -> dict:
        sid = id or new_id("ses")
        t = now_ms()
        with self.lock:
            self.db.execute(
                "INSERT INTO session(id, directory, title, parent_id, agent, model, permissions, metadata, created, updated, project) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, directory, title, parent_id, agent, _j(model) if model else None, _j(permissions or []), _j(metadata or {}), t, t, project if project and project != directory else None),
            )
        return self.get_session(sid)

    def get_session(self, sid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        return self._session(row) if row else None

    def list_sessions(self, directory: str | None = None, *, archived: bool = False, parent_id: str | None = None, limit: int = 200, search: str | None = None) -> list[dict]:
        q = "SELECT * FROM session WHERE archived=?"
        args: list[Any] = [1 if archived else 0]
        if parent_id is not None:
            q += " AND parent_id=?"
            args.append(parent_id)
        else:
            q += " AND parent_id IS NULL"
        if directory:
            q += " AND COALESCE(project, directory)=?"
            args.append(directory)
        if search:
            q += " AND title LIKE ?"
            args.append(f"%{search}%")
        q += " ORDER BY updated DESC LIMIT ?"
        args.append(limit)
        return [self._session(r) for r in self.db.execute(q, args)]

    def update_session(self, sid: str, **fields: Any) -> dict | None:
        cols = []
        args: list[Any] = []
        for k, v in fields.items():
            if k in ("model", "permissions", "metadata", "tokens"):
                v = _j(v) if v is not None else None
            if k == "archived":
                v = 1 if v else 0
            cols.append(f"{k}=?")
            args.append(v)
        if "updated" not in fields:
            cols.append("updated=?")
            args.append(now_ms())
        args.append(sid)
        with self.lock:
            self.db.execute(f"UPDATE session SET {', '.join(cols)} WHERE id=?", args)
        return self.get_session(sid)

    def touch(self, sid: str, *, idle: bool = False) -> None:
        t = now_ms()
        with self.lock:
            self.db.execute("UPDATE session SET updated=?, idle=? WHERE id=?", (t, t if idle else None, sid))

    def unfinished_sessions(self, since_ms: int) -> list[str]:
        """Threads whose last run started after `since_ms` and never finished (idle is set when a run ends)."""
        rows = self.db.execute("SELECT id FROM session WHERE idle IS NULL AND archived=0 AND parent_id IS NULL AND updated>=? ORDER BY updated DESC", (since_ms,))
        return [r["id"] for r in rows]

    def delete_session(self, sid: str) -> None:
        with self.lock:
            for child in self.list_sessions(parent_id=sid, limit=1000):
                self.delete_session(child["id"])
            self.db.execute("DELETE FROM message WHERE session_id=?", (sid,))
            self.db.execute("DELETE FROM snapshot WHERE session_id=?", (sid,))
            self.db.execute("DELETE FROM session WHERE id=?", (sid,))

    def _session(self, r: sqlite3.Row) -> dict:
        tokens = json.loads(r["tokens"]) if r["tokens"] else {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        out = {
            "id": r["id"], "title": r["title"], "agent": r["agent"], "model": json.loads(r["model"]) if r["model"] else None,
            "permissions": json.loads(r["permissions"] or "[]"), "metadata": json.loads(r["metadata"] or "{}"), "archived": bool(r["archived"]),
            "tokens": tokens, "cost": r["cost"] or 0.0, "location": {"directory": r["directory"]}, "projectID": r["project"] or r["directory"],
            "project": r["project"] or r["directory"],
            "time": {"created": r["created"], "updated": r["updated"], **({"idle": r["idle"]} if r["idle"] else {})},
        }
        if r["parent_id"]:
            out["parentID"] = r["parent_id"]
        return out

    # ---- usage ------------------------------------------------------------------------

    def cost_since(self, since_ms: int) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(json_extract(data, '$.cost')), 0) FROM message WHERE type='assistant' AND created>=?", (since_ms,)).fetchone()
        return float(row[0] or 0)

    def usage_rows(self, since_ms: int) -> list[dict]:
        """One row per model step since a time, without loading the (possibly huge) messages."""
        q = """SELECT m.created, m.session_id, json_extract(m.data, '$.model.providerID') AS provider, json_extract(m.data, '$.model.id') AS model,
                      COALESCE(json_extract(m.data, '$.tokens.input'), 0) AS input, COALESCE(json_extract(m.data, '$.tokens.output'), 0) AS output,
                      COALESCE(json_extract(m.data, '$.tokens.reasoning'), 0) AS reasoning, COALESCE(json_extract(m.data, '$.tokens.cache.read'), 0) AS cache_read,
                      COALESCE(json_extract(m.data, '$.tokens.cache.write'), 0) AS cache_write, json_extract(m.data, '$.cost') AS cost
               FROM message m WHERE m.type='assistant' AND m.created>=? AND json_extract(m.data, '$.tokens') IS NOT NULL ORDER BY m.created"""
        return [dict(r) for r in self.db.execute(q, (since_ms,))]

    # ---- messages ---------------------------------------------------------------------

    def add_message(self, sid: str, msg: dict) -> dict:
        msg.setdefault("id", new_id("msg"))
        msg.setdefault("time", {"created": now_ms()})
        with self.lock:
            seq = (self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM message WHERE session_id=?", (sid,)).fetchone()[0] or 0) + 1
            self.db.execute("INSERT INTO message(id, session_id, seq, type, data, created) VALUES (?,?,?,?,?,?)",
                            (msg["id"], sid, seq, msg.get("type", "user"), _j(msg), msg["time"].get("created", now_ms())))
            self.db.execute("UPDATE session SET updated=? WHERE id=?", (now_ms(), sid))
        return msg

    def insert_before(self, sid: str, before_id: str, msg: dict) -> dict:
        """Insert a message just before another one (later messages and their undo snapshots move up one)."""
        msg.setdefault("id", new_id("msg"))
        msg.setdefault("time", {"created": now_ms()})
        with self.lock:
            seq = self.message_seq(sid, before_id)
            if seq is None:
                return self.add_message(sid, msg)
            # two steps so the (session, seq) order never collides mid-update
            self.db.execute("UPDATE message SET seq=-(seq+1) WHERE session_id=? AND seq>=?", (sid, seq))
            self.db.execute("UPDATE message SET seq=-seq WHERE session_id=? AND seq<0", (sid,))
            self.db.execute("UPDATE snapshot SET seq=seq+1 WHERE session_id=? AND seq>=?", (sid, seq))
            self.db.execute("INSERT INTO message(id, session_id, seq, type, data, created) VALUES (?,?,?,?,?,?)",
                            (msg["id"], sid, seq, msg.get("type", "user"), _j(msg), msg["time"].get("created", now_ms())))
        return msg

    def save_message(self, sid: str, msg: dict) -> None:
        with self.lock:
            self.db.execute("UPDATE message SET data=?, type=? WHERE id=? AND session_id=?", (_j(msg), msg.get("type", "user"), msg["id"], sid))

    def list_messages(self, sid: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute("SELECT data FROM message WHERE session_id=? ORDER BY seq", (sid,))]

    def message_seq(self, sid: str, mid: str) -> int | None:
        row = self.db.execute("SELECT seq FROM message WHERE session_id=? AND id=?", (sid, mid)).fetchone()
        return row["seq"] if row else None

    def messages_from(self, sid: str, seq: int) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute("SELECT data FROM message WHERE session_id=? AND seq>=? ORDER BY seq", (sid, seq))]

    def delete_messages_from(self, sid: str, seq: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM message WHERE session_id=? AND seq>=?", (sid, seq))
            self.db.execute("DELETE FROM snapshot WHERE session_id=? AND seq>=?", (sid, seq))

    def replace_messages(self, sid: str, messages: list[dict]) -> None:
        """Context editing: rewrite the whole history. Undo snapshots follow the messages that
        survive (re-numbered to their new position); snapshots of removed messages are dropped."""
        with self.lock:
            self.db.execute("DELETE FROM message WHERE session_id=?", (sid,))
            for i, m in enumerate(messages, start=1):
                m.setdefault("id", new_id("msg"))
                m.setdefault("time", {"created": now_ms()})
                self.db.execute("INSERT INTO message(id, session_id, seq, type, data, created) VALUES (?,?,?,?,?,?)",
                                (m["id"], sid, i, m.get("type", "user"), _j(m), m["time"].get("created", now_ms())))
            new_seq = {m["id"]: i for i, m in enumerate(messages, start=1)}
            for r in self.db.execute("SELECT id, message_id FROM snapshot WHERE session_id=?", (sid,)).fetchall():
                if r["message_id"] in new_seq:
                    self.db.execute("UPDATE snapshot SET seq=? WHERE id=?", (new_seq[r["message_id"]], r["id"]))
                else:
                    self.db.execute("DELETE FROM snapshot WHERE id=?", (r["id"],))

    # ---- snapshots (undo) -------------------------------------------------------------

    def record_snapshot(self, sid: str, mid: str, path: str) -> None:
        """Remember a file's content before the tool changes it — once per file per message."""
        seq = self.message_seq(sid, mid) or 0
        with self.lock:
            if self.db.execute("SELECT 1 FROM snapshot WHERE session_id=? AND message_id=? AND path=?", (sid, mid, path)).fetchone():
                return
            p = Path(path)
            existed = p.is_file()
            content = p.read_bytes() if existed else None
            self.db.execute("INSERT INTO snapshot(session_id, message_id, seq, path, existed, content, created) VALUES (?,?,?,?,?,?,?)",
                            (sid, mid, seq, path, 1 if existed else 0, content, now_ms()))

    def snapshots_from(self, sid: str, seq: int) -> list[dict]:
        rows = self.db.execute("SELECT * FROM snapshot WHERE session_id=? AND seq>=? ORDER BY seq, id", (sid, seq))
        return [{"path": r["path"], "existed": bool(r["existed"]), "content": r["content"], "seq": r["seq"], "message_id": r["message_id"]} for r in rows]

    def touched_files(self, sid: str) -> list[dict]:
        """First snapshot per file in this session = the original content, for the Changes panel."""
        seen: dict[str, dict] = {}
        for r in self.db.execute("SELECT * FROM snapshot WHERE session_id=? ORDER BY seq, id", (sid,)):
            seen.setdefault(r["path"], {"path": r["path"], "existed": bool(r["existed"]), "content": r["content"]})
        return list(seen.values())
