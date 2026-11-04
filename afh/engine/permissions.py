"""Approval rules per thread, and the ask-the-user flow the tools go through."""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Callable

from .types import PermissionDenied, event, new_id

# Thread modes, as ordered rules: the last matching rule wins.
MODE_RULES: dict[str, list[dict]] = {
    "full": [{"action": "*", "resource": "*", "effect": "allow"}],
    "ask": [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "ask"},
        {"action": "shell", "resource": "*", "effect": "ask"},
    ],
    "readonly": [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "deny"},
        {"action": "shell", "resource": "*", "effect": "deny"},
    ],
}
# Sensible defaults on top of every mode: secrets files always ask.
BASE_RULES = [{"action": "read", "resource": "*.env", "effect": "ask"}, {"action": "read", "resource": "*.env.*", "effect": "ask"}]


def rules_for_mode(mode: str) -> list[dict]:
    return [*MODE_RULES.get(mode, MODE_RULES["ask"]), *BASE_RULES]


def mode_of(rules: list[dict]) -> str:
    """Best-effort inverse of rules_for_mode, for the UI's mode pill."""
    effects = {(r.get("action"), r.get("resource")): r.get("effect") for r in rules}
    e = effects.get(("edit", "*"))
    return "readonly" if e == "deny" else "ask" if e == "ask" else "full"


def _match(pattern: str, value: str) -> bool:
    if pattern == "*":
        return True
    value = value.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(value.rsplit("/", 1)[-1], pattern)


def decide(rules: list[dict], action: str, resources: list[str]) -> str:
    """allow | ask | deny for an action on these resources (the strictest across resources)."""
    worst = "allow"
    rank = {"allow": 0, "ask": 1, "deny": 2}
    for res in resources or ["*"]:
        effect = "allow"
        for r in rules:
            if r.get("action") in ("*", action) and _match(str(r.get("resource", "*")), res):
                effect = r.get("effect", "allow")  # last match wins
        if rank[effect] > rank[worst]:
            worst = effect
    return worst


class Gate:
    """One thread's permission gate: evaluates rules and asks the user through the event stream."""

    def __init__(self, session_id: str, rules: list[dict], publish: Callable[[dict], None], pending: dict[str, "Request"], on_rules_changed: Callable[[list[dict]], None]):
        self.session_id = session_id
        self.rules = rules
        self.publish = publish
        self.pending = pending
        self.on_rules_changed = on_rules_changed

    async def require(self, action: str, resources: list[str], metadata: dict | None = None) -> None:
        effect = decide(self.rules, action, resources)
        if effect == "allow":
            return
        if effect == "deny":
            raise PermissionDenied(f"'{action}' is not allowed in this thread (read-only or denied by its rules)")
        req = Request(self.session_id, action, resources, metadata or {})
        self.pending[req.id] = req
        self.publish(event("permission.asked", self.session_id, id=req.id, action=action, resources=resources, metadata=metadata or {}, save=["*"]))
        try:
            decision, message = await req.future
        finally:
            self.pending.pop(req.id, None)
        self.publish(event("permission.replied", self.session_id, id=req.id, decision=decision))
        if decision == "always":
            self.rules = [*self.rules, {"action": action, "resource": "*", "effect": "allow"}]
            self.on_rules_changed(self.rules)
        elif decision == "reject":
            raise PermissionDenied(message or "The user rejected this action.")

    async def ask_user(self, action: str, metadata: dict) -> tuple[str, str | None, list | None]:
        """Always wait for the user, whatever the thread's rules (questions are not permissions).
        Returns (decision, message, answers)."""
        req = Request(self.session_id, action, [], metadata)
        self.pending[req.id] = req
        self.publish(event("permission.asked", self.session_id, id=req.id, action=action, resources=[], metadata=metadata, save=["*"]))
        try:
            decision, message = await req.future
        finally:
            self.pending.pop(req.id, None)
        self.publish(event("permission.replied", self.session_id, id=req.id, decision=decision))
        return decision, message, req.answers


class Request:
    def __init__(self, session_id: str, action: str, resources: list[str], metadata: dict):
        self.id = new_id("per")
        self.session_id = session_id
        self.action = action
        self.resources = resources
        self.metadata = metadata
        self.answers: list | None = None  # what the user picked, for "question" requests
        self.future: asyncio.Future = asyncio.get_event_loop().create_future()

    def to_dict(self) -> dict:
        return {"id": self.id, "sessionID": self.session_id, "action": self.action, "resources": self.resources, "metadata": self.metadata, "save": ["*"]}

    def reply(self, decision: str, message: str | None = None, answers: list | None = None) -> None:
        if not self.future.done():
            self.answers = answers
            self.future.set_result((decision, message))
