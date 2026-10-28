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
    kind: str = "builtin"  # builtin | custom | delegate | leader

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description, "mode": self.mode, "hidden": self.hidden, "model": self.model,
                "color": self.color, "custom": self.kind == "custom", "delegate": self.kind == "delegate", "leader": self.kind == "leader",
                "system": self.system if self.kind in ("custom", "delegate") else (self.system if store.load_settings().get("prompts", {}).get("agents", {}).get(self.id) else "")}


READONLY_RULES = [{"action": "edit", "resource": "*", "effect": "deny"}, {"action": "shell", "resource": "*", "effect": "deny"}]


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
    ]
    for aid, cfg in (s.get("agents") or {}).items():
        agents.append(AgentConfig(aid, cfg.get("name") or aid.title(), cfg.get("description", ""), cfg.get("mode", "primary"), overrides.get(aid) or cfg.get("system") or base,
                                  _model_ref(cfg.get("model")), READONLY_RULES if cfg.get("readonly") else [], False, cfg.get("color"), "custom"))
    deleg = s.get("delegation", {})
    delegates = [d for d in deleg.get("delegates", []) if d.get("id") and d.get("enabled", True)]
    for d in delegates:
        agents.append(AgentConfig(d["id"], d.get("name") or d["id"], d.get("job", ""), "subagent",
                                  store.DELEGATE_PROMPT.format(name=d.get("name") or d["id"], job=d.get("job", "").strip() or "general tasks", system=("\n" + d["system"].strip()) if d.get("system", "").strip() else ""),
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


def delegate_ids(settings: dict | None = None) -> list[str]:
    return [a.id for a in all_agents(settings) if a.kind == "delegate"]
