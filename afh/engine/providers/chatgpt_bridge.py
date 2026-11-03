"""Emulated tool calling for the ChatGPT web backend, which has none.

The backend cannot accept tool schemas or emit tool calls, so we teach the chat model a
plain text protocol: the harness describes the tools in a preamble, the model answers with
``<tool_call>{json}</tool_call>`` blocks when it wants to act, we parse those blocks out of
the reply and surface them to the engine as ordinary tool calls, and tool results go back as
``<tool_response>`` text on the next turn. This is a faithful port of shadowgate's
``src/tools.ts`` (the protocol wording and the many edge cases were tuned against real models).

The provider (``chatgpt_web.py``) uses this to present the normal Provider interface, so AFH's
agent loop drives the full harness through a model that is "just a chat".
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from afh.engine.types import ChatMessage, ToolSpec

OPEN = "<tool_call>"
CLOSE = "</tool_call>"


def tool_preamble(tools: list[ToolSpec], choice: Any = None) -> str:
    """The briefing that makes a chat model use the protocol. Delivered inside the first user
    message (system/critic channels were ignored by some models). One worked example is essential."""
    first = tools[0].name if tools else "action_name"
    lines = [
        "# Harness protocol (read carefully)",
        "",
        "You are the reasoning engine of an agent that runs on the USER'S machine. You have no native "
        "tools for that machine; instead, the agent harness reads your reply text and executes any action "
        "blocks it finds, then sends you the output in the next message. This is purely a text protocol: "
        "emitting the block IS performing the action. It is not a hallucinated capability and it is not a "
        "native ChatGPT tool — it works because the harness parses your text.",
        "",
        "Actions the harness can execute for you:",
    ]
    for t in tools:
        params = json.dumps(t.parameters, ensure_ascii=False) if t.parameters else "{}"
        desc = f" — {' '.join((t.description or '').split())}" if t.description else ""
        lines.append(f"- {t.name}{desc}. Arguments (JSON Schema): {params[:6000] + '…' if len(params) > 6000 else params}")
    lines += [
        "",
        "To request an action, write a block exactly like this (one block per action; you may write a short "
        "sentence before the first block, and several blocks when the actions are independent):",
        OPEN,
        f'{{"name": "{first}", "arguments": {{"param": "value"}}}}',
        CLOSE,
        "Then END your reply and wait. The harness executes it and replies with one entry per block, in order:",
        '<tool_response name="action_name">',
        "...output...",
        "</tool_response>",
        "After that you continue: request more actions, or answer the user.",
        "",
        "Example exchange:",
        "User: how many lines does the notes file have?",
        "Assistant: Let me check.",
        OPEN,
        f'{{"name": "{first}", "arguments": {{"example": "value"}}}}',
        CLOSE,
        f'User: <tool_response name="{first}">',
        "42",
        "</tool_response>",
        "Assistant: 42 lines.",
        "",
        "Rules: never answer questions about the user's files, system, environment or anything on their side "
        "from memory or from any sandbox of your own — request the action. Never say an action is unavailable; "
        "if you need it, emit the block. Never just announce an action (\"I'll read…\", \"Let me check…\", "
        "\"I need to run…\") — include the block in the SAME reply, right after the sentence. Keep every "
        "\"arguments\" value a JSON object that matches the schema. You have NO Python sandbox, code interpreter, "
        "canvas, browser or image tool of your own here — anything you run there is discarded and the user never "
        "sees it; the ONLY way to run code, read files or produce output on the user's side is a <tool_call> block. "
        "A failed action is normal, not a blocker: read the error in the <tool_response>, correct the command or "
        "path, and request it again (up to a few attempts) — never stop a task because one action failed, and never "
        "describe yourself as blocked by the harness. When no action is needed, or once you have the results you "
        "need, answer normally without any block.",
    ]
    if choice == "required":
        lines.append("For THIS turn you must request at least one action.")
    elif isinstance(choice, dict) and choice.get("name"):
        lines.append(f"For THIS turn you must request the action \"{choice['name']}\".")
    return "\n".join(lines)


def transform_history(messages: list[ChatMessage]) -> list[dict]:
    """AFH messages → conversation turns [{role, text, images}] in the text protocol.

    Assistant tool calls become ``<tool_call>`` blocks appended to the assistant text; tool
    results become ``<tool_response>`` user turns (consecutive results collapse into one)."""
    out: list[dict] = []
    for m in messages:
        if m.role == "assistant":
            text = m.text or ""
            for c in m.tool_calls:
                block = OPEN + "\n" + json.dumps({"name": c.name, "arguments": c.input}, ensure_ascii=False) + "\n" + CLOSE
                text = (text + "\n" + block) if text else block
            out.append({"role": "assistant", "text": text, "images": []})
        elif m.role == "tool":
            name = getattr(m, "tool_name", "") or ""
            header = f"<tool_response{f' name=\"{name}\"' if name else ''}{f' id=\"{m.tool_call_id}\"' if m.tool_call_id else ''}>"
            block = f"{header}\n{m.text or ''}\n</tool_response>"
            prev = out[-1] if out else None
            if prev and prev["role"] == "user" and prev["text"].startswith("<tool_response"):
                prev["text"] += "\n" + block
            else:
                out.append({"role": "user", "text": block, "images": []})
        elif m.role == "system":
            out.append({"role": "critic", "text": m.text or "", "images": []})
        else:  # user
            out.append({"role": "user", "text": m.text or "", "images": list(m.images or [])})
    return out


def inject_preamble(turns: list[dict], preamble: str, tool_names: list[str]) -> list[dict]:
    """Fold the protocol preamble into the first user turn, and a short reminder onto the last."""
    first = next((i for i, t in enumerate(turns) if t["role"] == "user"), -1)
    if first == -1:
        turns = [{"role": "user", "text": preamble, "images": []}, *turns]
        first = 0
    else:
        turns[first] = {**turns[first], "text": f"{preamble}\n\n---\n\n{turns[first]['text']}"}
    last = len(turns) - 1
    if last > first and turns[last]["role"] == "user":
        body = turns[last]["text"]
        names = ", ".join(tool_names)
        hint = cappedHint(body) if body.startswith("<tool_response") else None
        capped = ""
        if hint:
            capped = (f" One result above was cut short by the tool itself (\"{hint['line']}\"). That is a page limit, "
                      f"not a failure: if the task needs the rest, request the next part ({hint['next']}) and keep going "
                      "until you have it, then answer. Never answer from a partial result as if it were the whole.")
        turns[last] = {**turns[last], "text": (
            f"{body}\n\n[Harness reminder: you act on the user's machine ONLY by replying with <tool_call> blocks "
            f"(actions: {names or 'see above'}). Your own sandbox or browser is not their machine. The protocol is "
            f"always available; never say it is not. If an action failed, fix it and request it again.{capped} When "
            "nothing more is needed, answer normally.]")}
    return turns


# ---- parsing the model's reply --------------------------------------------------------------

def _quoted_ranges(text: str) -> list[tuple[int, int]]:
    """Fenced regions that merely QUOTE the protocol must not be executed; a fence whose whole body
    is a tool_call block is still a real call (models sometimes wrap calls in ```)."""
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"```[^\n]*\n([\s\S]*?)```", text):
        body = m.group(1).strip()
        only = body.startswith(OPEN) and body.endswith(CLOSE) and OPEN not in body[len(OPEN):len(body) - len(CLOSE)]
        if not only and OPEN in body:
            out.append((m.start(), m.end()))
    return out


def _find_json_object_end(text: str, frm: int) -> int:
    """Index just past the JSON object that starts (after optional whitespace / ```json fence) at frm, or -1."""
    i = frm
    fence = re.match(r"\s*```(?:json)?\s*", text[frm:])
    if fence:
        i += fence.end()
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] != "{":
        return -1
    depth = 0
    in_str = False
    k = i
    while k < len(text):
        ch = text[k]
        if in_str:
            if ch == "\\":
                k += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return -1


def lenient_json(src: str) -> Any:
    """json.loads that forgives what models produce: lone backslashes (Windows paths), trailing commas, truncation."""
    candidates = [src, re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", src), re.sub(r",\s*([}\]])", r"\1", src)]
    for c in candidates:
        try:
            return json.loads(c)
        except ValueError:
            pass
        end = c.rfind("}")
        if end != -1:
            try:
                return json.loads(c[:end + 1])
            except ValueError:
                pass
    return None


def _parse_call(inner: str) -> dict | None:
    s = re.sub(r"\s*```$", "", re.sub(r"^```(?:json)?\s*", "", inner.strip(), flags=re.I)).strip()
    if not s:
        return None
    obj = lenient_json(s)
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or (obj.get("function") or {}).get("name") or obj.get("tool")
    if not isinstance(name, str) or not name:
        return None
    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = (obj.get("function") or {}).get("arguments")
    if args is None:
        args = obj.get("input")
    if args is None:
        args = {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"input": args}
    raw = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
    return {"id": "call_" + uuid.uuid4().hex[:24], "name": name, "input": args if isinstance(args, dict) else {"input": args}, "raw": raw}


def extract_tool_calls(text: str) -> tuple[str, list[dict]]:
    """Parse every complete (or trailing unterminated) tool_call block out of a reply.
    Returns (visible_text, calls); each call is {id, name, input(dict), raw(json str)}."""
    calls: list[dict] = []
    quoted = _quoted_ranges(text)
    is_quoted = lambda pos: any(a <= pos < b for a, b in quoted)
    rest = ""
    i = 0
    while i < len(text):
        open_at = text.find(OPEN, i)
        if open_at == -1:
            rest += text[i:]
            break
        if is_quoted(open_at):
            rest += text[i:open_at + len(OPEN)]
            i = open_at + len(OPEN)
            continue
        rest += text[i:open_at]
        body_start = open_at + len(OPEN)
        obj_end = _find_json_object_end(text, body_start)
        if obj_end != -1:
            inner = text[body_start:obj_end]
            after = text.find(CLOSE, obj_end)
            nxt = after + len(CLOSE) if after != -1 and re.fullmatch(r"\s*(?:```)?\s*", text[obj_end:after]) else obj_end
        else:
            close = text.find(CLOSE, body_start)
            inner = text[body_start:] if close == -1 else text[body_start:close]
            nxt = len(text) if close == -1 else close + len(CLOSE)
        parsed = _parse_call(inner)
        if parsed:
            calls.append(parsed)
        elif nxt < len(text) or obj_end != -1:
            rest += text[open_at:nxt]
        i = max(nxt, body_start)
    clean = re.sub(r"\n{3,}", "\n\n", re.sub(r"```(?:json)?\s*```", "", rest)).strip()
    return clean, calls


# ---- nudging: the model announced an action but emitted no block ----------------------------

_INTENT_VERBS = (r"read|check|run|list|look|inspect|open|fetch|execute|search|verify|call|use|request|need|issue|emit|"
                 r"send|provide|perform|access|retry|try|attempt|create|write|delete|remove|fix|correct|continue|proceed|redo|rerun")


def looks_like_unfulfilled_intent(text: str) -> bool:
    """A reply that announces an action but contains no block ("Let me read the file.")."""
    t = text.strip()
    if not t:
        return True
    if len(t) > 700 or t.endswith("?"):
        return False
    if len(t) < 200 and len(re.findall(r"\b(command|result|output|file|files|harness|tool|action|block|protocol)\b", t, re.I)) >= 2:
        return True
    if re.search(r"\b(can['’]?t|cannot|unable to|not able to)\s+(truthfully |honestly |reliably |actually |really |yet )?"
                 r"(verify|confirm|check|read|inspect|retrieve|access|complete|perform|carry out|execute|create|write|delete|modify|edit)\b"
                 r"(?!\s+(?:any|anything|no)\b)", t, re.I):
        return True
    if re.search(r"\b(can['’]?t|cannot|unable|not able|isn['’]?t available|not available|no longer available|not exposed|"
                 r"stopped being|not executable|no access|don['’]?t have access|blocked|stuck)\b", t, re.I) and \
       re.search(r"\b(harness|blocks?|actions?|tools?|functions?|interface|protocol|sequence|steps?|machine|computer|pc|commands?)\b", t, re.I):
        return True
    return bool(re.search(r"\b(i(?:['’]ll| will| need| can| would| should| am going to)|let me|need to|going to|harness action|the action|i['’]d need)\b", t, re.I)
                and re.search(rf"\b({_INTENT_VERBS})\b", t, re.I))


def looks_like_short_announcement(text: str) -> bool:
    """A short mid-loop reply that reads like a lead-in to an action ("Retrying with -Path.")."""
    t = text.strip()
    if not t or len(t) >= 240 or re.search(r"\?\s*$", t):
        return False
    return bool(re.search(r"\b(i['’]ll|i will|i['’]m going|let me|going to|need to|needs? to|will now|now i|next[, ]|retry(?:ing)?|"
                          r"re-?run(?:ning)?|trying|checking|reading|running|listing|looking|inspecting|fetching|verifying|"
                          r"continuing|proceeding|one moment|hold on|stand by)\b", t, re.I))


_CONTINUE_HINT = re.compile(r"^.*\b[Uu]se\s+([a-z_]+\s*=\s*\d+)\s+to continue\b.*$", re.M)


def cappedHint(text: str) -> dict | None:
    """A tool result the tool cut short with its own way to fetch the rest ("Use offset=1547 to continue.")."""
    m = _CONTINUE_HINT.search(text)
    if not m:
        return None
    return {"line": m.group(0).strip().strip("()")[:200], "next": re.sub(r"\s+", "", m.group(1))}


NUDGE_MESSAGE = ("Your last reply contained no <tool_call> block, so nothing happened on the user's machine. If the task "
                 "is not finished, reply now with ONLY the <tool_call> block(s) for the next action, in the exact protocol "
                 "format. If the task is finished, give the complete final answer now.")
NUDGE_EMPTY_MESSAGE = ("Your last turn produced no reply text and no <tool_call> block — nothing reached the user. If you used "
                       "a built-in sandbox, code interpreter, canvas or image tool, it does not exist here and its output was "
                       "discarded. Do the step through the harness: reply now with ONLY the <tool_call> block(s) for the next "
                       "action, in the exact protocol format. If the task is finished, give the complete final answer in plain text.")


class ToolCallSplitter:
    """Streaming helper: lets visible text through until a tool_call block starts, holding back a
    partially-typed ``<tool_call>`` opener so it is never leaked to the user."""

    def __init__(self) -> None:
        self.buf = ""
        self.held = ""
        self.in_call = False
        self.emitted = ""

    def push(self, delta: str) -> str:
        self.buf += delta
        if self.in_call:
            return ""
        pending = self.held + delta
        open_at = pending.find(OPEN)
        if open_at != -1:
            self.in_call = True
            self.held = ""
            out = pending[:open_at].rstrip()
            self.emitted += out
            return out
        keep = 0
        for n in range(min(len(OPEN) - 1, len(pending)), 0, -1):
            if OPEN.startswith(pending[len(pending) - n:]):
                keep = n
                break
        self.held = pending[len(pending) - keep:] if keep else ""
        out = pending[:len(pending) - keep] if keep else pending
        self.emitted += out
        return out

    def finish(self) -> tuple[str, list[dict], str]:
        """At end of stream: (full_visible_text, calls, unsent_tail)."""
        text, calls = extract_tool_calls(self.buf)
        sent = self.emitted.strip()
        unsent = ""
        if text.startswith(sent):
            unsent = text[len(sent):].lstrip()
        elif not calls:
            unsent = self.held
        self.held = ""
        return text, calls, unsent

    @property
    def saw_call(self) -> bool:
        return self.in_call
