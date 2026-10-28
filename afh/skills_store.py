"""skills.sh client plus an installer that writes skills where the AFH engine reads them.

What the live skills.sh API looks like (checked 2026-10-28):

- Documented ``/api/v1/*`` endpoints (``/skills``, ``/skills/search``, ``/skills/curated``,
  ``/skills/{source}/{slug}``) answer 401 ``authentication_required`` unless a Vercel OIDC
  bearer token is sent. Set ``SKILLS_SH_TOKEN`` and they are used.
- Without a token this module uses what the official ``skills`` CLI and the website use,
  all public and unauthenticated:
    GET /api/search?q=&limit=&owner=            -> {query, searchType, skills:[{id, source, skillId, name, installs}], count}
    GET /api/download/{owner}/{repo}/{slug}      -> {files:[{path, contents}], hash}   (404 -> {"error":"not_found"})
    GET /api/v1/skills/audit/{source}/{slug}     -> {id, source, slug, audits:[{provider, slug, status, summary, auditedAt, riskLevel, categories}]}
    GET / , /trending , /hot  (header RSC: 1)    -> React Server Component payload containing "initialSkills":[{source, skillId, name, installs, ...}]
    GET /official             (header RSC: 1)    -> payload containing "owners":[{owner, repos:[{repo, totalInstalls, skills:[{name, installs}]}], totalInstalls, featuredRepo, featuredSkill}]

Every public function returns skill records normalised to the documented v1 shape:
``{id, slug, name, source, installs, sourceType, installUrl, url}``.

Install locations (OpenCode reads all of these; AFH only ever writes to the first two):
- global:   ~/.afh/skills/<slug>/
- project:  <project>/.afh/skills/<slug>/
- external: ~/.claude/skills, ~/.agents/skills, ~/.config/opencode/skills, <project>/.claude|.agents|.opencode/skills
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import httpx

BASE_URL = "https://skills.sh"
TIMEOUT = 15.0
HEADERS = {"User-Agent": "agent-flow-harness", "Accept": "application/json"}
CACHE_TTL = 60.0  # seconds; in-memory cache for GET responses

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 200
MANIFEST_NAME = ".afh-skill.json"
VIEWS = ("all-time", "trending", "hot")
SCOPES = ("global", "project")

HOME = Path.home()
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
from .store import AFH_DIR

AFH_SKILLS_DIR = AFH_DIR / "skills"
OPENCODE_SKILLS_DIR = AFH_SKILLS_DIR  # kept for older callers
EXTERNAL_SKILL_DIRS: tuple[Path, ...] = (HOME / ".claude" / "skills", HOME / ".agents" / "skills", XDG_CONFIG / "opencode" / "skills")
PROJECT_SKILLS_SUBDIR = Path(".afh") / "skills"
PROJECT_EXTERNAL_SUBDIRS: tuple[Path, ...] = (Path(".claude") / "skills", Path(".agents") / "skills", Path(".opencode") / "skills")

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

_lock = threading.RLock()
_cache: dict[str, tuple[float, Any]] = {}


class SkillsError(RuntimeError):
    """A skills.sh or installer failure; ``status`` mirrors the HTTP status where there is one."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- HTTP


def _token() -> str | None:
    return os.environ.get("SKILLS_SH_TOKEN") or None


def _get(path: str, params: dict | None = None, *, rsc: bool = False, auth: bool = False) -> tuple[int, Any]:
    """GET BASE_URL+path, cached for CACHE_TTL. Returns (status, parsed JSON or text)."""
    url = BASE_URL + path
    key = json.dumps([url, params or {}, rsc, auth], sort_keys=True)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    headers = dict(HEADERS)
    if rsc:
        headers["RSC"] = "1"
        headers["Accept"] = "text/x-component"
    if auth and _token():
        headers["Authorization"] = f"Bearer {_token()}"
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SkillsError(f"skills.sh unreachable: {exc}", 503) from exc
    if resp.status_code == 429:
        raise SkillsError("skills.sh rate limit hit; retry in a moment", 429)
    if rsc:
        body: Any = resp.text
    else:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
    result = (resp.status_code, body)
    if resp.status_code < 500:
        with _lock:
            _cache[key] = (now + CACHE_TTL, result)
    return result


def _v1(path: str, params: dict | None = None) -> Any | None:
    """Call a documented /api/v1 endpoint when a token is configured. None means 'not available'."""
    if not _token():
        return None
    status, body = _get(path, params, auth=True)
    if status == 401:
        return None
    if status == 404:
        raise SkillsError("skill not found", 404)
    if status >= 400:
        raise SkillsError(f"skills.sh error {status}: {_message(body)}", status)
    return body


def _message(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)
    return str(body)[:200]


def _rsc_value(text: str, key: str) -> Any:
    """Pull the JSON value following ``"key":`` out of a Next.js RSC payload."""
    marker = f'"{key}":'
    idx = text.find(marker)
    if idx < 0:
        raise SkillsError(f"skills.sh page layout changed: no {key!r} in payload", 502)
    try:
        value, _ = json.JSONDecoder().raw_decode(text, idx + len(marker))
    except ValueError as exc:
        raise SkillsError(f"skills.sh page layout changed: cannot parse {key!r}", 502) from exc
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# --------------------------------------------------------------------------- records


def _record(source: str, slug: str, name: str | None = None, installs: Any = 0, **extra: Any) -> dict:
    source = str(source or "").strip("/")
    slug = str(slug or "")
    github = bool(_SOURCE_RE.match(source))
    out = {
        "id": f"{source}/{slug}",
        "slug": slug,
        "name": name or slug,
        "source": source,
        "installs": int(installs or 0),
        "sourceType": "github" if github else "well-known",
        "installUrl": f"https://github.com/{source}" if github else f"https://{source}",
        "url": f"{BASE_URL}/{source}/{slug}",
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _from_v1(item: dict) -> dict:
    return _record(
        item.get("source", ""),
        item.get("slug") or item.get("skillId") or "",
        item.get("name"),
        item.get("installs"),
        isDuplicate=item.get("isDuplicate"),
    )


def _from_site(item: dict) -> dict:
    return _record(
        item.get("source", ""),
        item.get("skillId") or item.get("slug") or "",
        item.get("name"),
        item.get("installs"),
        weeklyInstalls=item.get("weeklyInstalls"),
        isOfficial=item.get("isOfficial"),
    )


def _split_source(source: str) -> tuple[str, str]:
    if not _SOURCE_RE.match(source or ""):
        raise ValueError(f"source must look like owner/repo, got {source!r}")
    owner, repo = source.split("/", 1)
    return owner, repo


def _check_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug or "") or ".." in slug:
        raise ValueError(f"invalid skill slug {slug!r}")
    return slug


# --------------------------------------------------------------------------- catalogue


def search(q: str, limit: int = 30, owner: str | None = None) -> dict:
    """Search skills by name/description. Returns {data, query, searchType, count}."""
    q = (q or "").strip()
    if len(q) < 2:
        raise ValueError("query must be at least 2 characters")
    limit = max(1, min(int(limit), 100))
    params: dict[str, Any] = {"q": q, "limit": limit}
    if owner:
        params["owner"] = owner
    body = _v1("/api/v1/skills/search", params)
    if body is not None:
        data = [_from_v1(s) for s in body.get("data") or []]
        return {"data": data, "query": q, "searchType": body.get("searchType"), "count": body.get("count", len(data))}
    status, body = _get("/api/search", params)
    if status >= 400 or not isinstance(body, dict):
        raise SkillsError(f"skills.sh search failed ({status}): {_message(body)}", status if status >= 400 else 502)
    data = [_from_site(s) for s in body.get("skills") or []]
    return {"data": data, "query": q, "searchType": body.get("searchType"), "count": body.get("count", len(data))}


def browse(view: str = "trending", page: int = 0, per_page: int = 40, source: str | None = None) -> dict:
    """Leaderboard page. Returns {data, pagination:{page, perPage, total, hasMore}, view}."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    page = max(0, int(page))
    per_page = max(1, min(int(per_page), 500))
    params: dict[str, Any] = {"view": view, "page": page, "per_page": per_page}
    if source:
        params["source"] = source
    body = _v1("/api/v1/skills", params)
    if body is not None:
        pag = body.get("pagination") or {}
        return {
            "data": [_from_v1(s) for s in body.get("data") or []],
            "pagination": {
                "page": pag.get("page", page),
                "perPage": pag.get("perPage", per_page),
                "total": pag.get("total"),
                "hasMore": bool(pag.get("hasMore", False)),
            },
            "view": view,
        }
    # Public fallback: the website's server-rendered leaderboard (600 rows per view).
    path = {"all-time": "/", "trending": "/trending", "hot": "/hot"}[view]
    status, text = _get(path, rsc=True)
    if status >= 400 or not isinstance(text, str):
        raise SkillsError(f"skills.sh leaderboard unavailable ({status})", status if status >= 400 else 502)
    rows = [_from_site(s) for s in _rsc_value(text, "initialSkills") if isinstance(s, dict)]
    if source:
        rows = [r for r in rows if r["source"].lower() == source.lower()]
    start = page * per_page
    chunk = rows[start : start + per_page]
    return {
        "data": chunk,
        "pagination": {"page": page, "perPage": per_page, "total": len(rows), "hasMore": start + per_page < len(rows)},
        "view": view,
    }


def curated() -> dict:
    """Official first-party skills grouped by owner: {data:[{owner, totalInstalls, featuredRepo, featuredSkill, repos, skills}], totalOwners, totalSkills}."""
    body = _v1("/api/v1/skills/curated")
    if body is not None:
        data = []
        for o in body.get("data") or []:
            data.append({**o, "skills": [_from_v1(s) for s in o.get("skills") or []]})
        return {"data": data, "totalOwners": body.get("totalOwners", len(data)), "totalSkills": body.get("totalSkills")}
    status, text = _get("/official", rsc=True)
    if status >= 400 or not isinstance(text, str):
        raise SkillsError(f"skills.sh curated list unavailable ({status})", status if status >= 400 else 502)
    owners = _rsc_value(text, "owners")
    data = []
    for o in owners:
        if not isinstance(o, dict):
            continue
        skills = []
        for repo in o.get("repos") or []:
            for s in repo.get("skills") or []:
                skills.append(_record(repo.get("repo", ""), s.get("name", ""), s.get("name"), s.get("installs")))
        skills.sort(key=lambda s: -s["installs"])
        data.append(
            {
                "owner": o.get("owner"),
                "totalInstalls": o.get("totalInstalls", sum(s["installs"] for s in skills)),
                "featuredRepo": o.get("featuredRepo"),
                "featuredSkill": o.get("featuredSkill"),
                "repos": o.get("repos") or [],
                "skills": skills,
            }
        )
    totals = {k: _rsc_int(text, k) for k in ("totalOwners", "totalSkills")}
    return {"data": data, "totalOwners": totals["totalOwners"] or len(data), "totalSkills": totals["totalSkills"]}


def _rsc_int(text: str, key: str) -> int | None:
    m = re.search(rf'"{key}":(\d+)', text)
    return int(m.group(1)) if m else None


def detail(source: str, slug: str) -> dict:
    """Skill metadata plus its files: {id, source, slug, installs, hash, files:[{path, contents}]}."""
    _check_slug(slug)
    body = _v1(f"/api/v1/skills/{source}/{slug}")
    if body is not None:
        return {**_record(source, slug, body.get("name"), body.get("installs")), "hash": body.get("hash"), "files": body.get("files")}
    owner, repo = _split_source(source)
    status, body = _get(f"/api/download/{owner}/{repo}/{slug}")
    if status == 404:
        raise SkillsError(f"skill {source}/{slug} not found on skills.sh", 404)
    if status >= 400 or not isinstance(body, dict):
        raise SkillsError(f"skills.sh download failed ({status}): {_message(body)}", status if status >= 400 else 502)
    installs = None
    try:  # best effort: installs come from the search index
        for s in search(slug, limit=20, owner=owner)["data"]:
            if s["id"].lower() == f"{source}/{slug}".lower():
                installs = s["installs"]
                break
    except Exception:
        pass
    return {**_record(source, slug, slug, installs), "hash": body.get("hash"), "files": body.get("files") or []}


def audit(source: str, slug: str) -> dict | None:
    """Security audit results, or None when skills.sh has none (404)."""
    _check_slug(slug)
    status, body = _get(f"/api/v1/skills/audit/{source}/{slug}")
    if status == 404:
        return None
    if status >= 400 or not isinstance(body, dict):
        raise SkillsError(f"skills.sh audit failed ({status}): {_message(body)}", status if status >= 400 else 502)
    return body


# --------------------------------------------------------------------------- install


def skills_root(scope: str = "global", project_dir: str | Path | None = None, root: str | Path | None = None) -> Path:
    """Directory AFH writes skills into for ``scope``; ``root`` overrides it (tests)."""
    if root is not None:
        return Path(root)
    if scope == "global":
        return OPENCODE_SKILLS_DIR
    if scope == "project":
        if not project_dir:
            raise ValueError("project_dir is required for project scope")
        return Path(project_dir) / PROJECT_SKILLS_SUBDIR
    raise ValueError(f"scope must be one of {SCOPES}")


def _safe_relpath(raw: str, base: Path) -> Path | None:
    """Return base/raw if raw is a plain relative POSIX path that stays inside base, else None."""
    if not raw or "\\" in raw or "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    p = PurePosixPath(raw)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts) or p.parts[-1] == MANIFEST_NAME:
        return None
    target = (base / Path(*p.parts)).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def _snapshot_hash(files: list[dict]) -> str:
    """Local content hash (sha256 over sorted path+contents, like the skills CLI's computeSnapshotHash).

    This does NOT reproduce the ``hash`` skills.sh returns; it is only used when the server gives none,
    and check_updates() compares local-to-local or server-to-server, never across.
    """
    h = hashlib.sha256()
    for f in sorted(files, key=lambda f: f["path"]):
        h.update(f["path"].encode("utf-8"))
        h.update(str(f.get("contents") or "").encode("utf-8"))
    return h.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def install(
    source: str,
    slug: str,
    scope: str = "global",
    project_dir: str | Path | None = None,
    root: str | Path | None = None,
) -> dict:
    """Download a skill and write it under the skills dir for ``scope``. Returns the manifest."""
    _check_slug(slug)
    _split_source(source)  # only GitHub-hosted owner/repo skills are downloadable
    base = skills_root(scope, project_dir, root)
    info = detail(source, slug)
    files = [f for f in (info.get("files") or []) if isinstance(f, dict) and isinstance(f.get("path"), str)]
    if not files:
        raise SkillsError(f"{source}/{slug} has no downloadable files", 404)

    kept: list[tuple[Path, str, str]] = []
    skipped: list[dict] = []
    for f in files:
        rel = f["path"]
        contents = f.get("contents")
        if not isinstance(contents, str):
            skipped.append({"path": rel, "reason": "no text contents"})
            continue
        if len(kept) >= MAX_FILES:
            skipped.append({"path": rel, "reason": f"more than {MAX_FILES} files"})
            continue
        if len(contents.encode("utf-8")) > MAX_FILE_BYTES:
            skipped.append({"path": rel, "reason": "larger than 1 MB"})
            continue
        kept.append((Path(*PurePosixPath(rel).parts), rel, contents))
    if not any(rel == "SKILL.md" for _, rel, _ in kept):
        raise SkillsError(f"{source}/{slug} does not contain a top-level SKILL.md", 422)

    final = base / slug
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".{slug}.staging-{os.getpid()}"
    old = base / f".{slug}.old-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        for _, rel, contents in kept:
            target = _safe_relpath(rel, staging)
            if target is None:
                raise ValueError(f"unsafe file path in skill: {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8", newline="\n")
        manifest = {
            "id": info["id"],
            "source": info["source"],
            "slug": slug,
            # skills.sh's hash and the local recipe are not interchangeable, so remember which one this is.
            "hash": info.get("hash") or _snapshot_hash(files),
            "hashSource": "skills.sh" if info.get("hash") else "local",
            "installs": info.get("installs"),
            "installedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": scope,
            "files": [rel for _, rel, _ in kept],
            "skipped": skipped,
        }
        _write_json(staging / MANIFEST_NAME, manifest)
        with _lock:
            shutil.rmtree(old, ignore_errors=True)
            if final.exists():
                final.rename(old)
            try:
                staging.rename(final)
            except OSError:
                if old.exists():
                    old.rename(final)
                raise
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {**manifest, "path": str(final)}


def uninstall(slug: str, scope: str = "global", project_dir: str | Path | None = None, root: str | Path | None = None) -> bool:
    """Remove a skill folder AFH manages (or any SKILL.md folder) from the OpenCode skills dir."""
    _check_slug(slug)
    if scope == "external":
        raise ValueError("external skill folders (~/.claude, ~/.agents) are read-only for AFH")
    base = skills_root(scope, project_dir, root)
    target = (base / slug).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise ValueError("slug escapes the skills directory") from None
    if not target.is_dir():
        return False
    if not (target / MANIFEST_NAME).exists() and not (target / "SKILL.md").exists():
        raise ValueError(f"{target} is not a skill folder")
    shutil.rmtree(target)
    return True


# --------------------------------------------------------------------------- installed


def parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML-frontmatter reader: top-level ``key: value`` pairs, quotes stripped, folded blocks joined."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        if line[:1] not in (" ", "\t") and ":" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value in (">", "|", ">-", "|-"):
                value = ""
            out[key] = _unquote(value)
        elif key is not None and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return inner.replace('\\"', '"') if value[0] == '"' else inner
    return value


def _read_manifest(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _scan(folder: Path, scope: str) -> list[dict]:
    if not folder.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_md = child / "SKILL.md"
        manifest = _read_manifest(child)
        if manifest is None and not skill_md.is_file():
            continue
        fm: dict[str, str] = {}
        if skill_md.is_file():
            try:
                fm = parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                fm = {}
        entry = {
            "id": None,
            "source": None,
            "slug": child.name,
            "name": fm.get("name") or child.name,
            "description": fm.get("description", ""),
            "hash": None,
            "installs": None,
            "installedAt": None,
            "scope": scope,
            "managed": manifest is not None,
            "path": str(child),
        }
        if manifest:
            for k in ("id", "source", "hash", "hashSource", "installs", "installedAt"):
                entry[k] = manifest.get(k)
            entry["slug"] = manifest.get("slug") or child.name
        out.append(entry)
    return out


def installed(
    project_dir: str | Path | None = None,
    root: str | Path | None = None,
    external_dirs: Iterable[str | Path] | None = None,
) -> list[dict]:
    """Every skill the engine would see: AFH-managed (manifest) and unmanaged (bare SKILL.md) folders."""
    out: list[dict] = []
    out += _scan(skills_root("global", None, root), "global")
    if project_dir:
        project = Path(project_dir)
        out += _scan(project / PROJECT_SKILLS_SUBDIR, "project")
        for sub in PROJECT_EXTERNAL_SUBDIRS:
            out += _scan(project / sub, "external")
    ext = list(EXTERNAL_SKILL_DIRS) if external_dirs is None else [Path(p) for p in external_dirs]
    for d in ext:
        out += _scan(Path(d), "external")
    return out


def check_updates(project_dir: str | Path | None = None, root: str | Path | None = None) -> list[dict]:
    """Compare each managed skill's manifest hash with the live snapshot hash."""
    results: list[dict] = []
    for entry in installed(project_dir, root, external_dirs=[]):
        if not entry["managed"] or not entry.get("source"):
            continue
        row = {
            "id": entry["id"],
            "slug": entry["slug"],
            "scope": entry["scope"],
            "path": entry["path"],
            "installedHash": entry.get("hash"),
            "latestHash": None,
            "updateAvailable": False,
            "error": None,
        }
        try:
            live = detail(entry["source"], entry["slug"])
            local_only = entry.get("hashSource") == "local" or not live.get("hash")
            if local_only:
                row["latestHash"] = _snapshot_hash(live["files"]) if live.get("files") else None
                if entry.get("hashSource") != "local":
                    row["error"] = "skills.sh returned no hash; cannot compare"
                    row["latestHash"] = None
            else:
                row["latestHash"] = live["hash"]
            row["updateAvailable"] = bool(row["latestHash"] and row["installedHash"] and row["latestHash"] != row["installedHash"])
        except Exception as exc:
            row["error"] = str(exc)
        results.append(row)
    return results
