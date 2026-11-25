"""A model that ends its turn without an answer.

Sometimes a reply ends with nothing to show for it: the model thought and then said nothing, the
connection closed early, the reply ran into the output limit, or a tool call came out broken or as
plain text. The run used to end there, as if the task were done. Instead the model is sent back with
what happened and the end of its own thinking; after a few tries the user is told, never left guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TRIES = 3  # times in a row the model is sent back
MAX_TOKENS = 32_000  # a reply's limit; grows when a reply runs into it
MAX_TOKENS_TOP = 128_000
KEEP_THOUGHTS = 6000  # characters of its own thinking a stopped model gets back
# A tool call written out as text, in the formats models are trained on, at the very end of the reply.
TEXT_CALL = re.compile(r"(</tool_call>|</function>|</invoke>|</function_calls>|<\|tool_calls?_(section_)?end\|>|<\|tool_call_end\|>|<｜tool▁calls?▁end｜>)\s*$")


@dataclass
class Stall:
    label: str  # what the user sees
    text: str  # what the model is told; empty when it has been sent back often enough


def _said(msg: dict, kind: str) -> str:
    return "\n\n".join(p.get("text", "") for p in msg.get("content", []) if p.get("type") == kind and p.get("text", "").strip()).strip()


class Stalls:
    def __init__(self):
        self.max_tokens = MAX_TOKENS
        self.tries = 0
        self.announced = False  # sent back once for ending on "Now I'll do this:"
        self.spoke = False  # the step before this one already held the answer, next to a to-do update

    def progress(self, msg: dict, calls: list) -> None:
        """The model called tools: whatever held it up is over."""
        self.tries = 0
        self.spoke = bool(_said(msg, "text")) and all(c.name in ("todo", "goal") for c in calls)

    def check(self, msg: dict, worked: bool) -> Stall | None:
        """The model ended its turn without calling a tool. None when that is a real ending."""
        ending = msg.get("ending") or ""
        text, thoughts = _said(msg, "text"), _said(msg, "reasoning")
        broken_call = any(p.get("type") == "tool" for p in msg.get("content", []))
        why = label = ""
        if ending == "refusal":
            return None if text else Stall("The model declined to answer. Rephrase the request, or try another model.", "")
        if ending == "length":
            self.max_tokens = min(MAX_TOKENS_TOP, self.max_tokens * 2)
        if broken_call:
            why, label = "Your last reply ended in the middle of a tool call, so nothing was run.", "The reply was cut off in the middle of a step"
        elif ending == "length":
            why = "Your last reply ran into the output limit" + (". Continue exactly where you stopped, without repeating what you wrote." if text else " while you were still thinking.")
            label = "The reply reached the model's output limit"
        elif ending == "malformed":
            why, label = "Your last tool call was malformed, so nothing was run. Call the tool again with valid arguments.", "The model's tool call came out broken"
        elif ending == "cut":
            why = "The connection closed before your last reply was complete." + (" Continue exactly where you stopped, without repeating what you wrote." if text else "")
            label = "The connection closed before the reply was complete"
        elif TEXT_CALL.search(text or thoughts):
            why, label = "You wrote a tool call as text, so nothing was run. Use a real tool call.", "The model wrote a step as text instead of running it"
        elif not text and not (self.spoke and not thoughts):
            why = "Your last reply ended without an answer and without calling a tool" + (", right after thinking." if thoughts else ".")
            label = "The model stopped after thinking, without an answer" if thoughts else "The model sent an empty reply"
        elif worked and not self.announced and text.endswith((":", "：")):
            self.announced = True
            return Stall("The model stopped before doing what it said. AFH asked it to carry on.",
                         "You ended your turn after announcing a next step, without doing it. Do it now. If the task is finished, say so in a sentence.")
        if not why:
            return None
        self.tries += 1
        if self.tries > TRIES:
            return Stall(f"Stopped: {label[0].lower() + label[1:]}, {self.tries} times in a row. Send a message to continue, or try another model.", "")
        if not text:
            why += (" Don't start over and keep the thinking short: carry on with the task now, by calling the next tool or by writing your answer."
                    " If the task is finished, tell the user what you did in a few sentences.")
            if thoughts:
                why += "\n\nThe end of your own thinking, so you can pick it up:\n<thinking>\n" + thoughts[-KEEP_THOUGHTS:] + "\n</thinking>"
        return Stall(label + ". AFH asked it to carry on.", why)
