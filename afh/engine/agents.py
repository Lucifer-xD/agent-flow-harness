"""Modes and agents: Build, Plan, Delegate (the leader), the user's custom agents, and the
delegates from the Delegation tab. All derived from settings — nothing lives anywhere else."""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import store


@dataclass
class AgentConfig:
    id: str
    name: str
    description: str = ""
    mode: str = "primary"  # primary | subagent | all
    system: str = ""  # full system prompt for this agent
    model: dict | None = None  # {"providerID", "id", "variant"} or None = thread's model
    permissions: list[dict] = field(default_factory=list)  # extra rules appended to the thread's
    hidden: bool = False
    color: str | None = None
    kind: str = "builtin"  # builtin | custom | role (a subagent) | delegate | leader

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description, "mode": self.mode, "hidden": self.hidden, "model": self.model,
                "color": self.color, "custom": self.kind == "custom", "delegate": self.kind == "delegate", "leader": self.kind == "leader", "role": self.kind == "role",
                "system": self.system if self.kind in ("custom", "delegate") else (self.system if store.load_settings().get("prompts", {}).get("agents", {}).get(self.id) else "")}


HELPER_ID = "general"  # the old built-in "Helper" delegate; threads that used it continue as a Coder

READONLY_RULES = [{"action": "edit", "resource": "*", "effect": "deny"}, {"action": "shell", "resource": "*", "effect": "deny"}]
# Red Team audits without changing source: it may read and run (probe the local app), but not edit.
NOEDIT_RULES = [{"action": "edit", "resource": "*", "effect": "deny"}]

# Subagents: in Build, Plan, Red Team and the user's own modes the model can hand a self-contained piece of work
# to a subagent on its own model. Each one has a job (its name in the app), its own instructions and its own
# limits. This is not Delegate mode: there a leader hands work to the cheaper models from the Delegation tab.
ROLES: list[dict] = [
    {"id": "explorer", "name": "Explorer", "color": "#3b82f6", "rules": READONLY_RULES,
     "job": "Finds things in the codebase: where something is defined or used, how a feature is wired, which files matter for a change. Read-only.",
     "how": "Search widely and in parallel (grep, glob, read several files in one step), follow the trail to the real answer, and stop as soon as you have it. "
            "Report file paths with line numbers and the few lines that prove each point; no essays, no proposals unless asked."},
    {"id": "researcher", "name": "Researcher", "color": "#8b5cf6", "rules": READONLY_RULES,
     "job": "Looks things up outside the code: documentation, APIs, versions, error messages, facts that must be checked against primary sources. Read-only.",
     "how": "Prefer primary sources (official docs, specifications, the project's own repository, original papers) over blogs and summaries. "
            "Check each claim you report; say how sure you are and give the link for every fact. When sources disagree, say so instead of picking one silently."},
    {"id": "coder", "name": "Coder", "color": "#f97316", "rules": [],
     "job": "Implements a change: writes and edits code, runs it, and fixes what breaks, within the brief it is given.",
     "how": "Read the code you are about to change and follow the project's existing style. Make the change completely (no TODOs, no stubs), "
            "then build or run the relevant tests and fix what fails. Stay inside the brief: no unrelated refactors."},
    {"id": "tester", "name": "Tester", "color": "#10b981", "rules": [],
     "job": "Proves whether something works: runs the tests and the app, reproduces bugs step by step, and writes missing tests. Does not change product code.",
     "how": "Run the real thing (test suite, app, script) rather than reasoning about it. For a bug, find the smallest reproduction and the exact error. "
            "You may add or fix tests; do not change product code - report what is broken instead, with the evidence."},
    {"id": "reviewer", "name": "Reviewer", "color": "#e5484d", "rules": NOEDIT_RULES,
     "job": "Reviews finished work for bugs, regressions, security holes and missed requirements. May run tests; never edits.",
     "how": "Read every changed line and the code around it. Look for real defects: wrong logic, edge cases, broken callers, missing error handling, "
            "security problems, requirements the change misses. Run the tests if they exist. Report each finding with file:line, why it is wrong "
            "and how to fix it, most serious first. Say plainly when you find nothing serious; never pad the list."},
    {"id": "writer", "name": "Writer", "color": "#eab308", "rules": [],
     "job": "Writes and edits text: documentation, READMEs, changelogs, release notes, UI copy, comments.",
     "how": "Write for the reader named in the brief: plain words, short sentences, concrete examples, accurate to the code (check it). "
            "Keep the document's existing structure and tone unless the brief says otherwise."},
]
ROLE_IDS = [r["id"] for r in ROLES]


def _model_ref(m: dict | str | None) -> dict | None:
    if not m:
        return None
    if isinstance(m, dict):
        return {"providerID": m.get("providerID"), "id": m.get("id"), "variant": m.get("variant")} if m.get("id") and m.get("providerID") else None
    if "/" in m:
        pid, rest = m.split("/", 1)
        mid, _, variant = rest.partition("#")
        return {"providerID": pid, "id": mid, "variant": variant or None}
    return None


def all_agents(settings: dict | None = None) -> list[AgentConfig]:
    s = settings or store.load_settings()
    base = store.system_prompt(s)
    overrides = s.get("prompts", {}).get("agents", {})
    agents: list[AgentConfig] = [
        AgentConfig("build", "Build", "The default mode. Reads, edits and runs code in the project.", "primary", overrides.get("build") or base),
        AgentConfig("plan", "Plan", "Investigates and proposes a plan without changing anything.", "primary", overrides.get("plan") or (base + store.PLAN_RULES), permissions=READONLY_RULES),
        AgentConfig("redteam", "Red Team", "Security audit of your own project: finds exploitable weaknesses (auth/OTP, access control, injection, secrets) and reports fixes. Does not change code.",
                    "primary", overrides.get("redteam") or (base + store.REDTEAM_RULES), permissions=NOEDIT_RULES, color="#e5484d"),
    ]
    for aid, cfg in (s.get("agents") or {}).items():
        agents.append(AgentConfig(aid, cfg.get("name") or aid.title(), cfg.get("description", ""), cfg.get("mode", "primary"), overrides.get(aid) or cfg.get("system") or base,
                                  _model_ref(cfg.get("model")), READONLY_RULES if cfg.get("readonly") else [], False, cfg.get("color"), "custom"))
    deleg = s.get("delegation", {})
    taken = {a.id for a in agents}
    if subagents_on(s):
        for r in ROLES:
            if r["id"] in taken:
                continue
            body = store.ROLE_PROMPT.format(name=r["name"], job=r["job"], how=r["how"])
            agents.append(AgentConfig(r["id"], r["name"], r["job"], "subagent", base.strip() + "\n\n# You are a subagent\n\n" + body,
                                      None, list(r["rules"]), False, r["color"], "role"))
    delegates = [d for d in deleg.get("delegates", []) if d.get("id") and d.get("enabled", True) and d["id"] not in taken]
    for d in delegates:
        rules = store.DELEGATE_PROMPT.format(name=d.get("name") or d["id"], job=d.get("job", "").strip() or "general tasks", system=("\n" + d["system"].strip()) if d.get("system", "").strip() else "")
        # A delegate works like any agent (same tools and habits), plus the rules of being delegated to.
        agents.append(AgentConfig(d["id"], d.get("name") or d["id"], d.get("job", ""), "subagent", base.strip() + "\n\n# You are a delegate\n\n" + rules,
                                  _model_ref(d.get("model")), READONLY_RULES if d.get("readonly") else [], False, d.get("color"), "delegate"))
    agents.append(AgentConfig(store.LEADER_ID, "Delegate", "Leads the work and delegates tasks to your delegate models.", "primary",
                              overrides.get(store.LEADER_ID) or store.leader_prompt(delegates, deleg.get("leaderInstructions", "")), None, [], False, "#ff6a2a", "leader"))
    return agents


def get_agent(aid: str | None, settings: dict | None = None) -> AgentConfig:
    agents = all_agents(settings)
    for a in agents:
        if a.id == (aid or "build"):
            return a
    return agents[0]


def subagents_on(settings: dict | None = None) -> bool:
    """The Subagents switch (Settings → Delegation; stored under its old name, builtinHelper)."""
    return (settings or store.load_settings()).get("delegation", {}).get("builtinHelper", True) is not False


def delegate_ids(settings: dict | None = None) -> list[str]:
    return [a.id for a in all_agents(settings) if a.kind == "delegate"]


def subagent_ids(settings: dict | None = None) -> list[str]:
    """Who a thread outside Delegate mode can start: the built-in roles and the user's own agents marked as subagents."""
    return [a.id for a in all_agents(settings) if a.kind == "role" or (a.kind == "custom" and a.mode in ("subagent", "all"))]
