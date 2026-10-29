"""The ``question`` tool: the model pauses to ask the user multiple-choice questions.

The questions go to the user as a card (one question at a time, Next / Back / Submit), through the
same pending-request flow as approvals, so they survive a reload and Stop cancels them. Unlike an
approval, a question always waits for the user, in every approval mode. The answers come back as
the tool result and the model carries on in the same run.
"""

from __future__ import annotations

from typing import Any

from .types import PermissionDenied, ToolContext, ToolResult, ToolSpec

MAX_QUESTIONS = 6
MAX_OPTIONS = 8


def clean(raw: Any) -> list[dict]:
    """Validated questions: ``[{question, header, options: [{label, description}], multiple}]``."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("questions must be a non-empty list")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"ask at most {MAX_QUESTIONS} questions at a time")
    out = []
    for i, q in enumerate(raw, 1):
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            raise ValueError(f"question {i} has no text")
        options = []
        for o in q.get("options") or []:
            o = {"label": o} if isinstance(o, str) else o if isinstance(o, dict) else {}
            label = " ".join(str(o.get("label") or "").split())
            if label and label not in (x["label"] for x in options):
                options.append({"label": label[:120], "description": " ".join(str(o.get("description") or "").split())[:300]})
        if len(options) > MAX_OPTIONS:
            raise ValueError(f"question {i} has more than {MAX_OPTIONS} options")
        out.append({"question": str(q["question"]).strip()[:1000], "header": " ".join(str(q.get("header") or "").split())[:30],
                    "options": options, "multiple": bool(q.get("multiple"))})
    return out


def report(questions: list[dict], answers: list) -> tuple[str, list[dict]]:
    """The tool result for the model, and the answers normalised (one per question)."""
    norm = []
    lines = ["The user answered:"]
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) and isinstance(answers[i], dict) else {}
        labels = [o["label"] for o in q["options"]]
        picked = [x for x in a.get("selected") or [] if x in labels]
        other = " ".join(str(a.get("other") or "").split())[:2000]
        norm.append({"selected": picked, "other": other})
        said = ", ".join(picked)
        if other:
            said = f'{said}; wrote: "{other}"' if said else f'wrote: "{other}"'
        lines.append(f"{i + 1}. {q['question']}\n   -> {said or '(no answer)'}")
    lines.append("Continue the work with these answers.")
    return "\n".join(lines), norm


class QuestionTool:
    spec = ToolSpec(
        name="question",
        description=(
            "Pause and ask the user one or more multiple-choice questions; the user picks answers in a card and you get them back, "
            "then you continue. Use it when you are blocked on a decision only the user can make (which approach, which option, "
            "what they prefer, missing requirements) - not for things you can find out by reading the code or running something, and "
            "not for permission to act (approvals happen on their own). Give 2-5 clear options per question, each a short label with "
            "an optional one-line description; put the option you recommend first and add \" (Recommended)\" to its label. Set "
            "multiple: true when several options can apply. The user can always type their own answer instead. Ask related questions "
            "together in one call (up to 6) rather than one call per question."
        ),
        parameters={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_QUESTIONS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "The full question, ending with a question mark."},
                            "header": {"type": "string", "description": "A 1-3 word label for the question (\"Database\", \"Auth\")."},
                            "options": {
                                "type": "array",
                                "maxItems": MAX_OPTIONS,
                                "items": {
                                    "type": "object",
                                    "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
                                    "required": ["label"],
                                },
                            },
                            "multiple": {"type": "boolean", "description": "true = the user may pick several options"},
                        },
                        "required": ["question", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    )

    async def run(self, ctx: ToolContext, input: dict) -> ToolResult:
        try:
            questions = clean(input.get("questions"))
        except ValueError as err:
            return ToolResult(text=f"question: {err}", is_error=True)
        decision, message, answers = await ctx.permissions.ask_user("question", {"title": "The agent has a question", "questions": questions})
        if decision == "reject":  # Stop pressed while the card was open
            raise PermissionDenied(message or "Interrupted")
        if decision == "dismiss" or not answers:
            note = f' They said: "{message}"' if message else ""
            return ToolResult(text="The user closed the questions without answering." + note + " Do not ask the same questions again right away: "
                              "continue with sensible defaults and say what you assumed, or explain in your reply what you need.",
                              metadata={"questions": questions, "dismissed": True})
        text, norm = report(questions, answers)
        return ToolResult(text=text, metadata={"questions": questions, "answers": norm})
