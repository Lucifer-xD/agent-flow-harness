// Settings window. Big tabs live in their own modules (models, skills, delegation, remote).

import { api, native } from "./api.js";
import { PRESETS, applyAppearance } from "./appearance.js";
import { delegationPane } from "./delegate.js";
import { logoNode } from "./logo.js";
import { modelsPane } from "./settings-models.js";
import { remotePane } from "./settings-remote.js";
import { skillsPane } from "./settings-skills.js";
import { basename, confirmDialog, copyText, el, ico, icon, modal, toast, toggle } from "./ui.js";

const TABS = [
  ["general", "General", "sliders"],
  ["appearance", "Appearance", "sparkle"],
  ["personalization", "Personalization", "user"],
  ["delegation", "Delegation", "branch"],
  ["models", "Models & providers", "cpu"],
  ["skills", "Skills", "book"],
  ["mcp", "MCP servers", "plug"],
  ["prompts", "Prompts & agents", "scroll"],
  ["remote", "Remote control", "globe"],
  ["about", "About", "info"],
];
const ACCENTS = ["#ff6a2a", "#ff3d71", "#f59f00", "#2fbf71", "#22b8cf", "#4f8cff", "#7c6cff", "#e64980", "#ffffff"];
const RESTART_NOTE = "Saving reconnects MCP servers; running threads keep going.";

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
  ctx.onReady = () => current && ["mcp"].includes(current) && show(current);
  let timer = 0;
  ctx.onCatalogEvent = () => { if (current === "mcp") { clearTimeout(timer); timer = setTimeout(() => show(current), 900); } };
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
  for (const [v, label] of options) box.append(el(`button${v === value ? ".on" : ""}`, { type: "button", on: { click: (e) => { box.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); onChange(v); } } }, label));
  return box;
}

function slider(min, max, step, value, fmt, onInput, onChange) {
  const input = el("input", { type: "range", min, max, step, value, style: { width: "170px", accentColor: "var(--accent)" } });
  const label = el("span.h-muted", { style: { fontStyle: "normal", width: "48px", textAlign: "right" } }, fmt(value));
  input.addEventListener("input", () => { label.textContent = fmt(Number(input.value)); onInput?.(Number(input.value)); });
  input.addEventListener("change", () => onChange(Number(input.value)));
  return el("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, input, label);
}

async function guard(fn, okMsg) {
  try {
    const out = await fn();
    if (out?.restarting) toast("Saved — reconnecting…", "ok");
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
    const agents = ctx.S.agents.filter((a) => !a.hidden && a.mode !== "subagent");
    const agentSel = el("select.sel", { style: { width: "200px" }, on: { change: (e) => save({ defaultAgent: e.target.value }) } }, agents.map((a) => el("option", { value: a.id, selected: a.id === s.defaultAgent }, a.name)));
    pane.append(...header("General", "How Agent Flow Harness behaves. Looks are in Appearance."),
      card("New threads", null, null,
        row("Default mode", "Build, Plan, Delegate or one of your agents", agentSel),
        row("Default approval mode", "Ask first shows every edit and command before it runs", seg([["ask", "Ask first"], ["full", "Full access"], ["readonly", "Read only"]], s.defaultMode, (v) => save({ defaultMode: v }))),
        row("Reopen the last thread on start", null, toggle(s.ui.reopenLast !== false, ui("reopenLast")))),
      card("Conversation", null, null,
        row("Show thinking", "Display the model's reasoning when it shares it", toggle(s.ui.showReasoning, ui("showReasoning"))),
        row("Show model, tokens and time under replies", "Otherwise only on hover", toggle(s.ui.showMeta !== false, ui("showMeta"))),
        row("Send with", null, seg([["enter", "Enter"], ["ctrl-enter", "Ctrl + Enter"]], s.ui.sendKey, ui("sendKey"))),
        row("Ask before deleting a thread", null, toggle(s.ui.confirmDelete !== false, ui("confirmDelete"))),
        row("Live file view", "Open a side pane and show files being written or edited as it happens", toggle(s.ui.liveFiles !== false, ui("liveFiles")))),
      card("Notifications", "When you're in another window", null,
        row("Sounds", "A short tone when a run finishes or needs your approval", toggle(s.ui.sounds !== false, ui("sounds"))),
        row("Desktop notifications", "System notification when a thread finishes or needs approval", toggle(s.ui.notify !== false, (v) => { ui("notify")(v); if (v && "Notification" in window && Notification.permission === "default") Notification.requestPermission(); }))),
      card("Keyboard", null, null, el("div.card-body", el("pre.h-pre", "Enter / Shift+Enter   send / new line\nEsc                   stop the running thread\nCtrl+N                new thread\nCtrl+K                search threads\nCtrl+B                toggle sidebar\nCtrl+,                settings"))));
  },

  async appearance(pane, ctx) {
    const s = ctx.S.settings;
    const u = s.ui;
    const save = (patch) => ctx.saveSettings({ ui: patch }).catch((e) => toast(e.message, "err"));
    const preview = (patch) => applyAppearance({ ...ctx.S.settings.ui, ...patch }); // live, before save
    const presetGrid = el("div.preset-grid");
    const drawPresets = () => {
      presetGrid.replaceChildren();
      for (const [id, p] of Object.entries(PRESETS)) {
        presetGrid.append(el(`button.preset${u.preset === id ? ".on" : ""}`, { type: "button", style: { background: p.bg, color: p.text, borderColor: u.preset === id ? p.accent : "transparent" }, on: { click: async () => { u.preset = id; u.accentOverride = false; u.bg = p.bg; u.text = p.text; u.accent = p.accent; await save({ preset: id, accentOverride: false, bg: p.bg, text: p.text, accent: p.accent }); drawPresets(); drawCustom(); } } },
          el("span.preset-dot", { style: { background: p.accent } }), el("span", p.name), el("span.preset-sub", p.dark ? "dark" : "light")));
      }
      presetGrid.append(el(`button.preset${u.preset === "custom" ? ".on" : ""}`, { type: "button", style: { background: u.bg, color: u.text, borderColor: u.preset === "custom" ? u.accent : "transparent" }, on: { click: async () => { u.preset = "custom"; await save({ preset: "custom" }); drawPresets(); drawCustom(); } } },
        el("span.preset-dot", { style: { background: u.accent } }), el("span", "Custom"), el("span.preset-sub", "your colors")));
    };
    drawPresets();
    const colorField = (label, key, onPick) => {
      const input = el("input", { type: "color", value: u[key] || "#000000", style: { width: "44px", height: "30px", border: "0", background: "none", padding: "0", cursor: "pointer" } });
      const hexBox = el("input.inp", { value: u[key] || "", style: { width: "110px", fontFamily: "var(--mono)" } });
      const commit = async (v) => { if (!/^#[0-9a-f]{6}$/i.test(v)) return; u[key] = v; hexBox.value = v; input.value = v; onPick(v); };
      input.addEventListener("input", () => { hexBox.value = input.value; preview({ [key]: input.value, preset: "custom" }); });
      input.addEventListener("change", () => commit(input.value));
      hexBox.addEventListener("change", () => commit(hexBox.value.trim()));
      return row(label, null, el("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, input, hexBox));
    };
    const customBox = el("div");
    const drawCustom = () => {
      customBox.replaceChildren(
        colorField("Background", "bg", (v) => save({ bg: v, preset: "custom" }).then(drawPresets)),
        colorField("Text", "text", (v) => save({ text: v, preset: "custom" }).then(drawPresets)),
        row("Accent", "Buttons, focus rings, the active thread, the delegation cards", el("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
          el("div.swatches", ACCENTS.map((c) => el(`button.swatch${c === u.accent ? ".on" : ""}`, { type: "button", style: { background: c }, on: { click: async (e) => { u.accent = c; u.accentOverride = true; await save({ accent: c, accentOverride: true }); e.currentTarget.parentElement.querySelectorAll(".swatch").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); drawPresets(); } } }))),
          (() => { const i = el("input", { type: "color", value: u.accent, title: "Custom accent", style: { width: "30px", height: "30px", border: "0", background: "none", padding: "0", cursor: "pointer" } }); i.addEventListener("input", () => preview({ accent: i.value, accentOverride: true })); i.addEventListener("change", async () => { u.accent = i.value; u.accentOverride = true; await save({ accent: i.value, accentOverride: true }); drawPresets(); }); return i; })())));
    };
    drawCustom();
    pane.append(...header("Appearance", "Make it yours: theme, colors, type, shape and motion. Changes apply instantly."),
      card("Theme", null, seg([["system", "Follow system"], ["dark", "Dark"], ["light", "Light"]], u.theme, (v) => save({ theme: v }).then(drawPresets)), el("div.card-body", presetGrid), customBox),
      card("Type", null, null,
        row("Font", null, seg([["inter", "Inter"], ["system", "System"], ["rounded", "Rounded"], ["serif", "Serif"], ["mono", "Mono"]], u.font || "inter", (v) => save({ font: v }))),
        row("Text size", null, slider(12, 18, 1, u.fontSize, (v) => `${v}px`, (v) => preview({ fontSize: v }), (v) => save({ fontSize: v })))),
      card("Shape & layout", null, null,
        row("Corner roundness", null, slider(0, 24, 2, u.radius ?? 12, (v) => `${v}px`, (v) => preview({ radius: v }), (v) => save({ radius: v }))),
        row("Density", null, seg([["comfortable", "Comfortable"], ["compact", "Compact"]], u.density, (v) => save({ density: v }))),
        row("Your messages", "Bubbles on the right, or flat with an accent bar", seg([["bubbles", "Bubbles"], ["flat", "Flat"]], u.bubbles || "bubbles", (v) => save({ bubbles: v }))),
        row("Glass effect", "Translucent composer, sidebar and menus", toggle(u.glass !== false, (v) => save({ glass: v })))),
      card("Motion", null, null,
        row("Animations", "Messages, panels, menus", toggle(u.animations, (v) => save({ animations: v }))),
        row("Animation speed", null, slider(0.5, 2, 0.1, u.animSpeed || 1, (v) => `${v.toFixed(1)}×`, (v) => preview({ animSpeed: v }), (v) => save({ animSpeed: v }))),
        row("Logo flows while a model works", null, toggle(u.logoAnim !== false, (v) => save({ logoAnim: v }))),
        el("div.row", el("div.rl", el("b", "Preview")), el("div", { style: { display: "flex", gap: "16px", alignItems: "center" } }, logoNode({ size: 64 }), logoNode({ size: 64, working: true })))),
      card("Custom CSS", "For power users: anything here is injected into the app", null, el("div.card-body",
        (() => { const ta = el("textarea.ta.code", { rows: 6, value: u.customCss || "", placeholder: ".bubble { border-radius: 6px }\n.thread-inner { max-width: 960px }" }); return el("div", ta, el("div.actions", el("button.btn.primary.sm", { on: { click: () => save({ customCss: ta.value }).then(() => toast("Applied", "ok")) } }, "Apply"))); })())));
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
    pane.append(...header("MCP servers", "Give agents new tools through the Model Context Protocol. Local servers run on your computer; remote ones are plain HTTP."));
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

  async prompts(pane, ctx, opts = {}) {
    const project = ctx.project();
    const data = await api.get(api.q("/api/prompts", { directory: project }));
    const custom = new Set(ctx.S.settings.customAgents || []);
    pane.append(...header("Prompts & agents", "One harness system prompt goes to every model in every mode. Edit it here, replace it per mode if you want, create your own agents, and manage AGENTS.md."));

    // ---- the harness prompt
    const sysTa = el("textarea.ta.code", { value: data.system, style: { minHeight: "320px" } });
    const sysSave = el("button.btn.primary", { on: { click: () => guard(() => api.put("/api/prompts/system", { text: sysTa.value })) } }, "Save prompt");
    pane.append(card("Harness system prompt", data.systemIsDefault ? "AFH's default — sent to every model, before AGENTS.md, personalization, skills and the environment" : "Your custom prompt — sent to every model", el("span.pill-tag.accent", data.systemIsDefault ? "default" : "custom"),
      el("div.card-body", sysTa,
        el("div.actions", { style: { marginTop: "10px" } },
          el("button.btn.ghost", { on: { click: async () => { await copyText(sysTa.value); toast("Copied", "ok", 1200); } } }, ico("copy"), "Copy"),
          data.systemIsDefault ? null : el("button.btn.ghost", { on: { click: async () => { if (await confirmDialog({ title: "Reset to AFH's default prompt?", body: RESTART_NOTE, confirm: "Reset" })) guard(() => api.put("/api/prompts/system", { text: "" })); } } }, "Reset to default"),
          el("span", { style: { flex: 1 } }), sysSave))));

    // ---- per-mode replacements
    const agents = data.agents.filter((a) => !a.hidden && !a.delegate && !a.leader && a.mode !== "subagent");
    let selected = agents.find((a) => a.id === opts.agent) || agents[0];
    const tabs = el("div.agent-tabs");
    const editor = el("div");
    const drawAgent = () => {
      tabs.replaceChildren(...agents.map((a) => el(`button.chip-btn${a.id === selected.id ? ".on" : ""}`, { type: "button", on: { click: () => { selected = a; drawAgent(); } } }, a.name, custom.has(a.id) ? el("span.pill-tag.accent", "custom") : null, data.agentOverrides[a.id] ? el("span.pill-tag", "replaced") : null)));
      const override = data.agentOverrides[selected.id] || "";
      const ta = el("textarea.ta.code", { value: override, placeholder: selected.id === "plan" ? "Empty = the harness prompt plus the plan-mode rules below." : "Empty = the harness prompt above. Paste a full prompt here to replace it for this mode only." });
      editor.replaceChildren(
        el("div.help", { style: { color: "var(--text-3)", fontSize: "12.5px", marginBottom: "10px" } }, selected.description || ""),
        selected.id === "plan" && !override ? el("pre.h-pre", { style: { marginBottom: "10px" } }, data.planRules) : null,
        ta,
        el("div.actions", { style: { marginTop: "10px" } },
          custom.has(selected.id) ? el("button.btn.danger", { on: { click: async () => { if (await confirmDialog({ title: `Delete agent "${selected.name}"?`, body: RESTART_NOTE, confirm: "Delete", danger: true })) guard(() => api.del(`/api/agents/${selected.id}`)); } } }, ico("trash"), "Delete agent") : null,
          el("span", { style: { flex: 1 } }),
          override ? el("button.btn.ghost", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: "" })) } }, "Use the harness prompt") : null,
          el("button.btn.primary", { on: { click: () => guard(() => api.put(`/api/prompts/agent/${selected.id}`, { system: ta.value })) } }, "Save for this mode")));
    };
    if (selected) drawAgent();
    const newAgent = el("div.card", { hidden: true });
    pane.append(card("Per-mode replacement", "Optional. Leave empty to use the harness prompt.", el("button.btn.sm", { on: { click: () => (newAgent.hidden = !newAgent.hidden) } }, ico("plus"), "New agent"), el("div.card-body", tabs, editor)));

    const f = { id: el("input.inp", { placeholder: "reviewer" }), description: el("input.inp", { placeholder: "Reviews changes for bugs and risky code" }), system: el("textarea.ta.code", { placeholder: "Optional: a full system prompt for this agent (empty = the harness prompt)", style: { minHeight: "120px" } }) };
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
    pane.append(mdEditor("Global instructions", "AGENTS.md read by every thread in every project.", data.globalInstructions, data.globalInstructionsPath, (text) => api.put("/api/prompts/global", { text })));
    if (project) pane.append(mdEditor(`Project instructions · ${basename(project)}`, "AGENTS.md at the project root. Commit it to share with your team.", data.projectInstructions, data.projectInstructionsPath, (text) => api.put("/api/prompts/project", { directory: project, text })));
  },

  async about(pane, ctx) {
    const info = await api.get("/api/bootstrap");
    pane.append(...header("About", "Agent Flow Harness is an open-source desktop coding agent with its own engine: no third-party harness, every prompt and tool is yours to see and change."),
      card("Version", null, el("span.pill-tag.accent", `v${info.version}`),
        row("Engine", "AFH Engine (Python, in-process)", el("span.status-dot.active")),
        row("Models available", null, el("span", String(ctx.S.models.length))),
        row("Reload engine", "Re-reads providers, agents and reconnects MCP servers", el("button.btn.sm", { on: { click: () => guard(() => api.post("/api/restart")) } }, ico("refresh"), "Restart"))),
      card("Where things live", null, null, el("div.card-body",
        el("div.note", el("b", "Everything stays on this computer. "), "Settings, API keys and threads live under ~/.afh. Nothing is sent anywhere except to the model providers you configure."),
        el("pre.h-pre", "~/.afh/settings.json       appearance, projects, personalization, delegation, prompts, agents, MCP servers\n~/.afh/providers.json      providers and API keys\n~/.afh/afh.db              threads, messages and undo snapshots\n~/.afh/skills/             installed skills\n~/.afh/personalization.md  generated instructions\n~/.afh/AGENTS.md           global instructions"))),
      card("Open source", "MIT licensed. Uses marked (MIT), DOMPurify (Apache-2.0/MPL-2.0), highlight.js (BSD-3), Electron (MIT), FastAPI (MIT).", null));
  },
};
