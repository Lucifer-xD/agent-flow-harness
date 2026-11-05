"""The conversation on screen: messages, tool rows, thinking, notices and the start screen."""
from __future__ import annotations

from typing import Any, Callable

from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Markdown, Static

from . import state as S
from .themes import gradient_text, mix

WINDOW = 60  # messages drawn at once; "Show earlier" adds more
MAX_BODY_LINES = 400  # lines of a tool's output drawn when opened
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
LOGO = (
    " █████╗ ███████╗██╗  ██╗",
    "██╔══██╗██╔════╝██║  ██║",
    "███████║█████╗  ███████║",
    "██╔══██║██╔══╝  ██╔══██║",
    "██║  ██║██║     ██║  ██║",
    "╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝",
)
TODO_MARK = {"completed": "✓", "cancelled": "✗", "in_progress": "▸", "pending": "○"}
VISIBLE = {"user", "assistant", "compaction", "model-switched", "agent-switched", "shell"}


def gradient(text: str, style: str = "bold") -> Content:
    return Content.assemble(*[(ch, f"{colour} {style}".strip()) for ch, colour in gradient_text(text)])


def logo() -> Content:
    width = max(len(line) for line in LOGO)
    colours = [c for _, c in gradient_text("x" * width)]
    lines = []
    for line in LOGO:
        lines.append(Content.assemble(*[(ch, colours[i]) for i, ch in enumerate(line)]))
    return Content("\n").join(lines)


def diff_content(patch: str | None, limit: int = MAX_BODY_LINES) -> Content:
    """A coloured unified diff."""
    pieces: list[Content] = []
    lines = (patch or "").rstrip("\n").split("\n")
    for line in lines[:limit]:
        if line.startswith(("+++", "---")):
            pieces.append(Content.styled(line, "$afh-text3"))
        elif line.startswith("@@"):
            pieces.append(Content.styled(line, "$primary"))
        elif line.startswith("+"):
            pieces.append(Content.styled(line, "$success on $success 12%"))
        elif line.startswith("-"):
            pieces.append(Content.styled(line, "$error on $error 12%"))
        else:
            pieces.append(Content.styled(line, "$afh-text2"))
    if len(lines) > limit:
        pieces.append(Content.styled(f"… {len(lines) - limit} more lines. /diff shows all of it.", "$afh-text3"))
    return Content("\n").join(pieces)


def plain_block(text: str, style: str = "$afh-text2", limit: int = MAX_BODY_LINES) -> Content:
    lines = text.rstrip().split("\n")
    body = "\n".join(lines[:limit])
    if len(lines) > limit:
        body += f"\n… {len(lines) - limit} more lines"
    return Content.styled(body, style)


class Row(Static):
    """One line of text that can't wrap."""
    DEFAULT_CSS = "Row { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }"


class Foldable(Vertical):
    """A line you can click to show more: the base of tool rows and thinking."""

    DEFAULT_CSS = """
    Foldable { height: auto; }
    Foldable > Horizontal { height: 1; }
    Foldable .fold-left { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    Foldable .fold-right { width: auto; height: 1; padding-left: 1; }
    Foldable .fold-body { height: auto; padding: 0 0 0 2; display: none; }
    Foldable .fold-tail { height: auto; padding: 0 0 0 2; color: $afh-text3; display: none; }
    Foldable.-open .fold-body { display: block; }
    Foldable:hover .fold-left { background: $boost; }
    """

    def __init__(self, opened: bool = False, **kw: Any):
        super().__init__(**kw)
        self.opened = opened
        self.head = Static(classes="fold-left")
        self.right = Static(classes="fold-right")
        self.body = Static(classes="fold-body")
        self.tail = Static(classes="fold-tail")
        self.set_class(opened, "-open")

    def compose(self):
        with Horizontal():
            yield self.head
            yield self.right
        yield self.tail
        yield self.body

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.set_open(not self.opened)

    def set_open(self, opened: bool) -> None:
        self.opened = opened
        self.set_class(opened, "-open")
        self.draw()

    def draw(self) -> None:  # filled in by each kind of row
        pass


class ToolRow(Foldable):
    """One tool call: verb, target and outcome. Opens to its diff or output."""

    DEFAULT_CSS = "ToolRow { margin: 0 0 0 2; }"

    def __init__(self, tool: dict, opened: bool = False):
        super().__init__(opened=opened)
        self.tool = tool

    def on_mount(self) -> None:
        self.draw()

    def status(self) -> str:
        return (self.tool.get("state") or {}).get("status") or "streaming"

    def draw(self) -> None:
        p = self.tool
        state = p.get("state") or {}
        status = self.status()
        live = status in ("streaming", "running")
        name = (p.get("name") or "tool").lower()
        given = S.tool_input(p)
        meta = state.get("metadata") or {}
        kind = S.kind_of(name)
        patches = S.tool_patches(p) if kind == "edit" else []
        mark = ("●", "$primary") if live else ("✗", "$error") if status == "error" else ("●", "$success" if kind == "edit" else "$afh-text3")
        self.head.update(Content.assemble(mark, " ", (S.tool_verb(p, live), "bold"), "  ", (S.one_line(S.tool_target(p), 400), "$afh-text2")))
        bits: list[Any] = []
        if patches:
            added = removed = 0
            for x in patches:
                a, r = (x["additions"], x["deletions"]) if x.get("additions") is not None else S.count_patch(x.get("patch"))
                added, removed = added + (a or 0), removed + (r or 0)
            bits += [(f"+{added}", "$success"), " ", (f"−{removed}", "$error")]
        elif meta.get("blockedBy"):
            bits.append(("blocked by hook", "$warning"))
        elif status == "error":
            bits.append(("failed", "$error"))
        elif status == "streaming":
            bits.append(("preparing", "$afh-text3"))
        elif status == "running":
            bits.append((f"waiting up to {given['wait']}s" if name == "jobs" and given.get("wait") else "running", "$afh-text3"))
        elif meta.get("job"):
            job = meta["job"]
            word = "running" if job.get("running") else "stopped" if job.get("stopped") else f"exited {job.get('exitCode', '')}"
            bits.append((f"{job.get('id', '')} {word}", "$afh-text3"))
        diag = meta.get("diagnostics")
        if diag:
            ok = diag.get("ok")
            count = diag.get("problems", 0)
            bits += ["  ", ("checked" if ok else f"{count} problem{'' if count == 1 else 's'}", "$success" if ok else "$error")]
        hooks = meta.get("hooks") or []
        if hooks and not meta.get("blockedBy"):
            bits += ["  ", (f"{len(hooks)} hook{'s' if len(hooks) > 1 else ''}", "$error" if any(h.get("code") for h in hooks) else "$afh-text3")]
        self.right.update(Content.assemble(*bits) if bits else "")
        tail = S.live_tail(p) if live else ""
        self.tail.styles.display = "block" if tail else "none"
        if tail:
            self.tail.update(Content(tail))
        if self.opened:
            self.body.update(self.details(patches))

    def details(self, patches: list[dict]) -> Content:
        p = self.tool
        state = p.get("state") or {}
        sections: list[Content] = []
        if patches:
            for x in patches:
                if len(patches) > 1:
                    sections.append(Content.styled(S.base_name(x.get("file")), "bold"))
                sections.append(diff_content(x.get("patch")))
        else:
            text = S.input_text(p)
            if text:
                sections.append(plain_block(text, "$afh-text2"))
        out = S.tool_text(state.get("content"))
        if out:
            sections.append(Content.styled("Output", "$afh-text3 bold"))
            sections.append(plain_block(out, "$foreground"))
        images = [c for c in state.get("content") or [] if c.get("type") == "image"]
        if images:
            sections.append(Content.styled(f"{len(images)} image{'s' if len(images) > 1 else ''}. /images opens them.", "$afh-text3"))
        err = state.get("error")
        if err:
            sections.append(Content.styled(str(err.get("message") if isinstance(err, dict) else err), "$error"))
        return Content("\n").join(sections) if sections else Content.styled("Nothing to show", "$afh-text3")


class PlanRow(ToolRow):
    """The agent's `todo` call: the list as it stands after the call."""

    def __init__(self, tool: dict, opened: bool = True):
        super().__init__(tool, opened=opened)

    def draw(self) -> None:
        p = self.tool
        state = p.get("state") or {}
        given = S.tool_input(p)
        meta = state.get("metadata") or {}
        todos = meta.get("todos") or (given.get("todos") if isinstance(given.get("todos"), list) and not given.get("merge") else []) or []
        done = sum(1 for x in todos if x.get("status") == "completed")
        total = sum(1 for x in todos if x.get("status") != "cancelled")
        live = self.status() in ("streaming", "running")
        label = "Planning" if live else "Checked the to-do list" if meta.get("read") else "Updated the to-do list"
        self.head.update(Content.assemble(("●", "$primary" if live else "$afh-text3"), " ", (label, "bold")))
        self.right.update(Content.styled(f"{done}/{total} done", "$afh-text3") if todos else "")
        lines = []
        for x in todos:
            st = x.get("status") or "pending"
            text = x.get("activeForm") if st == "in_progress" and x.get("activeForm") else x.get("content")
            style = {"completed": "$afh-text3 strike", "cancelled": "$afh-text3 strike", "in_progress": "$primary"}.get(st, "$foreground")
            lines.append(Content.styled(f"{TODO_MARK.get(st, '○')} {text}", style))
        self.body.update(Content("\n").join(lines) if lines else "")


class ThinkRow(Foldable):
    """Thinking: one quiet line that opens to the text."""

    DEFAULT_CSS = "ThinkRow { margin: 0 0 0 2; } ThinkRow .fold-body { color: $afh-text3; }"

    def __init__(self, data: dict, opened: bool = False):
        super().__init__(opened=opened)
        self.data = data

    def on_mount(self) -> None:
        self.draw()

    def draw(self) -> None:
        p = self.data
        live = p.get("live")
        created, completed = (p.get("time") or {}).get("created"), (p.get("time") or {}).get("completed")
        start, end = (created, completed) if created and completed else (p.get("started"), p.get("ended"))
        secs = (end - start) / 1000 if start and end else None
        label = "Thinking" if live else (f"Thought for {secs:.1f}s" if secs < 10 else f"Thought for {round(secs)}s") if secs else "Thoughts"
        self.head.update(Content.assemble(("▾" if self.opened else "▸", "$afh-text3"), " ", (label, "$afh-text3 italic")))
        text = (p.get("text") or "").strip()
        if self.opened:
            self.body.update(Content(text or "…"))
        tail = "\n".join(text.split("\n")[-2:]) if live and not self.opened else ""
        self.tail.styles.display = "block" if tail else "none"
        if tail:
            self.tail.update(Content(S.one_line(tail, 300)))


class DelegateRow(ToolRow):
    """A `subagent` call: who it went to, what it's doing now, and its report. Enter or click watches it."""

    def __init__(self, tool: dict, thread_of: Callable[[dict], "S.Thread | None"], agent_name: Callable[[str], str]):
        super().__init__(tool)
        self.thread_of, self.agent_name = thread_of, agent_name

    def draw(self) -> None:
        p = self.tool
        state = p.get("state") or {}
        given = S.tool_input(p)
        status = self.status()
        live = status in ("streaming", "running")
        who = self.agent_name(given.get("agent") or "helper")
        mark = ("●", "$primary") if live else ("✗", "$error") if status == "error" else ("●", "$success")
        self.head.update(Content.assemble(mark, " ", (who, "bold"), "  ", (S.one_line(given.get("description") or "", 300), "$afh-text2")))
        child = self.thread_of(p)
        word = "working" if live else "failed" if status == "error" else "done"
        cost = (child.session.get("cost") if child else 0) or 0
        self.right.update(Content.assemble((word, "$afh-text3"), (f"  {S.fmt_cost(cost)}", "$afh-text3") if cost else ""))
        steps = []
        if child and live:
            for m in child.messages[-6:]:
                for part in m.get("content") or []:
                    if part.get("type") == "tool":
                        running = (part.get("state") or {}).get("status") in ("streaming", "running")
                        steps.append(f"└ {S.tool_verb(part, running)} {S.one_line(S.tool_target(part), 80)}")
        self.tail.styles.display = "block" if steps else "none"
        if steps:
            self.tail.update(Content("\n".join(steps[-4:])))
        if self.opened:
            sections = [Content.styled("Brief", "$afh-text3 bold"), plain_block(given.get("prompt") or "", "$afh-text2", 60)]
            report = S.tool_text(state.get("content"))
            if report:
                sections += [Content.styled("Report", "$afh-text3 bold"), plain_block(report, "$foreground")]
            if state.get("error"):
                err = state["error"]
                sections.append(Content.styled(str(err.get("message") if isinstance(err, dict) else err), "$error"))
            self.body.update(Content("\n").join(sections))


class TextPart(Markdown):
    """Streamed Markdown. Only what's new is parsed, so a long answer stays smooth."""

    DEFAULT_CSS = """
    TextPart { margin: 1 0 0 2; padding: 0; background: transparent; height: auto; }
    TextPart MarkdownParagraph { margin: 0 0 1 0; }
    TextPart MarkdownFence { margin: 0 0 1 0; }
    """

    def __init__(self, data: dict):
        super().__init__(data.get("text") or "", open_links=False)
        self.data = data
        self.shown = data.get("text") or ""

    async def sync(self) -> None:
        text = self.data.get("text") or ""
        if text == self.shown:
            return
        if text.startswith(self.shown):
            delta, self.shown = text[len(self.shown):], text
            await self.append(delta)
        else:
            self.shown = text
            await self.update(text)


class UserMsg(Static):
    """What you sent."""

    DEFAULT_CSS = """
    UserMsg { margin: 1 0 1 0; padding: 0 1; border-left: outer $primary; background: $surface; color: $foreground; height: auto; }
    UserMsg.-pending { color: $afh-text3; }
    """

    def __init__(self, m: dict):
        super().__init__()
        self.m = m

    def on_mount(self) -> None:
        self.draw()

    def draw(self) -> None:
        m = self.m
        self.set_class(bool(m.get("pending")), "-pending")
        cmd = m.get("command")
        if cmd and cmd.get("name") == "goal":
            pieces = [("Goal  ", "$primary bold"), cmd.get("args") or ""]
        elif cmd:
            pieces = [(f"/{cmd.get('name')}", "$primary bold"), f" {cmd.get('args')}" if cmd.get("args") else ""]
        else:
            pieces = [m.get("text") or ""]
        files = [f.get("name") or S.base_name(f.get("uri")) for f in m.get("files") or []]
        if files:
            pieces += ["\n"] + [(f"[{name}] ", "$afh-text3") for name in files]
        if m.get("pending"):
            pieces.append(("  queued", "$afh-text3 italic"))
        self.update(Content.assemble(*pieces))


class Note(Static):
    """A quiet line in the thread: notices, model switches."""
    DEFAULT_CSS = "Note { margin: 0 0 1 2; color: $afh-text3; height: auto; } Note.-warn { color: $warning; }"


class ErrorCard(Static):
    DEFAULT_CSS = "ErrorCard { margin: 1 0 1 2; padding: 0 1; border-left: outer $error; background: $error 8%; height: auto; }"

    def __init__(self, err: Any, model: str = ""):
        super().__init__()
        info = S.explain_error(err)
        parts: list[Any] = [(info["title"], "$error bold"), "\n", info["message"]]
        if info["hint"]:
            parts += ["\n", (info["hint"], "$afh-text2")]
        chips = " · ".join(x for x in (model, f"HTTP {info['status']}" if info["status"] else "") if x)
        if chips:
            parts += ["\n", (chips, "$afh-text3")]
        self.update(Content.assemble(*parts))


class GoalCard(Static):
    DEFAULT_CSS = "GoalCard { margin: 0 0 1 2; padding: 0 1; height: auto; border-left: outer $success; } GoalCard.-blocked { border-left: outer $warning; }"


class AssistantMsg(Vertical):
    """One step of the model: its text, thinking and tool calls in order."""

    DEFAULT_CSS = """
    AssistantMsg { height: auto; }
    AssistantMsg .meta { margin: 0 0 1 2; color: $afh-text3; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    """

    def __init__(self, m: dict, view: "Transcript"):
        super().__init__()
        self.m, self.view = m, view
        self.parts: dict[str, Any] = {}
        self.meta_row = Static(classes="meta")
        self.retry_row = Note()
        self.err_row: ErrorCard | None = None
        self.stop_row: Note | None = None

    def compose(self):
        yield self.retry_row
        yield self.meta_row

    async def on_mount(self) -> None:
        await self.sync()

    def key_of(self, p: dict) -> str:
        return f"tool:{p.get('id')}" if p.get("type") == "tool" else f"{p.get('type')}:{p.get('ordinal')}"

    def make(self, p: dict) -> Any:
        kind = p.get("type")
        if kind == "text":
            return TextPart(p) if (p.get("text") or p.get("live")) else None
        if kind == "reasoning":
            return ThinkRow(p, opened=self.view.show_details) if self.view.show_thinking() and (p.get("text") or p.get("live")) else None
        if kind != "tool":
            return None
        name = (p.get("name") or "tool").lower()
        if name == "subagent":
            return DelegateRow(p, self.view.child_of, self.view.agent_name)
        if name == "todo":
            return PlanRow(p)
        if name == "goal":
            return self.goal_row(p) or ToolRow(p, opened=self.view.show_details)
        if name == "question":
            return self.question_row(p)
        if name == "design":
            return self.design_row(p) or ToolRow(p, opened=self.view.show_details)
        return ToolRow(p, opened=self.view.show_details)

    def goal_row(self, p: dict) -> Any:
        given = S.tool_input(p)
        status = (p.get("state") or {}).get("status")
        report = given.get("status")
        if report == "set" and status != "error" and given.get("text"):
            done = f" (done when {given['criteria']})" if given.get("criteria") else ""
            return Note(Content.assemble(("Goal set: ", "bold"), given["text"], done))
        if status == "error" or report not in ("achieved", "blocked", "progress"):
            return None
        if report == "progress":
            return Note(Content.assemble(("Milestone: ", "bold"), given.get("summary") or ""))
        ok = report == "achieved"
        pieces: list[Any] = [("Goal achieved" if ok else "Goal blocked, needs you", "$success bold" if ok else "$warning bold")]
        if given.get("summary"):
            pieces += ["\n", given["summary"]]
        card = GoalCard(Content.assemble(*pieces))
        card.set_class(not ok, "-blocked")
        return card

    def question_row(self, p: dict) -> Any:
        state = p.get("state") or {}
        meta = state.get("metadata") or {}
        given = S.tool_input(p)
        questions = meta.get("questions") or given.get("questions")
        if not isinstance(questions, list) or state.get("status") in (None, "streaming", "running"):
            return Note("")  # still open: the question dialog handles it
        answers = meta.get("answers")
        skipped = meta.get("dismissed") or not answers
        lines: list[Any] = [("Asked, skipped" if skipped else "Asked", "bold")]
        for i, q in enumerate(questions):
            a = (answers or [{}] * len(questions))[i] if i < len(answers or questions) else {}
            said = ", ".join([*(a.get("selected") or []), *([f'"{a["other"]}"'] if a.get("other") else [])])
            lines += ["\n", (q.get("question") or "", "$afh-text2"), "  ", said or ("skipped" if skipped else "-")]
        return Note(Content.assemble(*lines))

    def design_row(self, p: dict) -> Any:
        state = p.get("state") or {}
        meta = state.get("metadata") or {}
        if state.get("status") in (None, "streaming", "running"):
            return None
        chosen = (meta.get("answer") or {}).get("choice")
        title = (meta.get("design") or {}).get("title") or S.tool_input(p).get("title") or "Design options"
        word = "skipped" if meta.get("dismissed") else f"{chosen} chosen" if chosen else "new options asked for"
        return Note(Content.assemble(("Design: ", "bold"), str(title), f"  {word}"))

    def settled(self, p: dict, row: Any) -> bool:
        special = p.get("type") == "tool" and (p.get("name") or "").lower() in ("goal", "question", "design")
        return special and not getattr(row, "final", False) and (p.get("state") or {}).get("status") not in (None, "streaming", "running")

    async def sync(self) -> None:
        """Bring the widgets in line with the message. Parts only ever appear at the end, except on a retry."""
        m = self.m
        keys = {self.key_of(p) for p in m.get("content") or []}
        for key in [k for k in self.parts if k not in keys]:
            await self.parts.pop(key).remove()
        for p in m.get("content") or []:
            key = self.key_of(p)
            row = self.parts.get(key)
            if row is None:
                row = self.make(p)
                if row is None:
                    continue
                self.parts[key] = row
                await self.mount(row, before=self.meta_row)
            elif isinstance(row, TextPart):
                await row.sync()
            elif self.settled(p, row):  # goals, questions and designs get their own look once they're finished
                fresh = self.make(p)
                fresh.final = True
                self.parts[key] = fresh
                await self.mount(fresh, before=row)
                await row.remove()
            elif isinstance(row, ToolRow):
                row.tool = p
                row.draw()
            elif isinstance(row, ThinkRow):
                row.data = p
                row.draw()
        self.draw_retry()
        await self.draw_end()

    def draw_retry(self) -> None:
        m = self.m
        retries = m.get("retries") or []
        self.retry_row.styles.display = "block" if retries else "none"
        if not retries:
            return
        r = retries[-1]
        message = str((r.get("error") or {}).get("message") or "")
        why = f": {message[:90]}" if message else ""
        n = len(retries)
        if m.get("retrying"):
            text = f"Provider error, retrying (attempt {(r.get('attempt') or 0) + 1}){why}"
        elif m.get("error") and not m.get("stopped"):
            text = f"Provider error, gave up after {n + 1} attempts{why}"
        else:
            text = f"Provider error, recovered after {n} {'retry' if n == 1 else 'retries'}{why}"
        self.retry_row.update(text)

    async def draw_end(self) -> None:
        m = self.m
        stopped = m.get("stopped") or (m.get("error") and S.is_stop({"message": m.get("error")}))
        if m.get("error") and not stopped and not self.err_row and not self.view.same_as_live_error(m):
            self.err_row = ErrorCard(m["error"], self.view.model_name(m.get("model")))
            await self.mount(self.err_row, before=self.meta_row)
        if stopped and not self.stop_row:
            self.stop_row = Note("Stopped")
            await self.mount(self.stop_row, before=self.meta_row)
        text = self.meta_text()
        self.meta_row.styles.display = "block" if text else "none"
        self.meta_row.update(text)

    def meta_text(self) -> str:
        m = self.m
        if m.get("live") or not self.view.show_meta() or not self.view.ends_turn(m):
            return ""
        bits = [self.view.model_name(m.get("model"))]
        tokens = m.get("tokens")
        if tokens:
            cache = tokens.get("cache") or {}
            total = (tokens.get("input") or 0) + (cache.get("read") or 0) + (cache.get("write") or 0) + (tokens.get("output") or 0)
            bits.append(f"{S.fmt_tokens(total)} tokens")
        if m.get("cost"):
            bits.append(S.fmt_cost(m["cost"]))
        spent = m.get("turnMs") or m.get("durationMs")
        if not spent and (m.get("time") or {}).get("completed") and (m.get("time") or {}).get("created"):
            spent = m["time"]["completed"] - m["time"]["created"]
        if spent:
            bits.append(S.fmt_dur(spent))
        if m.get("tps"):
            bits.append(f"{round(m['tps'])} tok/s")
        return " · ".join(b for b in bits if b)

    def set_details(self, opened: bool) -> None:
        for row in self.parts.values():
            if isinstance(row, (ThinkRow, ToolRow)) and not isinstance(row, (PlanRow, DelegateRow)):
                row.set_open(opened)


class Compaction(Foldable):
    DEFAULT_CSS = "Compaction { margin: 0 0 1 2; } Compaction .fold-body { color: $afh-text2; }"

    def __init__(self, m: dict):
        super().__init__()
        self.m = m

    def on_mount(self) -> None:
        self.draw()

    def draw(self) -> None:
        n = (self.m.get("metadata") or {}).get("compacted")
        label = f"Compacted {n} earlier message{'' if n == 1 else 's'}, summary" if n else "Earlier context was compacted, summary"
        self.head.update(Content.assemble(("▾" if self.opened else "▸", "$afh-text3"), " ", (label, "$afh-text3")))
        if self.opened:
            self.body.update(Content(self.m.get("text") or "No summary was kept for this compaction."))


class ShowEarlier(Static):
    DEFAULT_CSS = "ShowEarlier { color: $primary; margin: 0 0 1 0; text-align: center; height: 1; }"

    def on_click(self) -> None:
        self.screen.query_one(Transcript).show_more()


class Transcript(VerticalScroll):
    """The conversation. Follows the end unless you've scrolled up."""

    DEFAULT_CSS = """
    Transcript { height: 1fr; padding: 0 1; scrollbar-size-vertical: 1; background: $background; }
    """
    can_focus = False

    def __init__(self, ui: Any, **kw: Any):
        super().__init__(**kw)
        self.ui = ui  # the app: names, settings, children
        self.thread: S.Thread | None = None
        self.rows: dict[str, Any] = {}
        self.dirty: set[str] = set()
        self.window = WINDOW
        self.show_details = False
        self.error_row: ErrorCard | None = None
        self.more: ShowEarlier | None = None

    def on_mount(self) -> None:
        self.anchor()
        self.set_interval(1 / 12, self.flush)

    # what the rows ask for
    def show_thinking(self) -> bool:
        return self.ui.setting("showReasoning", True)

    def show_meta(self) -> bool:
        return self.ui.setting("showMeta", True)

    def model_name(self, ref: Any) -> str:
        return self.ui.model_name(ref)

    def agent_name(self, aid: str) -> str:
        return self.ui.agent_name(aid)

    def child_of(self, tool: dict) -> Any:
        return self.ui.child_of(self.thread, tool) if self.thread else None

    def ends_turn(self, m: dict) -> bool:
        seen = False
        for x in self.thread.messages if self.thread else []:
            if x is m:
                seen = True
            elif seen and x.get("type") in VISIBLE:
                return x.get("type") != "assistant"
        return True

    def same_as_live_error(self, m: dict) -> bool:
        t = self.thread
        return bool(t and t.error and t.messages and t.messages[-1] is m)

    # drawing
    async def show(self, thread: S.Thread | None) -> None:
        """Draw a whole thread."""
        self.thread = thread
        self.rows.clear()
        self.dirty.clear()
        self.error_row = self.more = None
        await self.remove_children()
        if thread is None:
            return
        start = max(0, len(thread.messages) - self.window)
        rows = []
        if start:
            self.more = ShowEarlier(f"↑ Show earlier messages ({start})")
            rows.append(self.more)
        for m in thread.messages[start:]:
            row = self.make(m)
            if row is not None:
                self.rows[m["id"]] = row
                rows.append(row)
        if rows:
            await self.mount_all(rows)
        await self.draw_error()
        self.scroll_end(animate=False)
        self.anchor()

    def show_more(self) -> None:
        self.window += WINDOW
        self.release_anchor()
        self.run_worker(self.show(self.thread), exclusive=True, group="transcript")

    def make(self, m: dict) -> Any:
        kind = m.get("type")
        if kind == "user":
            return UserMsg(m)
        if kind == "assistant":
            return AssistantMsg(m, self)
        if kind == "synthetic":
            meta = m.get("metadata") or {}
            notice = meta.get("notice")
            if not notice:
                return None
            label = meta.get("label") or {"goal": "Goal not achieved yet, continuing", "hook": "A stop hook failed, continuing", "todo": "To-do items still open, checking"}.get(notice, "Notice")
            row = Note(label)
            row.set_class(notice == "limit", "-warn")
            return row
        if kind == "compaction":
            return Compaction(m)
        if kind == "model-switched":
            return Note(f"Switched model to {self.model_name(m.get('model')) or 'another model'}")
        if kind == "agent-switched":
            return Note(f"Switched agent to {m.get('agent') or 'another agent'}")
        if kind == "shell":
            output = m.get("output") or ""
            content = [{"type": "text", "text": output}] if output else []
            return ToolRow({"id": m["id"], "name": "shell", "state": {"status": "completed", "input": {"command": m.get("command") or m.get("text") or ""}, "content": content}}, opened=True)
        if kind == "idle" and m.get("outcome") == "failed" and m.get("error"):
            t = self.thread
            if t and t.messages and t.messages[-1] is m and t.error:
                return None
            return ErrorCard(m["error"], self.model_name((t.session if t else {}).get("model")))
        return None

    async def add_new(self) -> None:
        """Mount messages that aren't on screen yet and refresh the ones that may have changed."""
        t = self.thread
        if t is None:
            return
        fresh = []
        for m in t.messages[-self.window:]:
            if m.get("id") in self.rows:
                continue
            row = self.make(m)
            if row is not None:
                self.rows[m["id"]] = row
                fresh.append(row)
        if fresh:
            await self.mount_all(fresh, before=self.error_row) if self.error_row else await self.mount_all(fresh)
        self.dirty.update(k for k, r in self.rows.items() if isinstance(r, (AssistantMsg, UserMsg)))
        await self.draw_error()

    async def draw_error(self) -> None:
        t = self.thread
        if self.error_row is not None:
            await self.error_row.remove()
            self.error_row = None
        if t and t.error:
            self.error_row = ErrorCard(t.error, self.model_name(t.session.get("model")))
            await self.mount(self.error_row)

    def touch(self, mid: str | None) -> None:
        if mid:
            self.dirty.add(mid)

    async def flush(self) -> None:
        """At most twelve screen updates a second, however fast the tokens come."""
        if not self.dirty:
            return
        dirty, self.dirty = self.dirty, set()
        for mid in dirty:
            row = self.rows.get(mid)
            if isinstance(row, AssistantMsg):
                await row.sync()
            elif isinstance(row, UserMsg):
                row.draw()

    def set_details(self, opened: bool) -> None:
        self.show_details = opened
        for row in self.rows.values():
            if isinstance(row, AssistantMsg):
                row.set_details(opened)


def bar(fraction: float, width: int = 20) -> Content:
    filled = round(max(0, min(1, fraction)) * width)
    colour = "$error" if fraction >= 0.9 else "$warning" if fraction >= 0.7 else "$primary"
    return Content.assemble(("█" * filled, colour), ("░" * (width - filled), "$afh-text3"))


__all__ = ["Transcript", "Row", "SPINNER", "logo", "gradient", "diff_content", "plain_block", "bar", "mix"]
