// Settings window. Big tabs live in their own modules (models, skills, delegation).

import { api, native } from "./api.js";
import { delegationPane } from "./delegate.js";
import { modelsPane } from "./settings-models.js";
import { remotePane } from "./settings-remote.js";
import { skillsPane } from "./settings-skills.js";
import { basename, confirmDialog, copyText, el, ico, icon, modal, toast, toggle } from "./ui.js";

const TABS = [
  ["general", "General", "sliders"],
  ["personalization", "Personalization", "user"],
  ["delegation", "Delegation", "branch"],
  ["models", "Models & providers", "cpu"],
  ["skills", "Skills", "book"],
  ["mcp", "MCP servers", "plug"],
  ["plugins", "Plugins", "puzzle"],
  ["prompts", "Prompts & agents", "scroll"],
  ["remote", "Remote control", "globe"],
  ["about", "About", "info"],
];
const ACCENTS = ["#ff6a2a", "#ff3d71", "#f59f00", "#7c6cff", "#4f8cff", "#22b8cf", "#2fbf71", "#a3a3b5"];
const RESTART_NOTE = "Saving restarts OpenCode for a few seconds. Threads that are running will stop.";

let instance = null;

export function openSettings(tab = "general", ctx, opts = {}) {
  if (instance) return instance.show(tab, opts);
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
  const m = modal([nav, body], { onClose: () => { instance = null; ctx.onReady = null; ctx.onCatalogEvent = null; ctx.redraw = null; } });
  ctx.onReady = () => current && ["models", "mcp", "plugins", "prompts", "delegation"].includes(current) && show(current);
  let timer = 0;
  ctx.onCatalogEvent = () => {
    if (current !== "mcp" && current !== "plugins") return;
    clearTimeout(timer);
    timer = setTimeout(() => show(current), 900);
  };
  ctx.redraw = (id, o) => show(id, o);
  instance = { show };
  show(tab, opts);
}

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const card = (title, sub, action, ...children) => el("div.card", el("div.card-head", el("div", el("h3", title), sub ? el("p", sub) : null), action || null), ...children);
const row = (title, sub, control) => el("div.row", el("div.rl", el("b", title), sub ? el("span", sub) : null), control);
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);

function seg(options, value, onChange) {
  const box = el("div.seg");
  for (const [v, label] of options) {
    box.append(el(`button${v === value ? ".on" : ""}`, { type: "button", dataset: { v }, on: { click: (e) => { box.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); onChange(v); } } }, label));
  }
  return box;
}

async function guard(fn, okMsg) {
  try {
    const out = await fn();
    if (out?.restarting) toast("Saved — restarting OpenCode…", "ok");
    else if (okMsg) toast(okMsg, "ok");
    return out ?? true;
  } catch (e) {
    toast(e.message, "err", 6000);
    return null;
  }
}

const PANES = {
  delegation: (pane, ctx) => delegationPane(pane, ctx),
  models: (pane, ctx, opts) => modelsPane(pane, ctx, opts),
  skills: (pane, ctx) => skillsPane(pane, ctx),
  remote: (pane, ctx) => remotePane(pane, ctx),

  async general(pane, ctx) {
    const s = ctx.S.settings;
    const save = (patch) => ctx.saveSettings(patch).catch((e) => toast(e.message, "err"));
    const ui = (k) => (v) => save({ ui: { [k]: v } });
    const custom = el("input", { type: "color", value: s.ui.accent, title: "Custom color", style: { width: "30px", height: "30px", border: "0", background: "none", padding: "0", cursor: "pointer" } });
    const swatches = el("div.swatches", ACCENTS.map((c) => el(`button.swatch${c === s.ui.accent ? ".on" : ""}`, { type: "button", style: { background: c }, on: { click: (e) => pickAccent(c, e.currentTarget) } })), custom);
    const pickAccent = (c, btn) => { swatches.querySelectorAll(".swatch").forEach((b) => b.classList.remove("on")); btn?.classList.add("on"); save({ ui: { accent: c } }); };
    custom.addEventListener("input", () => pickAccent(custom.value));
    const size = el("input", { type: "range", min: 12, max: 18, step: 1, value: s.ui.fontSize, style: { width: "160px", accentColor: "var(--accent)" } });
    const sizeLbl = el("span.h-muted", { style: { fontStyle: "normal", width: "40px", textAlign: "right" } }, `${s.ui.fontSize}px`);
    size.addEventListener("input", () => { sizeLbl.textContent = `${size.value}px`; document.documentElement.style.setProperty("--fs", `${size.value}px`); });
    size.addEventListener("change", () => save({ ui: { fontSize: Number(size.value) } }));
    const agents = ctx.S.agents.filter((a) => !a.hidden && a.mode !== "subagent");
    const agentSel = el("select.sel", { style: { width: "200px" }, on: { change: (e) => save({ defaultAgent: e.target.value }) } }, agents.map((a) => el("option", { value: a.id, selected: a.id === s.defaultAgent }, a.name)));
    pane.append(...header("General", "How Agent Flow Harness looks and behaves."),
      card("Appearance", null, null,
        row("Theme", null, seg([["system", "System"], ["dark", "Dark"], ["light", "Light"]], s.ui.theme, ui("theme"))),
        row("Accent color", null, swatches),
        row("Text size", null, el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, size, sizeLbl)),
        row("Density", null, seg([["comfortable", "Comfortable"], ["compact", "Compact"]], s.ui.density, ui("density"))),
        row("Animations", "Motion for messages, panels, menus and the logo", toggle(s.ui.animations, ui("animations")))),
      card("Conversation", null, null,
        row("Show thinking", "Display the model's reasoning when it shares it", toggle(s.ui.showReasoning, ui("showReasoning"))),
        row("Send with", null, seg([["enter", "Enter"], ["ctrl-enter", "Ctrl + Enter"]], s.ui.sendKey, ui("sendKey"))),
        row("Default approval mode", "For new threads", seg([["ask", "Ask first"], ["full", "Full access"], ["readonly", "Read only"]], s.defaultMode, (v) => save({ defaultMode: v }))),
        row("Default mode", "Build, Plan, Delegate or a custom agent, for new threads", agentSel)));
  },

  async personalization(pane, ctx) {
    const p = { ...ctx.S.settings.personalization };
    const inp = (k, ph) => el("input.inp", { value: p[k] || "", placeholder: ph, on: { input: (e) => { p[k] = e.target.value; dirty(); } } });
    const ta = (k, ph, rows = 4) => el("textarea.ta", { rows, value: p[k] || "", placeholder: ph, on: { input: (e) => { p[k] = e.target.value; dirty(); } } });
    const saveBtn = el("button.btn.primary", { disabled: true, on: { click: async () => { await guard(() => ctx.saveSettings({ personalization: p }), "Personalization saved — applies to the next message"); saveBtn.disabled = true; } } }, "Save");
    const dirty = () => (saveBtn.disabled = false);
    pane.append(...header("Personalization", "Tell the agent about you and how you like to work. This becomes an instructions file every thread reads."),
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

  async mcp(pane, ctx) {
    pane.append(...header("MCP servers", "Give agents new tools through the Model Context Protocol. Servers from your global OpenCode config show here too."));
    const servers = await api.get("/api/mcp");
    const list = el("div");
    for (const s of servers) {
      const st = s.disabled ? "disabled" : s.status?.status || "unknown";
      const where = s.type === "remote" ? s.url : (s.command || []).join(" ");
      list.append(el("div.list-item", el("span", { className: `status-dot ${st}`, title: st }),
        el("div.li-main", el("div.li-title", s.name, el("span.pill-tag", s.type), el("span.pill-tag", s.source === "afh" ? "added here" : s.source), el("span.pill-tag", st)),
          el("div.li-sub", { title: where }, where || ""), s.status?.error ? el("div.li-sub", { style: { color: "var(--bad)" } }, s.status.error) : null),
        !s.disabled && s.source !== "plugin" ? el("button.btn.ghost.sm", { title: "Reconnect", on: { click: () => guard(() => api.post(`/api/mcp/${encodeURIComponent(s.name)}/reconnect`), "Reconnecting…") } }, ico("refresh")) : null,
        s.source !== "plugin" ? toggle(!s.disabled, (on) => guard(() => api.post(`/api/mcp/${encodeURIComponent(s.name)}/enabled`, { enabled: on }))) : null,
        s.source === "afh" ? el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: async () => { if (await confirmDialog({ title: `Remove ${s.name}?`, body: RESTART_NOTE, confirm: "Remove", danger: true })) guard(() => api.del(`/api/mcp/${encodeURIComponent(s.name)}`)); } } }, ico("trash")) : null));
    }
    if (!servers.length) list.append(el("div.empty-row", "No MCP servers configured."));
    const RECOMMENDED = [
      { name: "chrome-devtools", title: "Chrome DevTools", sub: "Drive a real Chrome: navigate, click, screenshots, console, network", command: "npx -y chrome-devtools-mcp@latest" },
      { name: "filesystem", title: "Filesystem", sub: "Read/write a folder outside the project", command: "npx -y @modelcontextprotocol/server-filesystem C:\\path\\to\\folder" },
      { name: "github", title: "GitHub", sub: "Issues, PRs and repos (needs GITHUB_PERSONAL_ACCESS_TOKEN)", command: "npx -y @modelcontextprotocol/server-github", environment: "GITHUB_PERSONAL_ACCESS_TOKEN=" },
      { name: "playwright", title: "Playwright", sub: "Browser automation and end-to-end testing", command: "npx -y @playwright/mcp@latest" },
      { name: "context7", title: "Context7", sub: "Up-to-date library documentation for the model", command: "npx -y @upstash/context7-mcp" },
    ];
    let type = "local";
    const name = el("input.inp", { placeholder: "filesystem" });
    const command = el("input.inp", { placeholder: "npx -y @modelcontextprotocol/server-filesystem C:\\code" });
    const url = el("input.inp", { placeholder: "https://mcp.example.com/mcp" });
    const kv = el("textarea.ta", { rows: 3, placeholder: "KEY=value (one per line)" });
    const localF = el("div", field("Command", command, "The program and its arguments. Quote paths that contain spaces."));
    const remoteF = el("div", { hidden: true }, field("URL", url));
    const kvField = field("Environment variables", kv);
    const form = el("div.inline-form", { hidden: true },
      el("div.grid2", field("Name", name), field("Type", seg([["local", "Local (stdio)"], ["remote", "Remote (HTTP)"]], type, (v) => { type = v; localF.hidden = v !== "local"; remoteF.hidden = v !== "remote"; kvField.querySelector("label").textContent = v === "local" ? "Environment variables" : "Headers"; kv.placeholder = v === "local" ? "KEY=value (one per line)" : "Authorization: Bearer …"; }))),
      localF, remoteF, kvField,
      el("div.note", el("b", "Only add servers you trust. "), "A local MCP server runs on your computer with your permissions. ", RESTART_NOTE),
      el("div.actions", el("button.btn.ghost", { on: { click: () => (form.hidden = true) } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/mcp", type === "local" ? { name: name.value, type, command: command.value, environment: kv.value } : { name: name.value, type, url: url.value, headers: kv.value })) } }, "Add server")));
    const rec = el("div", RECOMMENDED.filter((r) => !servers.some((s) => s.name === r.name)).map((r) => el("div.list-item", ico("plug"), el("div.li-main", el("div.li-title", r.title), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, r.sub)),
      el("button.btn.sm", { on: { click: () => { form.hidden = false; name.value = r.name; command.value = r.command; kv.value = r.environment || ""; form.scrollIntoView({ behavior: "smooth", block: "nearest" }); } } }, ico("plus"), "Add"))));
    pane.append(card("Servers", `${servers.length} configured`, el("button.btn.sm", { on: { click: () => { form.hidden = !form.hidden; name.focus(); } } }, ico("plus"), "Add server"), list, form),
      card("Popular servers", "One click to prefill the form", null, rec.childElementCount ? rec : el("div.empty-row", "All added.")));
  },

  async plugins(pane, ctx) {
    pane.append(...header("Plugins", "OpenCode plugins add tools, providers, agents and hooks. Plugins added here apply only when OpenCode runs inside AFH."));
    const data = await api.get("/api/plugins");
    const add = el("input.inp", { placeholder: "npm package (opencode-plugin-x@1.2.0) or a local folder path" });
    const addBtn = el("button.btn.primary", { on: { click: () => add.value.trim() && guard(() => api.post("/api/plugins", { spec: add.value.trim() })) } }, ico("plus"), "Add");
    const browse = native.available() ? el("button.btn", { title: "Pick a plugin folder", on: { click: async () => { const p = await native.pickFolder(); if (p) add.value = p; } } }, ico("folder")) : null;
    const addedList = el("div");
    for (const spec of data.added) {
      addedList.append(el("div.list-item", ico("puzzle"), el("div.li-main", el("div.li-title", typeof spec === "string" ? basename(spec) : spec.package), el("div.li-sub", typeof spec === "string" ? spec : JSON.stringify(spec))),
        el("button.btn.ghost.sm.danger", { on: { click: async () => { if (await confirmDialog({ title: "Remove plugin?", body: RESTART_NOTE, confirm: "Remove", danger: true })) guard(() => api.del("/api/plugins", { spec })); } } }, ico("trash"))));
    }
    if (!data.added.length) addedList.append(el("div.empty-row", "No plugins added here yet."));
    pane.append(card("Add a plugin", null, null, el("div.card-body", el("div", { style: { display: "flex", gap: "8px" } }, add, browse, addBtn), el("div.help", { style: { fontSize: "12px", color: "var(--text-3)", marginTop: "8px" } }, "Plugins run code inside OpenCode — only install ones you trust. ", RESTART_NOTE))),
      card("Added here", null, null, addedList));
    const loaded = el("div");
    const LOCKED = new Set(["opencode.config.policy", "opencode.provider.opencode"]);
    const disabled = new Set(data.disabled);
    const all = [...data.loaded, ...data.disabled.filter((id) => !data.loaded.some((p) => p.id === id)).map((id) => ({ id, source: { type: "builtin" }, state: { status: "disabled" } }))];
    for (const p of all) {
      const st = disabled.has(p.id) ? "disabled" : p.state?.status || "active";
      loaded.append(el("div.list-item", el("span", { className: `status-dot ${st}` }),
        el("div.li-main", el("div.li-title", p.id, el("span.pill-tag", p.source?.type || "plugin"), p.source?.version ? el("span.pill-tag", p.source.version) : null, p.source?.outdated ? el("span.pill-tag.accent", "update available") : null),
          p.state?.error ? el("div.li-sub", { style: { color: "var(--bad)" } }, p.state.error) : p.source?.target ? el("div.li-sub", p.source.target) : null),
        LOCKED.has(p.id) ? el("span.pill-tag", "required") : toggle(!disabled.has(p.id), (on) => guard(() => api.post("/api/plugins/enabled", { id: p.id, enabled: on })))));
    }
    pane.append(card("Loaded plugins", `${data.loaded.length} running · turning a built-in off removes that feature`, null, loaded));
  },

  async prompts(pane, ctx, opts = {}) {
    const project = ctx.project();
    const data = await api.get(api.q("/api/prompts", { directory: project }));
    const custom = new Set(ctx.S.settings.customAgents || []);
    pane.append(...header("Prompts & agents", "See the exact system prompt each mode runs with, replace it, create your own agents, and manage the AGENTS.md instructions every thread reads."));

    const agents = data.agents.filter((a) => !a.hidden && !a.delegate && !a.leader);
    let selected = agents.find((a) => a.id === opts.agent) || agents[0];
    const tabs = el("div.agent-tabs");
    const editor = el("div");
    const def = ctx.S.settings.defaultModel || ctx.S.defaultModel;
    let builtin = null;
    const loadBuiltin = async () => { if (!builtin) builtin = await api.get(api.q("/api/prompts/builtin", { providerID: def?.providerID, modelID: def?.id })); return builtin; };
    const drawAgent = async () => {
      tabs.replaceChildren(...agents.map((a) => el(`button.chip-btn${a.id === selected.id ? ".on" : ""}`, { type: "button", on: { click: () => { selected = a; drawAgent(); } } }, a.name, a.mode === "subagent" ? el("span.pill-tag", "sub") : null, custom.has(a.id) ? el("span.pill-tag.accent", "custom") : null)));
      const ta = el("textarea.ta.code", { value: selected.system || "", placeholder: "Write a full system prompt here to replace the built-in one below. AGENTS.md files, skills and MCP guidance are still added after it." });
      const builtinBox = el("div.builtin-box");
      editor.replaceChildren(
        el("div.help", { style: { color: "var(--text-3)", fontSize: "12.5px", marginBottom: "10px" } }, selected.description || ""),
        selected.system ? null : builtinBox,
        el("div.tool-section-label", { style: { padding: "12px 0 6px" } }, selected.system ? "Your prompt (replaces the built-in one)" : "Your override (empty — the built-in prompt above is used)"),
        ta,
        el("div.actions", { style: { marginTop: "10px" } },
          custom.has(selected.id) ? el("button.btn.danger", { on: { click: async () => { if (await confirmDialog({ title: `Delete agent "${selected.name}"?`, body: RESTART_NOTE, confirm: "Delete", danger: true })) guard(() => api.del(`/api/agents/${selected.id}`)); } } }, ico("trash"), "Delete agent") : null,
          el("span", { style: { flex: 1 } }),
          selected.system ? el("button.btn.ghost", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: "" })) } }, "Back to built-in") : null,
          el("button.btn.primary", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: ta.value })) } }, "Save prompt")));
      if (!selected.system) {
        builtinBox.append(el("div.empty-row", el("span.spinner")));
        try {
          const b = await loadBuiltin();
          const options = [["model", `For your default model (${def ? def.id : "none"})`], ["harness", "Default (harness prompt)"], ...Object.keys(b.providers || {}).map((k) => [k, `${k}.txt`])];
          const pick = el("select.sel", { style: { width: "320px" } }, options.map(([v, l]) => el("option", { value: v }, l)));
          const pre = el("pre.h-pre", { style: { maxHeight: "360px" } });
          const info = el("div.help", { style: { color: "var(--text-3)", fontSize: "12px", margin: "6px 0" } });
          const render = () => {
            const v = pick.value;
            const text = v === "model" ? b.forModel?.text || b.harness : v === "harness" ? b.harness : b.providers[v];
            pre.textContent = text || "(empty)";
            info.textContent = v === "model" ? `OpenCode picks by model id: ${b.forModel ? `${b.forModel.key} (${b.forModel.mode})` : "harness"}. ${b.selectionRules?.join(" · ") || ""}` : `Source: ${b.source || "OpenCode repository"}${b.stale ? " (cached copy)" : ""}`;
          };
          pick.addEventListener("change", render);
          render();
          builtinBox.replaceChildren(
            el("div.tool-section-label", { style: { padding: "0 0 6px" } }, "Built-in prompt — this is what runs now"),
            el("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" } }, pick,
              el("button.btn.sm", { on: { click: async () => { await copyText(pre.textContent); toast("Copied", "ok", 1200); } } }, ico("copy"), "Copy"),
              el("button.btn.sm", { title: "Paste it into the editor so you can change it", on: { click: () => { ta.value = pre.textContent; ta.focus(); ta.scrollIntoView({ behavior: "smooth", block: "nearest" }); } } }, ico("edit"), "Use as starting point")),
            info, pre);
        } catch (e) {
          builtinBox.replaceChildren(el("div.error-card", ico("alert"), el("div", `Couldn't load the built-in prompt: ${e.message}`)));
        }
      }
    };
    if (selected) drawAgent();
    const newAgent = el("div.card", { hidden: true });
    pane.append(card("Mode system prompts", RESTART_NOTE, el("button.btn.sm", { on: { click: () => (newAgent.hidden = !newAgent.hidden) } }, ico("plus"), "New agent"), el("div.card-body", tabs, editor)));

    const f = { id: el("input.inp", { placeholder: "reviewer" }), description: el("input.inp", { placeholder: "Reviews changes for bugs and risky code" }), system: el("textarea.ta.code", { placeholder: "You are a meticulous code reviewer…", style: { minHeight: "140px" } }) };
    let mode = "primary", readonly = false;
    const modelSel = el("select.sel", el("option", { value: "" }, "Thread's model"), ctx.S.models.map((m) => el("option", { value: `${m.providerID}/${m.id}` }, `${m.name} — ${m.providerID}`)));
    newAgent.append(el("div.card-head", el("div", el("h3", "New agent"), el("p", "Shows up in the mode picker"))), el("div.card-body",
      el("div.grid2", field("Id", f.id, "lowercase, used in config"), field("Description", f.description)),
      el("div.grid2", field("Shown as", seg([["primary", "Main mode"], ["subagent", "Subagent"], ["all", "Both"]], mode, (v) => (mode = v))), field("Model", modelSel)),
      row("Read only", "Never edits files or runs commands", toggle(false, (v) => (readonly = v))),
      field("System prompt", f.system),
      el("div.actions", el("button.btn.ghost", { on: { click: () => (newAgent.hidden = true) } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/agents", { id: f.id.value, description: f.description.value, system: f.system.value, mode, model: modelSel.value || null, readonly })) } }, "Create agent"))));
    pane.append(newAgent);

    const mdEditor = (title, sub, text, path, save) => {
      const ta = el("textarea.ta.code", { value: text, placeholder: "# Instructions\n\n- Use TypeScript strict mode\n- Run `pnpm test` before finishing" });
      return card(title, path, el("button.btn.primary.sm", { on: { click: () => guard(() => save(ta.value), "Saved — applies to the next message") } }, "Save"), el("div.card-body", el("div.help", { style: { color: "var(--text-3)", fontSize: "12.5px", marginBottom: "8px" } }, sub), ta));
    };
    pane.append(mdEditor("Global instructions", "AGENTS.md read by every thread in every project (also used by OpenCode itself).", data.globalInstructions, data.globalInstructionsPath, (text) => api.put("/api/prompts/global", { text })));
    if (project) pane.append(mdEditor(`Project instructions · ${basename(project)}`, "AGENTS.md at the project root. Commit it to share with your team.", data.projectInstructions, data.projectInstructionsPath, (text) => api.put("/api/prompts/project", { directory: project, text })));
  },

  async about(pane, ctx) {
    const info = await api.get("/api/bootstrap");
    pane.append(...header("About", "Agent Flow Harness is an open-source desktop coding agent built on OpenCode through the opencode-python-sdk."),
      card("Version", null, el("span.pill-tag.accent", `v${info.version}`),
        row("Engine", "OpenCode server, managed by AFH", el("span.status-dot.active")),
        row("Models available", null, el("span", String(ctx.S.models.length))),
        row("Restart engine", "Reloads config, plugins and MCP servers", el("button.btn.sm", { on: { click: () => guard(() => api.post("/api/restart")) } }, ico("refresh"), "Restart"))),
      card("Where things live", null, null, el("div.card-body",
        el("div.note", el("b", "AFH never edits your global opencode.json. "), "Its agents, prompts, delegates, MCP servers, plugins and custom providers are kept in ~/.afh/config.json and layered on top when OpenCode starts. API keys live in OpenCode's credential store."),
        el("pre.h-pre", "~/.afh/settings.json       appearance, projects, personalization, delegation\n~/.afh/config.json         OpenCode overlay (agents, MCP, plugins, providers)\n~/.afh/personalization.md  generated instructions\n~/.config/opencode/AGENTS.md global instructions (shared with OpenCode)"))),
      card("Open source", "MIT licensed. Uses marked (MIT), DOMPurify (Apache-2.0/MPL-2.0), highlight.js (BSD-3), Electron (MIT), FastAPI (MIT).", null));
  },
};
