// Settings window: appearance, personalization, providers/models, MCP, plugins, prompts & agents.

import { api, native } from "./api.js";
import { basename, confirmDialog, el, fmtTokens, ico, icon, modal, toast, toggle } from "./ui.js";

const TABS = [
  ["general", "General", "sliders"],
  ["personalization", "Personalization", "user"],
  ["models", "Models & providers", "cpu"],
  ["mcp", "MCP servers", "plug"],
  ["plugins", "Plugins & skills", "puzzle"],
  ["prompts", "Prompts & agents", "scroll"],
  ["about", "About", "info"],
];
const ACCENTS = ["#7c6cff", "#4f8cff", "#22b8cf", "#2fbf71", "#f59f00", "#ff6b6b", "#e64980", "#a3a3b5"];
const RESTART_NOTE = "Saving restarts OpenCode for a few seconds. Threads that are running will stop.";

let instance = null;

export function openSettings(tab = "general", ctx, opts = {}) {
  if (instance) {
    instance.show(tab, opts);
    return;
  }
  const nav = el("nav.m-nav", el("h3", "Settings"));
  const body = el("div.m-body");
  const buttons = {};
  for (const [id, label, ic] of TABS) {
    buttons[id] = el("button", { type: "button", on: { click: () => show(id) } }, ico(ic), label);
    nav.append(buttons[id]);
  }
  nav.append(el("div.spacer"), el("div.h-muted", { style: { padding: "0 10px", fontStyle: "normal", fontSize: "11.5px" } }, "Changes save automatically unless a Save button is shown."));
  let current = null;
  const show = async (id, o = {}) => {
    current = id;
    Object.entries(buttons).forEach(([k, b]) => b.classList.toggle("on", k === id));
    const pane = el("div.m-pane");
    body.replaceChildren(el("button.icon-btn.m-close", { title: "Close (Esc)", html: icon("x"), on: { click: () => m.close() } }), pane);
    try {
      await PANES[id](pane, ctx, o);
    } catch (e) {
      pane.append(el("div.error-card", ico("alert"), el("div", e.message)));
    }
  };
  const m = modal([nav, body], {
    onClose: () => {
      instance = null;
      ctx.onReady = null;
      ctx.onCatalogEvent = null;
    },
  });
  ctx.onReady = () => current && ["models", "mcp", "plugins", "prompts"].includes(current) && show(current);
  let timer = 0;
  ctx.onCatalogEvent = () => {
    if (current !== "mcp" && current !== "plugins") return;
    clearTimeout(timer);
    timer = setTimeout(() => show(current), 900);
  };
  instance = { show };
  show(tab, opts);
}

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const card = (title, sub, action, ...children) =>
  el("div.card", el("div.card-head", el("div", el("h3", title), sub ? el("p", sub) : null), action || null), ...children);
const row = (title, sub, control) => el("div.row", el("div.rl", el("b", title), sub ? el("span", sub) : null), control);
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);

function seg(options, value, onChange) {
  const box = el("div.seg");
  for (const [v, label] of options) {
    box.append(el(`button${v === value ? ".on" : ""}`, { type: "button", on: { click: () => { box.querySelectorAll("button").forEach((b) => b.classList.remove("on")); box.querySelector(`[data-v="${CSS.escape(String(v))}"]`).classList.add("on"); onChange(v); } }, dataset: { v } }, label));
  }
  return box;
}

async function guard(fn, okMsg) {
  try {
    const out = await fn();
    if (out?.restarting) toast("Saved — restarting OpenCode…", "ok");
    else if (okMsg) toast(okMsg, "ok");
    return out;
  } catch (e) {
    toast(e.message, "err", 5000);
    return null;
  }
}

// ---- panes ---------------------------------------------------------------------

const PANES = {
  async general(pane, ctx) {
    const s = ctx.S.settings;
    const save = (patch) => ctx.saveSettings(patch).catch((e) => toast(e.message, "err"));
    const ui = (k) => (v) => save({ ui: { [k]: v } });
    const custom = el("input", { type: "color", value: s.ui.accent, title: "Custom color", style: { width: "30px", height: "30px", border: "0", background: "none", padding: "0", cursor: "pointer" } });
    const swatches = el("div.swatches", ACCENTS.map((c) => el(`button.swatch${c === s.ui.accent ? ".on" : ""}`, { type: "button", style: { background: c }, on: { click: (e) => pickAccent(c, e.currentTarget) } })), custom);
    const pickAccent = (c, btn) => {
      swatches.querySelectorAll(".swatch").forEach((b) => b.classList.remove("on"));
      btn?.classList.add("on");
      save({ ui: { accent: c } });
    };
    custom.addEventListener("input", () => pickAccent(custom.value));
    const size = el("input", { type: "range", min: 12, max: 18, step: 1, value: s.ui.fontSize, style: { width: "160px", accentColor: "var(--accent)" } });
    const sizeLbl = el("span.h-muted", { style: { fontStyle: "normal", width: "40px", textAlign: "right" } }, `${s.ui.fontSize}px`);
    size.addEventListener("input", () => { sizeLbl.textContent = `${size.value}px`; document.documentElement.style.setProperty("--fs", `${size.value}px`); });
    size.addEventListener("change", () => save({ ui: { fontSize: Number(size.value) } }));
    const agents = ctx.S.agents.filter((a) => !a.hidden && a.mode !== "subagent");
    const agentSel = el("select.sel", { style: { width: "200px" }, on: { change: (e) => save({ defaultAgent: e.target.value }) } }, agents.map((a) => el("option", { value: a.id, selected: a.id === s.defaultAgent }, a.name)));

    pane.append(...header("General", "How AFH looks and behaves."),
      card("Appearance", null, null,
        row("Theme", null, seg([["system", "System"], ["dark", "Dark"], ["light", "Light"]], s.ui.theme, ui("theme"))),
        row("Accent color", null, swatches),
        row("Text size", null, el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, size, sizeLbl)),
        row("Density", null, seg([["comfortable", "Comfortable"], ["compact", "Compact"]], s.ui.density, ui("density"))),
        row("Animations", "Motion for messages, panels and menus", toggle(s.ui.animations, ui("animations")))),
      card("Conversation", null, null,
        row("Show thinking", "Display the model's reasoning when it shares it", toggle(s.ui.showReasoning, ui("showReasoning"))),
        row("Send with", null, seg([["enter", "Enter"], ["ctrl-enter", "Ctrl + Enter"]], s.ui.sendKey, ui("sendKey"))),
        row("Default approval mode", "For new threads", seg([["ask", "Ask first"], ["full", "Full access"], ["readonly", "Read only"]], s.defaultMode, (v) => save({ defaultMode: v }))),
        row("Default agent", "For new threads", agentSel)));
  },

  async personalization(pane, ctx) {
    const p = { ...ctx.S.settings.personalization };
    const inp = (k, ph) => el("input.inp", { value: p[k] || "", placeholder: ph, on: { input: (e) => { p[k] = e.target.value; dirty(); } } });
    const ta = (k, ph, rows = 4) => el("textarea.ta", { rows, value: p[k] || "", placeholder: ph, on: { input: (e) => { p[k] = e.target.value; dirty(); } } });
    const saveBtn = el("button.btn.primary", { disabled: true, on: { click: async () => {
      await guard(() => ctx.saveSettings({ personalization: p }), "Personalization saved — applies to the next message");
      saveBtn.disabled = true;
    } } }, "Save");
    const dirty = () => (saveBtn.disabled = false);
    pane.append(...header("Personalization", "Tell the agent about you and how you like to work. AFH writes this to an instructions file every thread reads."),
      card("Use personalization", "Turn off to send none of this to the model", toggle(p.enabled, (v) => { p.enabled = v; dirty(); })),
      card("About you", null, null, el("div.card-body",
        el("div.grid2", field("What should it call you?", inp("name", "Alex")), field("What do you do?", inp("role", "Full-stack developer"))),
        field("Anything else it should know?", ta("about", "I mostly work in TypeScript and Python. I prefer small, focused commits.")))),
      card("How it responds", null, null, el("div.card-body",
        field("Response length", seg([["concise", "Concise"], ["balanced", "Balanced"], ["detailed", "Detailed"]], p.style, (v) => { p.style = v; dirty(); })),
        field("Tone", inp("tone", "friendly, direct, no emoji")),
        field("Custom instructions", ta("instructions", "Always run the test suite before saying you're done.\nUse pnpm, not npm.", 6), "Plain text or Markdown. Added to every thread's instructions."))),
      el("div.actions", saveBtn));
  },

  async models(pane, ctx) {
    const S = ctx.S;
    pane.append(...header("Models & providers", "Connect any provider OpenCode supports, or your own OpenAI- or Anthropic-compatible endpoint (Ollama, LM Studio, vLLM…)."));
    const def = S.settings.defaultModel || S.defaultModel;
    const sel = el("select.sel", { style: { width: "320px" }, on: { change: (e) => {
      const [providerID, ...rest] = e.target.value.split("/");
      ctx.saveSettings({ defaultModel: { providerID, id: rest.join("/") } }).then(() => toast("Default model saved", "ok"));
    } } });
    for (const m of S.models) sel.append(el("option", { value: `${m.providerID}/${m.id}`, selected: def && def.id === m.id && def.providerID === m.providerID }, `${m.name}  —  ${m.providerID}`));
    pane.append(card("Default model", `${S.models.length} models available from your connected providers`, sel));

    const data = await api.get("/api/providers");
    const connected = data.integrations.filter((i) => i.credentials.length);
    const list = el("div");
    for (const i of connected) {
      for (const c of i.credentials) {
        list.append(el("div.list-item",
          el("span.status-dot", { className: `status-dot ${c.active ? "active" : ""}` }),
          el("div.li-main", el("div.li-title", i.name, c.active ? el("span.pill-tag.accent", "active") : el("span.pill-tag", "inactive")), el("div.li-sub", `${c.label || "credential"} · ${c.hint || c.type}`)),
          !c.active ? el("button.btn.sm", { on: { click: () => guard(() => api.post(`/api/credentials/${c.id}/activate`), "Activated").then(() => ctx.reloadCatalog().then(() => PANES.redraw("models"))) } }, "Activate") : null,
          el("button.btn.ghost.sm.danger", { title: "Remove key", on: { click: async () => {
            if (!(await confirmDialog({ title: `Remove ${i.name} key?`, body: "Models from this provider stop working until you add a key again.", confirm: "Remove", danger: true }))) return;
            await guard(() => api.del(`/api/credentials/${c.id}`), "Key removed");
            await ctx.reloadCatalog();
            PANES.redraw("models");
          } } }, ico("trash"))));
      }
    }
    if (!connected.length) list.append(el("div.empty-row", "No providers connected yet."));

    // connect flow
    const search = el("input.inp", { placeholder: `Search ${data.integrations.length} providers…` });
    const results = el("div", { style: { maxHeight: "220px", overflowY: "auto", marginTop: "8px" } });
    const keyForm = el("div");
    const drawResults = () => {
      const q = search.value.toLowerCase();
      results.replaceChildren(...data.integrations.filter((i) => i.methods.includes("key") && (!q || `${i.name} ${i.id}`.toLowerCase().includes(q))).slice(0, 40).map((i) =>
        el("button.pop-item", { type: "button", on: { click: () => showKeyForm(i) } }, el("div.pi-main", el("div.pi-title", i.name), el("div.pi-sub", i.env.length ? `or set ${i.env[0]}` : i.id)), i.credentials.length ? el("span.pill-tag.accent", "connected") : null)));
    };
    const showKeyForm = (i) => {
      const key = el("input.inp", { type: "password", placeholder: "Paste API key", autocomplete: "off" });
      const label = el("input.inp", { placeholder: "Label (optional)" });
      keyForm.replaceChildren(el("div.inline-form",
        el("div", { style: { fontWeight: 600, marginBottom: "10px" } }, `Connect ${i.name}`),
        el("div.grid2", field("API key", key), field("Label", label)),
        el("div.help", { style: { fontSize: "12px", color: "var(--text-3)", marginBottom: "10px" } }, "Stored by OpenCode in its own credential store, not in AFH's files."),
        el("div.actions", el("button.btn.ghost", { on: { click: () => keyForm.replaceChildren() } }, "Cancel"),
          el("button.btn.primary", { on: { click: async () => {
            const ok = await guard(() => api.post("/api/credentials", { integrationID: i.id, key: key.value, label: label.value }), `${i.name} connected`);
            if (ok) { await ctx.reloadCatalog(); PANES.redraw("models"); }
          } } }, "Connect"))));
      setTimeout(() => key.focus(), 20);
    };
    search.addEventListener("input", drawResults);
    drawResults();
    pane.append(card("Connected providers", "API keys OpenCode uses", null, list),
      card("Connect a provider", null, null, el("div.card-body", search, results), keyForm));

    // custom endpoints
    const customList = el("div");
    for (const [id, p] of Object.entries(data.custom || {})) {
      customList.append(el("div.list-item", ico("globe"),
        el("div.li-main", el("div.li-title", p.name || id, el("span.pill-tag", id)), el("div.li-sub", `${p.settings?.baseURL || ""} · ${Object.keys(p.models || {}).join(", ")}`)),
        el("button.btn.ghost.sm.danger", { on: { click: async () => {
          if (!(await confirmDialog({ title: `Remove ${p.name || id}?`, body: RESTART_NOTE, confirm: "Remove", danger: true }))) return;
          guard(() => api.del(`/api/providers/custom/${id}`));
        } } }, ico("trash"))));
    }
    if (!customList.childElementCount) customList.append(el("div.empty-row", "None yet."));
    const f = { id: el("input.inp", { placeholder: "ollama-local" }), name: el("input.inp", { placeholder: "Ollama (local)" }), baseURL: el("input.inp", { placeholder: "http://localhost:11434/v1" }), apiKey: el("input.inp", { type: "password", placeholder: "optional", autocomplete: "off" }), models: el("input.inp", { placeholder: "qwen3-coder:30b, llama4:scout" }) };
    let kind = "openai";
    const form = el("div.inline-form", { hidden: true },
      field("API format", seg([["openai", "OpenAI-compatible"], ["anthropic", "Anthropic-compatible"]], kind, (v) => (kind = v))),
      el("div.grid2", field("Provider id", f.id), field("Display name", f.name)),
      el("div.grid2", field("Base URL", f.baseURL), field("API key", f.apiKey)),
      field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them."),
      el("div.note", RESTART_NOTE),
      el("div.actions", el("button.btn.ghost", { on: { click: () => (form.hidden = true) } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/providers/custom", { kind, id: f.id.value, name: f.name.value, baseURL: f.baseURL.value, apiKey: f.apiKey.value, models: f.models.value })) } }, "Add provider")));
    pane.append(card("Custom endpoints", "Your own servers and gateways", el("button.btn.sm", { on: { click: () => (form.hidden = !form.hidden) } }, ico("plus"), "Add"), customList, form));
  },

  async mcp(pane, ctx) {
    pane.append(...header("MCP servers", "Give agents new tools through the Model Context Protocol. Servers from your global OpenCode config show here too."));
    const servers = await api.get("/api/mcp");
    const list = el("div");
    for (const s of servers) {
      const st = s.disabled ? "disabled" : s.status?.status || "unknown";
      const where = s.type === "remote" ? s.url : (s.command || []).join(" ");
      list.append(el("div.list-item",
        el("span", { className: `status-dot ${st}`, title: st }),
        el("div.li-main",
          el("div.li-title", s.name, el("span.pill-tag", s.type), el("span.pill-tag", s.source === "afh" ? "added in AFH" : s.source), el("span.pill-tag", st)),
          el("div.li-sub", { title: where }, where || ""),
          s.status?.error ? el("div.li-sub", { style: { color: "var(--bad)" } }, s.status.error) : null),
        !s.disabled && s.source !== "plugin" ? el("button.btn.ghost.sm", { title: "Reconnect", on: { click: () => guard(() => api.post(`/api/mcp/${encodeURIComponent(s.name)}/reconnect`), "Reconnecting…") } }, ico("refresh")) : null,
        s.source !== "plugin" ? toggle(!s.disabled, async (on) => { await guard(() => api.post(`/api/mcp/${encodeURIComponent(s.name)}/enabled`, { enabled: on })); }) : null,
        s.source === "afh" ? el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: async () => {
          if (!(await confirmDialog({ title: `Remove ${s.name}?`, body: RESTART_NOTE, confirm: "Remove", danger: true }))) return;
          guard(() => api.del(`/api/mcp/${encodeURIComponent(s.name)}`));
        } } }, ico("trash")) : null));
    }
    if (!servers.length) list.append(el("div.empty-row", "No MCP servers configured."));

    let type = "local";
    const name = el("input.inp", { placeholder: "filesystem" });
    const command = el("input.inp", { placeholder: "npx -y @modelcontextprotocol/server-filesystem C:\\code" });
    const url = el("input.inp", { placeholder: "https://mcp.example.com/mcp" });
    const kv = el("textarea.ta", { rows: 3, placeholder: "KEY=value (one per line)" });
    const localF = el("div", field("Command", command, "The program and its arguments. Quote paths that contain spaces."));
    const remoteF = el("div", { hidden: true }, field("URL", url));
    const kvField = field("Environment variables", kv);
    const form = el("div.inline-form", { hidden: true },
      el("div.grid2", field("Name", name), field("Type", seg([["local", "Local (stdio)"], ["remote", "Remote (HTTP)"]], type, (v) => {
        type = v;
        localF.hidden = v !== "local";
        remoteF.hidden = v !== "remote";
        kvField.querySelector("label").textContent = v === "local" ? "Environment variables" : "Headers";
        kv.placeholder = v === "local" ? "KEY=value (one per line)" : "Authorization: Bearer …";
      }))),
      localF, remoteF, kvField,
      el("div.note", el("b", "Only add servers you trust. "), "A local MCP server runs on your computer with your permissions. ", RESTART_NOTE),
      el("div.actions", el("button.btn.ghost", { on: { click: () => (form.hidden = true) } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/mcp", type === "local"
          ? { name: name.value, type, command: command.value, environment: kv.value }
          : { name: name.value, type, url: url.value, headers: kv.value })) } }, "Add server")));
    pane.append(card("Servers", `${servers.length} configured`, el("button.btn.sm", { on: { click: () => { form.hidden = !form.hidden; name.focus(); } } }, ico("plus"), "Add server"), list, form));
  },

  async plugins(pane, ctx) {
    pane.append(...header("Plugins & skills", "OpenCode plugins add tools, providers, agents and hooks. Plugins added here apply only when OpenCode runs inside AFH."));
    const data = await api.get("/api/plugins");
    const add = el("input.inp", { placeholder: "npm package (opencode-plugin-x@1.2.0) or a local folder path" });
    const addBtn = el("button.btn.primary", { on: { click: () => add.value.trim() && guard(() => api.post("/api/plugins", { spec: add.value.trim() })) } }, ico("plus"), "Add");
    const browse = native.available() ? el("button.btn", { title: "Pick a plugin folder", on: { click: async () => { const p = await native.pickFolder(); if (p) add.value = p; } } }, ico("folder")) : null;
    const addedList = el("div");
    for (const spec of data.added) {
      addedList.append(el("div.list-item", ico("puzzle"), el("div.li-main", el("div.li-title", typeof spec === "string" ? basename(spec) : spec.package), el("div.li-sub", typeof spec === "string" ? spec : JSON.stringify(spec))),
        el("button.btn.ghost.sm.danger", { on: { click: async () => {
          if (!(await confirmDialog({ title: "Remove plugin?", body: RESTART_NOTE, confirm: "Remove", danger: true }))) return;
          guard(() => api.del("/api/plugins", { spec }));
        } } }, ico("trash"))));
    }
    if (!data.added.length) addedList.append(el("div.empty-row", "No plugins added in AFH yet."));
    pane.append(card("Add a plugin", null, null, el("div.card-body", el("div", { style: { display: "flex", gap: "8px" } }, add, browse, addBtn), el("div.help", { style: { fontSize: "12px", color: "var(--text-3)", marginTop: "8px" } }, "Plugins run code inside OpenCode — only install ones you trust. ", RESTART_NOTE))),
      card("Added in AFH", null, null, addedList));

    const loaded = el("div");
    const LOCKED = new Set(["opencode.config.policy", "opencode.provider.opencode"]);
    const disabled = new Set(data.disabled);
    const all = [...data.loaded, ...data.disabled.filter((id) => !data.loaded.some((p) => p.id === id)).map((id) => ({ id, source: { type: "builtin" }, state: { status: "disabled" } }))];
    for (const p of all) {
      const st = disabled.has(p.id) ? "disabled" : p.state?.status || "active";
      loaded.append(el("div.list-item",
        el("span", { className: `status-dot ${st}` }),
        el("div.li-main", el("div.li-title", p.id, el("span.pill-tag", p.source?.type || "plugin"), p.source?.version ? el("span.pill-tag", p.source.version) : null, p.source?.outdated ? el("span.pill-tag.accent", "update available") : null),
          p.state?.error ? el("div.li-sub", { style: { color: "var(--bad)" } }, p.state.error) : p.source?.target ? el("div.li-sub", p.source.target) : null),
        LOCKED.has(p.id) ? el("span.pill-tag", "required") : toggle(!disabled.has(p.id), (on) => guard(() => api.post("/api/plugins/enabled", { id: p.id, enabled: on })))));
    }
    pane.append(card("Loaded plugins", `${data.loaded.length} running · turning a built-in off removes that feature`, null, loaded));

    const skills = el("div", data.skills.map((s) => el("div.list-item", ico("book"), el("div.li-main", el("div.li-title", s.name), el("div.li-sub", { style: { fontFamily: "var(--font)", whiteSpace: "normal" } }, s.description.slice(0, 220))))));
    if (!data.skills.length) skills.append(el("div.empty-row", "No skills found."));
    pane.append(card("Skills", "Loaded from ~/.config/opencode/skills and project .opencode/skills", null, skills));
  },

  async prompts(pane, ctx, opts = {}) {
    const project = ctx.project();
    const data = await api.get(api.q("/api/prompts", { directory: project }));
    const custom = new Set(ctx.S.settings.customAgents || []);
    pane.append(...header("Prompts & agents", "Edit the system prompt each agent runs with, create your own agents, and manage the AGENTS.md instructions every thread reads."));

    // agent system prompts
    const agents = data.agents.filter((a) => !a.hidden);
    let selected = agents.find((a) => a.id === opts.agent) || agents[0];
    const tabs = el("div.agent-tabs");
    const editor = el("div");
    const drawAgent = () => {
      tabs.replaceChildren(...agents.map((a) => el(`button.chip-btn${a.id === selected.id ? ".on" : ""}`, { type: "button", on: { click: () => { selected = a; drawAgent(); } } }, a.name, a.mode === "subagent" ? el("span.pill-tag", "sub") : null, custom.has(a.id) ? el("span.pill-tag.accent", "custom") : null)));
      const ta = el("textarea.ta.code", { value: selected.system || "", placeholder: `Empty = OpenCode's built-in "${selected.id}" prompt (tuned per provider).\n\nWrite a full system prompt here to replace it. AGENTS.md files, skills and MCP guidance are still added after it.` });
      editor.replaceChildren(
        el("div.help", { style: { color: "var(--text-3)", fontSize: "12.5px", marginBottom: "8px" } }, selected.description || ""),
        ta,
        el("div.actions", { style: { marginTop: "10px" } },
          custom.has(selected.id) ? el("button.btn.danger", { on: { click: async () => {
            if (!(await confirmDialog({ title: `Delete agent "${selected.name}"?`, body: RESTART_NOTE, confirm: "Delete", danger: true }))) return;
            guard(() => api.del(`/api/agents/${selected.id}`));
          } } }, ico("trash"), "Delete agent") : null,
          el("span", { style: { flex: 1 } }),
          selected.system ? el("button.btn.ghost", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: "" })) } }, "Reset to built-in") : null,
          el("button.btn.primary", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: ta.value })) } }, "Save prompt")));
    };
    if (selected) drawAgent();
    pane.append(card("Agent system prompts", RESTART_NOTE, el("button.btn.sm", { on: { click: () => (newAgent.hidden = !newAgent.hidden) } }, ico("plus"), "New agent"), el("div.card-body", tabs, editor)));

    // new agent
    const f = { id: el("input.inp", { placeholder: "reviewer" }), description: el("input.inp", { placeholder: "Reviews changes for bugs and risky code" }), system: el("textarea.ta.code", { placeholder: "You are a meticulous code reviewer…", style: { minHeight: "140px" } }) };
    let mode = "primary", readonly = false;
    const modelSel = el("select.sel", el("option", { value: "" }, "Thread's model"), ctx.S.models.map((m) => el("option", { value: `${m.providerID}/${m.id}` }, `${m.name} — ${m.providerID}`)));
    const newAgent = el("div.card", { hidden: true }, el("div.card-head", el("div", el("h3", "New agent"), el("p", "Shows up in the agent picker"))), el("div.card-body",
      el("div.grid2", field("Id", f.id, "lowercase, used in config"), field("Description", f.description)),
      el("div.grid2", field("Shown as", seg([["primary", "Main agent"], ["subagent", "Subagent"], ["all", "Both"]], mode, (v) => (mode = v))), field("Model", modelSel)),
      row("Read only", "Never edits files or runs commands", toggle(false, (v) => (readonly = v))),
      field("System prompt", f.system),
      el("div.actions", el("button.btn.ghost", { on: { click: () => (newAgent.hidden = true) } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/agents", { id: f.id.value, description: f.description.value, system: f.system.value, mode, model: modelSel.value || null, readonly })) } }, "Create agent"))));
    pane.append(newAgent);

    // AGENTS.md
    const mdEditor = (title, sub, text, path, save) => {
      const ta = el("textarea.ta.code", { value: text, placeholder: "# Instructions\n\n- Use TypeScript strict mode\n- Run `pnpm test` before finishing" });
      return card(title, path, el("button.btn.primary.sm", { on: { click: () => guard(() => save(ta.value), "Saved — applies to the next message") } }, "Save"), el("div.card-body", el("div.help", { style: { color: "var(--text-3)", fontSize: "12.5px", marginBottom: "8px" } }, sub), ta));
    };
    pane.append(mdEditor("Global instructions", "AGENTS.md read by every thread in every project (also used by OpenCode itself).", data.globalInstructions, data.globalInstructionsPath, (text) => api.put("/api/prompts/global", { text })));
    if (project) pane.append(mdEditor(`Project instructions · ${basename(project)}`, "AGENTS.md at the project root. Commit it to share with your team.", data.projectInstructions, data.projectInstructionsPath, (text) => api.put("/api/prompts/project", { directory: project, text })));
  },

  async about(pane, ctx) {
    const info = await api.get("/api/bootstrap");
    pane.append(...header("About AFH", "An open-source desktop coding agent. AFH is its own app, built on OpenCode through the opencode-python-sdk."),
      card("Version", null, el("span.pill-tag.accent", `v${info.version}`),
        row("Engine", "OpenCode server, managed by AFH", el("span.status-dot.active")),
        row("Models available", null, el("span", String(ctx.S.models.length))),
        row("Restart engine", "Reloads config, plugins and MCP servers", el("button.btn.sm", { on: { click: () => guard(() => api.post("/api/restart")) } }, ico("refresh"), "Restart"))),
      card("Where things live", null, null, el("div.card-body",
        el("div.note", el("b", "AFH never edits your global opencode.json. "), "Its agents, prompts, MCP servers, plugins and custom providers are kept in ~/.afh/config.json and layered on top when OpenCode starts. API keys live in OpenCode's credential store."),
        el("pre.h-pre", "~/.afh/settings.json       appearance, projects, personalization\n~/.afh/config.json         OpenCode overlay (agents, MCP, plugins, providers)\n~/.afh/personalization.md  generated instructions\n~/.config/opencode/AGENTS.md global instructions (shared with OpenCode)"))),
      card("Open source", "MIT licensed. Uses marked (MIT), DOMPurify (Apache-2.0/MPL-2.0), highlight.js (BSD-3), pywebview (BSD-3), FastAPI (MIT).", null));
  },
};

PANES.redraw = (tab) => instance?.show(tab);
