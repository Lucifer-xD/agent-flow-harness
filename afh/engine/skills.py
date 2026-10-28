"""Skills: folders with a SKILL.md that the model can load on demand.

Discovery mirrors OpenCode so skills installed for it (or for Claude Code / the agents
convention) show up here too. A skill's id is its directory name; a skill nested inside
another skill directory gets ``parent/child``. Later roots win on duplicate ids, so a project
skill overrides a global one with the same id.

The ``skill`` tool returns the SKILL.md body wrapped exactly like OpenCode's skill tool
(``<skill_content>`` block with the base directory and up to 10 supporting files), so prompts
and skills written for OpenCode behave the same.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .types import ToolContext, ToolResult, ToolSpec

SKILL_FILE = "SKILL.md"
MAX_LISTED_FILES = 10
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}

# (label, path relative to its base) — global roots first, project roots last; later wins.
GLOBAL_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("global:opencode", (".config", "opencode", "skills")),
    ("global:claude", (".claude", "skills")),
    ("global:agents", (".agents", "skills")),
)
PROJECT_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("project:opencode", (".opencode", "skills")),
    ("project:claude", (".claude", "skills")),
    ("project:agents", (".agents", "skills")),
    ("project:afh", (".afh", "skills")),
)

_MENTION_RE = re.compile(r"(?<![\w@/])@([A-Za-z0-9][A-Za-z0-9._/-]*)")


@dataclass
class Skill:
    id: str
    name: str
    description: str
    path: str  # absolute path of SKILL.md
    dir: str  # its directory
    body: str  # SKILL.md without the frontmatter
    advertise: bool  # listed in the system prompt (False = only on explicit @mention)
    source: str  # which root it came from, e.g. "project:claude"


# ---- frontmatter -----------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(frontmatter dict, body)``; the dict is empty when the file has no ``---`` block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            return parse_yaml_ish("\n".join(lines[1:end])), "\n".join(lines[end + 1 :]).lstrip("\n")
    return {}, text


def _scalar(raw: str) -> Any:
    v = raw.strip()
    if v == "":
        return ""
    if v in ("~", "null"):
        return None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace('\\"', '"') if v[0] == '"' else inner.replace("''", "'")
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if v[0] == "[" and v[-1] == "]":
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    return v


def parse_yaml_ish(text: str) -> dict[str, Any]:
    """Enough YAML for skill frontmatter: ``key: value``, quoted strings, ``|``/``>`` block
    scalars, ``- item`` lists and one level of nested mappings (``metadata:``). No dependency."""
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " \t":
            i += 1
            continue
        key, sep, rest = line.partition(":")
        if not sep:
            i += 1
            continue
        key, rest = key.strip(), rest.strip()
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            block, i = _block(lines, i + 1)
            joined = "\n".join(block) if rest[0] == "|" else _fold(block)
            out[key] = joined.rstrip("\n") if rest.endswith("-") else joined.rstrip("\n") + ("\n" if block else "")
            continue
        if rest == "" or rest.startswith("#"):
            # nested mapping or list on the following indented lines
            nested, i = _block(lines, i + 1)
            if nested and nested[0].lstrip().startswith("- "):
                out[key] = [_scalar(n.lstrip()[2:]) for n in nested if n.strip().startswith("- ")]
            elif nested:
                out[key] = parse_yaml_ish("\n".join(n[_indent(nested):] for n in nested))
            else:
                out[key] = None
            continue
        out[key] = _scalar(rest)
        i += 1
    return out


def _indent(lines: list[str]) -> int:
    return min(len(l) - len(l.lstrip()) for l in lines if l.strip())


def _block(lines: list[str], start: int) -> tuple[list[str], int]:
    """Indented lines following ``start`` (blank lines included), de-indented."""
    block: list[str] = []
    i = start
    while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
        block.append(lines[i])
        i += 1
    while block and not block[-1].strip():
        block.pop()
    if block:
        ind = _indent(block)
        block = [l[ind:] if l.strip() else "" for l in block]
    return block, i


def _fold(block: list[str]) -> str:
    """YAML ``>`` folding: single newlines become spaces, blank lines stay paragraph breaks."""
    paragraphs, current = [], []
    for l in block:
        if l.strip():
            current.append(l.strip())
        else:
            paragraphs.append(" ".join(current))
            current = []
    paragraphs.append(" ".join(current))
    return "\n".join(paragraphs)


# ---- discovery -------------------------------------------------------------------------------


def load_skill(skill_md: Path, root: Path, source: str) -> Skill | None:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = split_frontmatter(text)
    skill_id = skill_md.parent.relative_to(root).as_posix()
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    advertise = meta.get("disable-model-invocation") is not True
    if isinstance(metadata.get("opencode/autoinvoke"), bool):
        advertise = metadata["opencode/autoinvoke"]
    name = meta.get("name")
    description = meta.get("description")
    return Skill(
        id=skill_id,
        name=str(name).strip() if name else skill_md.parent.name,
        description=" ".join(str(description).split()) if description else "",
        path=str(skill_md),
        dir=str(skill_md.parent),
        body=body.strip(),
        advertise=advertise,
        source=source,
    )


def scan_root(root: Path, source: str) -> list[Skill]:
    """Every directory under ``root`` (recursively) that holds a SKILL.md."""
    found: list[Skill] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        if SKILL_FILE in filenames and Path(dirpath) != root:
            skill = load_skill(Path(dirpath) / SKILL_FILE, root, source)
            if skill:
                found.append(skill)
    return found


def skill_roots(project_dir: str | None, home: Path, user_home: Path | None = None) -> list[tuple[str, Path]]:
    user = user_home or Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    roots: list[tuple[str, Path]] = []
    for label, parts in GLOBAL_ROOTS:
        base = Path(xdg) / Path(*parts[1:]) if (xdg and parts[0] == ".config" and user_home is None) else user.joinpath(*parts)
        roots.append((label, base))
    roots.append(("afh", Path(home) / "skills"))
    if project_dir:
        for label, parts in PROJECT_ROOTS:
            roots.append((label, Path(project_dir).joinpath(*parts)))
    return roots


def discover(project_dir: str | None, home: Path, user_home: Path | None = None) -> list[Skill]:
    """All skills visible to a session; ``home`` is the AFH data dir (its ``skills/`` is a root).
    ``user_home`` overrides ``Path.home()`` (tests)."""
    by_id: dict[str, Skill] = {}
    for label, root in skill_roots(project_dir, home, user_home):
        for skill in scan_root(root, label):
            by_id[skill.id] = skill  # later roots override earlier ones
    return sorted(by_id.values(), key=lambda s: s.id)


# ---- prompt & tool ---------------------------------------------------------------------------


def catalog_text(skills: Iterable[Skill]) -> str:
    """Compact catalog for the system prompt; only advertised skills."""
    lines = [f"- {s.id} · {s.name} · {s.description}".rstrip(" ·") for s in skills if s.advertise]
    if not lines:
        return ""
    return "Available skills (load one with the `skill` tool when the task matches its description):\n" + "\n".join(lines)


def supporting_files(skill: Skill, limit: int = MAX_LISTED_FILES) -> list[str]:
    """Absolute paths of up to ``limit`` files next to SKILL.md (sorted, dotfiles included)."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skill.dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        files.extend(str(Path(dirpath) / f) for f in filenames if f != SKILL_FILE)  # OpenCode drops every SKILL.md
    return sorted(files)[:limit]


def to_model_output(skill: Skill, files: list[str]) -> str:
    """Byte-for-byte the layout of OpenCode's ``Skill.toModelOutput``."""
    return "\n".join(
        [
            f'<skill_content name="{skill.name}">',
            f"# Skill: {skill.name}",
            "",
            skill.body.strip(),
            "",
            f"Base directory for this skill: {skill.dir}",
            "Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.",
            "Note: file list is sampled.",
            "",
            "<skill_files>",
            *(f"<file>{f}</file>" for f in files),
            "</skill_files>",
            "</skill_content>",
        ]
    )


class SkillTool:
    """The ``skill`` tool: loads a skill's instructions into the conversation."""

    DESCRIPTION = (
        "Load a specialized skill's instructions and resources into the current conversation when the task at hand matches its description.\n\n"
        "The skill ID must match an available skill or a skill explicitly referenced by the user."
    )

    def __init__(self, skills: list[Skill] | Callable[[], list[Skill]]):
        self._skills = skills
        self.spec = ToolSpec(
            name="skill",
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {"id": {"type": "string", "description": "The ID of an available skill or a skill explicitly referenced by the user"}},
                "required": ["id"],
            },
        )

    def skills(self) -> list[Skill]:
        return self._skills() if callable(self._skills) else list(self._skills)

    def get(self, skill_id: str) -> Skill | None:
        wanted = (skill_id or "").strip().lstrip("@")
        return next((s for s in self.skills() if s.id == wanted), None)

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        skill = self.get(str(input.get("id", "")))
        if skill is None:
            available = ", ".join(s.id for s in self.skills()) or "none"
            return ToolResult(text=f"Unable to load skill {input.get('id')!s}. Available skills: {available}", is_error=True)
        await ctx.permissions.require("skill", [skill.id], {"skill": skill.id, "path": skill.path})
        output = to_model_output(skill, supporting_files(skill))
        return ToolResult(text=output, metadata={"name": skill.name, "directory": skill.dir, "id": skill.id})


def mentioned(text: str, skills: Iterable[Skill]) -> list[Skill]:
    """Skills the user referenced as ``@skill-id`` in a message, in order, without duplicates."""
    by_id = {s.id: s for s in skills}
    out: list[Skill] = []
    for m in _MENTION_RE.finditer(text or ""):
        ref = m.group(1).rstrip(".,;:!?")
        skill = by_id.get(ref)
        if skill and skill not in out:
            out.append(skill)
    return out
