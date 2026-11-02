// Settings tabs for the agent's power features: Agent (loop, goals, error checks), Hooks,
// Commands (slash commands) and Usage & cost (spending, prices, limits).

import { api } from "./api.js";
import { fmtCost } from "./chat.js";
import { basename, confirmDialog, el, fmtTokens, ico, icon, toast, toggle } from "./ui.js";

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const card = (title, sub, action, ...children) => el("div.card", el("div.card-head", el("div", el("h3", title), sub ? el("p", sub) : null), action || null), ...children);
const row = (title, sub, control) => el("div.row", el("div.rl", el("b", title), sub ? el("span", sub) : null), control);
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);
const WIN = /Windows/i.test(navigator.userAgent);

function num(value, { min = 0, max = 1e9, step = 1, width = "90px", onChange }) {
  const i = el("input.inp", { type: "number", min, max, step, value, style: { width } });
  i.addEventListener("change", () => onChange(Math.max(min, Math.min(max, Number(i.value) || 0))));
  return i;
}

function select(options, value, onChange, width = "220px") {
  return el("select.sel", { style: { width }, on: { change: (e) => onChange(e.target.value) } }, options.map(([v, l]) => el("option", { value: v, selected: v === value }, l)));
}

// ---- Computer control -----------------------------------------------------------------------

const TIER_LABEL = { full: "full control", click: "click only", read: "view only" };

async function computerCard(pane, ctx, save) {
  const c = ctx.S.settings.computer || {};
  const body = el("div.comp-apps");
  const wrap = card("Computer control",
    "Lets the agent see the screen and use the mouse and keyboard in desktop apps — for things with no file, shell or web path — or teach you how to do something, one on-screen tooltip at a time. You approve each app the first time; press Esc any time to stop. Web browsers are view-only here (the agent has its own Browser tool), and terminals and code editors are click-only.",
    null,
    row("Let the agent use the computer", "Adds the computer tool (Windows). The agent still needs your approval for each app", toggle(c.enabled !== false, (v) => { save({ computer: { enabled: v } }); setTimeout(() => refresh(), 150); })),
    row("Let it control web browsers too", "Off by default — browsers stay view-only, since the agent has a dedicated Browser tool for the web", toggle(!!c.browserControl, (v) => save({ computer: { browserControl: v } }))),
    row("Step aside while it works", "Minimize AFH's window during a computer task so the agent sees your apps, and bring it back after", toggle(c.hideWindow !== false, (v) => save({ computer: { hideWindow: v } }))),
    row("Show AFH's cursor and effects", "The on-screen cursor, click ripples, keycaps and screenshot flashes (the glowing edge and Stop button always show)", toggle(c.effects !== false, (v) => save({ computer: { effects: v } }))),
    el("div.comp-head", el("b", "Always-allowed apps"), el("span.comp-sub", "Apps the agent can use without asking again. Open apps are listed so you can pre-approve them.")),
    body);
  pane.append(wrap);

  async function refresh() {
    body.replaceChildren(el("div.comp-loading", "Loading apps…"));
    let data;
    try { data = await api.get("/api/computer/apps"); } catch { body.replaceChildren(el("div.comp-empty", "Couldn't load apps.")); return; }
    if (!data.supported) { body.replaceChildren(el("div.comp-empty", "Computer control works on Windows only.")); return; }
    const allowed = data.allowed || [];
    const allowedIds = new Set(allowed.map((a) => a.id));
    const running = (data.running || []).filter((a) => !allowedIds.has(a.id));
    const rows = [];
    for (const a of allowed) rows.push(appRow(a, true));
    if (running.length) {
      rows.push(el("div.comp-group", "Open now"));
      for (const a of running) rows.push(appRow(a, false));
    }
    if (!rows.length) rows.push(el("div.comp-empty", "No apps approved yet, and nothing controllable is open."));
    body.replaceChildren(...rows);
  }

  function appRow(a, isAllowed) {
    const tier = el("span.comp-tier", TIER_LABEL[a.tier] || a.tier || "full control");
    const action = isAllowed
      ? el("button.btn.ghost.sm", { on: { click: async () => { await api.post("/api/computer/forget", { id: a.id }); refresh(); } } }, "Remove")
      : el("button.btn.sm", { on: { click: async () => { await api.post("/api/computer/allow", { app: a }); refresh(); } } }, "Always allow");
    return el("div.comp-row", el("span.comp-name", a.name || a.id), tier, el("span.spacer"), action);
  }

  ctx.onComputerAppsChanged = refresh;
  await refresh();
}

// ---- Agent ----------------------------------------------------------------------------------

export async function agentPane(pane, ctx) {
  const s = ctx.S.settings;
  const save = (patch, msg) => ctx.saveSettings(patch).then(() => msg && toast(msg, "ok", 1400)).catch((e) => toast(e.message, "err"));
  const ag = s.agent || {}, goals = s.goals || {}, diag = s.diagnostics || {};
  pane.append(...header("Agent", "How the agent works through a task: its step budget, the to-do list, goals with autopilot, and the error checks it gets after every edit."));

  pane.append(card("Work loop", null, null,
    row("Steps per run", "The most model calls one message may trigger before AFH stops and waits for you", num(ag.maxSteps ?? 200, { min: 10, max: 1000, onChange: (v) => save({ agent: { maxSteps: v } }, "Saved") })),
    row("Compact the conversation at", "When this much of the model's context window is used, older messages are summarised in place (they stay readable in the thread). Lower = cheaper, faster turns; higher = the model sees more detail",
      select([["40", "40% of the context window"], ["60", "60% of the context window"], ["80", "80% of the context window (default)"]], String(ag.compactAt ?? 80), (v) => save({ agent: { compactAt: Number(v) } }, "Saved"), "260px")),
    row("Check the to-do list before finishing", "If the agent ends its turn with open to-do items, it is asked once to finish them or update the list", toggle(ag.todoNudge !== false, (v) => save({ agent: { todoNudge: v } })))));

  const br = s.browser || {};
  const brPath = el("input.inp", { value: br.path || "", placeholder: "Found automatically (Chrome or Edge)", style: { width: "320px" } });
  brPath.addEventListener("change", () => save({ browser: { path: brPath.value.trim() } }, "Saved"));
  pane.append(card("Browser", "A real browser the agent drives to check its work or do things on the web: open your dev server, look at screenshots, click and type, read console errors. It has its own sign-ins, never your normal browser's.", null,
    row("Let the agent use a browser", "Adds the browser tool. Screenshots go to models that accept images", toggle(br.enabled !== false, (v) => save({ browser: { enabled: v } }))),
    row("Where it browses", "The side panel shows each thread's tab live; you can browse in it yourself and take over from the agent any time. Chrome or Edge is used when the AFH window isn't open (the CLI)",
      select([["panel", "Side panel in AFH (recommended)"], ["external", "Separate Chrome or Edge"]], br.where === "external" ? "external" : "panel", (v) => save({ browser: { where: v } }, "Saved"), "260px")),
    row("Show the Chrome/Edge window", "For the separate browser: watch it work instead of running it hidden (headless). Takes effect on its next start", toggle(!!br.visible, (v) => save({ browser: { visible: v } }))),
    row("Browser program", "For the separate browser: only if you want a specific Chrome/Edge/Chromium", brPath)));

  if (WIN) await computerCard(pane, ctx, save);

  const vo = s.voice || {};
  const names = ctx.S.providerNames || {};
  const voModel = el("input.inp", { value: vo.model || "", placeholder: "Default for the provider", style: { width: "220px" } });
  const voLang = el("input.inp", { value: vo.language || "", placeholder: "Detect", style: { width: "90px" } });
  voModel.addEventListener("change", () => save({ voice: { model: voModel.value.trim() } }, "Saved"));
  voLang.addEventListener("change", () => save({ voice: { language: voLang.value.trim().toLowerCase() } }, "Saved"));
  pane.append(card("Voice", "The mic button in the message box: speak, click again, and your words are typed in for you to check and send. Uses a speech-to-text (Whisper) endpoint of a provider you added.", null,
    row("Speech-to-text provider", "Automatic uses Groq (fast, cheap), then OpenAI — whichever has a key",
      select([["", "Automatic"], ...Object.entries(names).map(([id, n]) => [id, n])], vo.provider || "", (v) => save({ voice: { provider: v } }, "Saved"), "220px")),
    row("Model", "Groq: whisper-large-v3-turbo · OpenAI: gpt-4o-mini-transcribe", voModel),
    row("Language", "A code like en or ar makes short clips more accurate", voLang)));

  pane.append(card("Goals", "The agent sets a goal itself for multi-step work; you can also set one with the Goal button or /goal", null,
    row("Goals for every multi-step task", "Off: the agent sets a goal only when you ask for one. On: when it plans 3 or more steps, your request becomes the thread's goal", toggle(goals.auto === true, (v) => save({ goals: { auto: v } }))),
    row("Autopilot by default", "New goals keep the agent working until it reports them achieved or blocked", toggle(goals.autopilot !== false, (v) => save({ goals: { autopilot: v } }))),
    row("Continuations per message", "How often autopilot may send the agent back to work before it waits for you", num(goals.maxTurns ?? 3, { min: 1, max: 100, onChange: (v) => save({ goals: { maxTurns: v } }, "Saved") }))));

  const cmds = [...(diag.commands || [])];
  const list = el("div");
  const drawCmds = () => {
    list.replaceChildren(...cmds.map((c, i) => el("div.list-item.hook-row", ico("shield-check"),
      el("div.li-main", el("div.li-title", c.name || c.command.split(" ")[0], el("span.pill-tag", c.glob || "*")), el("div.li-sub", { title: c.command }, c.command)),
      toggle(c.enabled !== false, (v) => { cmds[i] = { ...c, enabled: v }; save({ diagnostics: { commands: cmds } }); }),
      el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: () => { cmds.splice(i, 1); save({ diagnostics: { commands: cmds } }, "Removed"); drawCmds(); } } }, ico("trash")))));
    if (!cmds.length) list.append(el("div.empty-row", "No custom checks. The built-in ones run without setup."));
  };
  drawCmds();
  const f = { name: el("input.inp", { placeholder: "eslint" }), glob: el("input.inp", { placeholder: "*.ts, *.tsx" }), command: el("input.inp", { placeholder: "npx eslint {files}" }) };
  const form = el("div.inline-form", { hidden: true },
    el("div.grid2", field("Name", f.name), field("Files", f.glob, "Comma-separated patterns")),
    field("Command", f.command, "{files} becomes the changed files that match, {file} the first one. A non-zero exit code counts as problems; the output goes to the model."),
    el("div.actions", el("button.btn.ghost", { on: { click: () => (form.hidden = true) } }, "Cancel"),
      el("button.btn.primary", { on: { click: () => {
        if (!f.command.value.trim()) return toast("Enter a command", "info");
        cmds.push({ name: f.name.value.trim(), glob: f.glob.value.trim() || "*", command: f.command.value.trim(), enabled: true });
        save({ diagnostics: { commands: cmds } }, "Check added");
        form.hidden = true; drawCmds();
      } } }, "Add check")));
  pane.append(card("Error checks after edits", "When a step changes files, AFH checks them and gives the problems straight back to the model", toggle(diag.enabled !== false, (v) => save({ diagnostics: { enabled: v } })),
    el("div.card-body", el("div.note", "Built in: Python syntax (plus ruff for undefined names, if installed), JSON, TOML, JavaScript (node --check), TypeScript (the project's own tsc), Go, PHP and Ruby.")),
    row("TypeScript type check", "Runs the project's tsc --noEmit when a .ts file changes (can take a few seconds)", toggle(diag.typescript !== false, (v) => save({ diagnostics: { typescript: v } }))),
    row("ruff for Python", "Undefined names and other fatal errors, when ruff is on PATH", toggle(diag.ruff !== false, (v) => save({ diagnostics: { ruff: v } }))),
    el("div.card-body", el("div", { style: { display: "flex", alignItems: "center", marginBottom: "6px" } }, el("b", { style: { fontSize: "13px" } }, "Your own checks"), el("span", { style: { flex: 1 } }),
      el("button.btn.sm", { on: { click: () => { form.hidden = !form.hidden; f.name.focus(); } } }, ico("plus"), "Add check")), list, form)));
}

// ---- Hooks ----------------------------------------------------------------------------------

const EVENTS = [["pre_tool", "Before a tool runs"], ["post_tool", "After a tool succeeds"], ["stop", "When the agent finishes"]];

const TEMPLATES = WIN ? [
  { name: "Run the tests before finishing", event: "stop", command: "python -m pytest -q; if ($LASTEXITCODE -ne 0) { exit 2 }", sub: "Exit code 2 sends the failures back to the agent" },
  { name: "Format Python files after edits", event: "post_tool", matcher: "^(write|edit|patch)$", command: "$env:AFH_FILES -split ';' | Where-Object { $_ -like '*.py' } | ForEach-Object { ruff format $_ }", sub: "Needs ruff" },
  { name: "Prettier after edits", event: "post_tool", matcher: "^(write|edit|patch)$", command: "$env:AFH_FILES -split ';' | Where-Object { $_ -match '\\.(js|ts|tsx|jsx|css|json|md)$' } | ForEach-Object { npx prettier --write $_ }", sub: "Needs Node.js" },
  { name: "Block dangerous commands", event: "pre_tool", matcher: "^shell$", command: "if ($env:AFH_TOOL_INPUT -match 'rm -rf|Remove-Item .*-Recurse|git push --force|git reset --hard|format [a-z]:') { Write-Output 'Blocked: this command is not allowed by a hook'; exit 2 }", sub: "Exit code 2 stops the call" },
  { name: "Log every command", event: "post_tool", matcher: "^shell$", command: "Add-Content -Path .afh-commands.log -Value $env:AFH_TOOL_INPUT", sub: "Appends to .afh-commands.log in the project" },
] : [
  { name: "Run the tests before finishing", event: "stop", command: "python -m pytest -q || exit 2", sub: "Exit code 2 sends the failures back to the agent" },
  { name: "Format Python files after edits", event: "post_tool", matcher: "^(write|edit|patch)$", command: "for f in $(echo \"$AFH_FILES\" | tr ':' ' '); do case \"$f\" in *.py) ruff format \"$f\";; esac; done", sub: "Needs ruff" },
  { name: "Prettier after edits", event: "post_tool", matcher: "^(write|edit|patch)$", command: "for f in $(echo \"$AFH_FILES\" | tr ':' ' '); do npx prettier --write \"$f\"; done", sub: "Needs Node.js" },
  { name: "Block dangerous commands", event: "pre_tool", matcher: "^shell$", command: "echo \"$AFH_TOOL_INPUT\" | grep -Eq 'rm -rf|git push --force|git reset --hard' && { echo 'Blocked by a hook'; exit 2; } || exit 0", sub: "Exit code 2 stops the call" },
  { name: "Log every command", event: "post_tool", matcher: "^shell$", command: "echo \"$AFH_TOOL_INPUT\" >> .afh-commands.log", sub: "Appends to .afh-commands.log in the project" },
];

export async function hooksPane(pane, ctx) {
  const hooks = [...(ctx.S.settings.hooks || [])];
  const save = (msg) => ctx.saveSettings({ hooks }).then(() => msg && toast(msg, "ok", 1500)).catch((e) => toast(e.message, "err"));
  pane.append(...header("Hooks", "Your own commands at fixed points of every run: format files after the agent writes them, block commands you never want, or run the tests before it may finish."));
  const list = el("div");
  const draw = () => {
    list.replaceChildren(...hooks.map((h, i) => el("div.list-item.hook-row", ico(h.event === "stop" ? "check" : h.event === "pre_tool" ? "shield" : "hook"),
      el("div.li-main", el("div.li-title", h.name || "Hook", el("span.pill-tag", EVENTS.find((e) => e[0] === h.event)?.[1] || h.event), h.matcher && h.event !== "stop" ? el("span.pill-tag", `tools: ${h.matcher}`) : null),
        el("div.li-sub", { title: h.command }, h.command)),
      el("button.btn.ghost.sm", { title: "Edit", on: { click: () => openForm(h, i) } }, ico("edit")),
      toggle(h.enabled !== false, (v) => { hooks[i] = { ...h, enabled: v }; save(); }),
      el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: async () => { if (await confirmDialog({ title: `Remove "${h.name || "hook"}"?`, body: "It stops running from the next tool call.", confirm: "Remove", danger: true })) { hooks.splice(i, 1); save("Removed"); draw(); } } } }, ico("trash")))));
    if (!hooks.length) list.append(el("div.empty-row", "No hooks yet. Start from a template below or add your own."));
  };
  draw();
  const formBox = el("div");
  const openForm = (h = {}, index = -1) => {
    let event = h.event || "post_tool";
    const f = { name: el("input.inp", { value: h.name || "", placeholder: "Format after edits" }), matcher: el("input.inp", { value: h.matcher || "", placeholder: "^(write|edit|patch)$ — empty = every tool" }),
      command: el("textarea.ta.code", { rows: 3, value: h.command || "" }), timeout: el("input.inp", { type: "number", min: 1, max: 600, value: h.timeout || 60, style: { width: "90px" } }) };
    const matcherField = field("Tools (regular expression on the tool name)", f.matcher, "Tool names: read, write, edit, patch, glob, grep, list, shell, jobs, webfetch, todo, subagent, and MCP tools like server_tool.");
    matcherField.hidden = event === "stop";
    formBox.replaceChildren(el("div.inline-form",
      el("div.grid2", field("Name", f.name), field("When", select(EVENTS, event, (v) => { event = v; matcherField.hidden = v === "stop"; }))),
      matcherField,
      field(`Command (runs in the project folder with ${WIN ? "PowerShell" : "bash"})`, f.command,
        "Gets a JSON payload on stdin and AFH_EVENT, AFH_TOOL, AFH_TOOL_INPUT, AFH_FILES, AFH_SESSION_ID, AFH_PROJECT_DIR. Exit code 2 blocks the tool (before) or sends the agent back to work (when it finishes); other output is shown to the agent."),
      el("div.grid2", field("Timeout (seconds)", f.timeout), el("div")),
      el("div.note", el("b", "Hooks run with your permissions. "), "Only add commands you understand."),
      el("div.actions", el("button.btn.ghost", { on: { click: () => formBox.replaceChildren() } }, "Cancel"),
        el("button.btn.primary", { on: { click: () => {
          const cmd = f.command.value.trim();
          if (!cmd) return toast("Enter a command", "info");
          const entry = { id: h.id || `hook_${Date.now().toString(36)}`, name: f.name.value.trim() || cmd.split(" ")[0], event, matcher: event === "stop" ? "" : f.matcher.value.trim(), command: cmd, timeout: Number(f.timeout.value) || 60, enabled: h.enabled !== false };
          if (index >= 0) hooks[index] = entry; else hooks.push(entry);
          save(index >= 0 ? "Hook saved" : "Hook added");
          formBox.replaceChildren();
          draw();
        } } }, index >= 0 ? "Save" : "Add hook"))));
    formBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    f.name.focus();
  };
  pane.append(card("Your hooks", `${hooks.length} configured`, el("button.btn.sm", { on: { click: () => openForm() } }, ico("plus"), "Add hook"), list, formBox));
  pane.append(card("Templates", "One click fills the form; review the command before saving", null,
    el("div", TEMPLATES.map((t) => el("div.list-item", ico("hook"), el("div.li-main", el("div.li-title", t.name, el("span.pill-tag", EVENTS.find((e) => e[0] === t.event)[1])), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, t.sub)),
      el("button.btn.sm", { on: { click: () => openForm({ ...t }) } }, ico("plus"), "Use"))))));
}

// ---- Commands -------------------------------------------------------------------------------

export async function commandsPane(pane, ctx) {
  const project = ctx.project();
  const all = await api.get(api.q("/api/commands", { directory: project }));
  let mine = all.filter((c) => c.source === "settings").map((c) => ({ name: c.name, description: c.description, prompt: c.prompt }));
  pane.append(...header("Commands", "Saved prompts you run by typing / in the composer. $ARGUMENTS is replaced by what you type after the command; $1, $2… by its words."));
  const save = async (msg) => {
    try {
      await api.put("/api/commands", { commands: mine, directory: project });
      ctx.invalidateCommands?.();
      if (msg) toast(msg, "ok", 1500);
      return true;
    } catch (e) {
      toast(e.message, "err", 6000);
      return false;
    }
  };
  const list = el("div");
  const formBox = el("div");
  const draw = () => {
    list.replaceChildren(...mine.map((c, i) => el("div.list-item", ico("slash"),
      el("div.li-main", el("div.li-title", el("code", `/${c.name}`)), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, c.description || c.prompt.slice(0, 90))),
      el("button.btn.ghost.sm", { title: "Edit", on: { click: () => openForm(c, i) } }, ico("edit")),
      el("button.btn.ghost.sm.danger", { title: "Delete", on: { click: async () => { mine.splice(i, 1); if (await save("Deleted")) draw(); } } }, ico("trash")))));
    if (!mine.length) list.append(el("div.empty-row", "No saved commands."));
  };
  const openForm = (c = {}, index = -1) => {
    const f = { name: el("input.inp", { value: c.name || "", placeholder: "review" }), description: el("input.inp", { value: c.description || "", placeholder: "Review my changes" }),
      prompt: el("textarea.ta.code", { rows: 6, value: c.prompt || "", placeholder: "Review the uncommitted changes for bugs. Focus on $ARGUMENTS." }) };
    formBox.replaceChildren(el("div.inline-form",
      el("div.grid2", field("Name", f.name, "Typed as /name"), field("Description", f.description)),
      field("Prompt", f.prompt),
      el("div.actions", el("button.btn.ghost", { on: { click: () => formBox.replaceChildren() } }, "Cancel"),
        el("button.btn.primary", { on: { click: async () => {
          const entry = { name: f.name.value.trim().replace(/^\//, "").toLowerCase(), description: f.description.value.trim(), prompt: f.prompt.value.trim() };
          const before = [...mine];
          if (index >= 0) mine[index] = entry; else mine.push(entry);
          if (await save(index >= 0 ? "Saved" : `/${entry.name} added`)) { formBox.replaceChildren(); draw(); } else mine = before;
        } } }, index >= 0 ? "Save" : "Add command"))));
    f.name.focus();
  };
  draw();
  pane.append(card("Your commands", "Stored in AFH's settings, available in every project", el("button.btn.sm", { on: { click: () => openForm() } }, ico("plus"), "New command"), list, formBox));
  const files = all.filter((c) => c.source === "project" || c.source === "global");
  pane.append(card("From files", "Markdown files: ~/.afh/commands/*.md (everywhere) and .afh/commands/*.md or .claude/commands/*.md in a project", null,
    files.length ? el("div", files.map((c) => el("div.list-item", ico("file"), el("div.li-main", el("div.li-title", el("code", `/${c.name}`), el("span.pill-tag", c.source)), el("div.li-sub", { title: c.path }, c.path))))) : el("div.empty-row", project ? `No command files in ${basename(project)} or ~/.afh/commands.` : "No command files.")));
  pane.append(card("Built in", null, null, el("div", all.filter((c) => c.builtin).map((c) => el("div.list-item", ico("sparkle"), el("div.li-main", el("div.li-title", el("code", `/${c.name}`), c.args ? el("span.pill-tag", c.args) : null), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, c.description)))))));
}

// ---- Usage & cost -------------------------------------------------------------------------------

export async function usagePane(pane, ctx) {
  const [u, prov] = await Promise.all([api.get("/api/usage/summary?days=30"), api.get("/api/providers")]);
  const configured = new Map(prov.configured.map((p) => [p.id, p]));
  pane.append(...header("Usage & cost", "Tokens and spending across every thread on this computer for the last 30 days, the prices AFH uses, and limits that stop a run before it spends too much."));

  const days = u.days;
  const byDay = new Map(days.map((d) => [d.day, d]));
  const series = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    series.push({ key, label: `${d.getDate()}`, ...(byDay.get(key) || { cost: 0, input: 0, output: 0, cacheRead: 0, steps: 0 }) });
  }
  const anyCost = series.some((d) => d.cost > 0);
  const value = (d) => (anyCost ? d.cost : d.input + d.cacheRead + d.output);
  const max = Math.max(...series.map(value), 1e-9);
  const bars = el("div.usage-bars", series.map((d) => el(`div.usage-bar${value(d) ? "" : ".zero"}`, { title: `${d.key}: ${d.steps} steps · ${fmtTokens(d.input + d.cacheRead)} in · ${fmtTokens(d.output)} out${d.cost ? ` · ${fmtCost(d.cost)}` : ""}` },
    el("i", { style: { height: `${Math.max(2, (value(d) / max) * 100)}%` } }), el("span", d.label))));
  const totalTokens = days.reduce((a, d) => a + d.input + d.cacheRead + d.cacheWrite + d.output, 0);
  const cacheShare = days.reduce((a, d) => a + d.cacheRead, 0) / Math.max(1, days.reduce((a, d) => a + d.input + d.cacheRead + d.cacheWrite, 0));
  pane.append(card("Last 30 days", anyCost ? "Spending per day" : "Tokens per day (no priced model used yet)", null,
    el("div.card-body",
      el("div.grid2", { style: { gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "10px" } },
        stat("Spent", fmtCost(u.total || 0)), stat("Today", fmtCost(u.today || 0)), stat("Tokens", fmtTokens(totalTokens)), stat("From cache", `${Math.round(cacheShare * 100)}%`)),
      bars)));

  // per model, with prices
  const tbody = el("tbody");
  for (const m of u.models) {
    const p = configured.get(m.providerID);
    const price = m.price || {};
    const inIn = el("input.inp", { type: "number", min: 0, step: 0.01, value: price.input ?? "", placeholder: "—" });
    const inOut = el("input.inp", { type: "number", min: 0, step: 0.01, value: price.output ?? "", placeholder: "—" });
    const inCache = el("input.inp", { type: "number", min: 0, step: 0.01, value: price.cacheRead ?? "", placeholder: "—" });
    const savePrice = async () => {
      const body = inIn.value === "" && inOut.value === "" ? null : { input: Number(inIn.value || 0), output: Number(inOut.value || 0), ...(inCache.value !== "" ? { cacheRead: Number(inCache.value) } : {}) };
      try { await api.put(`/api/providers/${m.providerID}/prices`, { model: m.id, price: body }); toast(body ? `Price saved for ${m.name}` : "Price cleared", "ok", 1500); } catch (e) { toast(e.message, "err"); }
    };
    [inIn, inOut, inCache].forEach((i) => i.addEventListener("change", savePrice));
    tbody.append(el("tr",
      el("td", el("div", { style: { fontWeight: 550 } }, m.name), el("div", { style: { color: "var(--text-3)", fontSize: "11.5px" } }, `${p?.name || m.providerID}${m.plan ? " · plan" : ""}`)),
      el("td.num", String(m.steps)),
      el("td.num", fmtTokens(m.input + m.cacheRead + m.cacheWrite)),
      el("td.num", fmtTokens(m.output)),
      el("td.num", m.cost ? fmtCost(m.cost) : m.plan ? "plan" : m.unpriced ? "—" : "$0"),
      el("td", p && !m.plan ? el("div", { style: { display: "flex", gap: "4px" } }, inIn, inOut, inCache) : el("span", { style: { color: "var(--text-3)", fontSize: "12px" } }, m.plan ? "flat-rate plan" : "provider removed"))));
  }
  pane.append(card("By model", "Prices are USD per million tokens: input · output · cache read. AFH ships no guessed prices; OpenRouter models come with theirs.", null,
    u.models.length ? el("div.card-body", { style: { overflowX: "auto" } }, el("table.usage-table", el("thead", el("tr", el("th", "Model"), el("th", "Steps"), el("th", "In"), el("th", "Out"), el("th", "Cost"), el("th", "Price / 1M"))), tbody))
      : el("div.empty-row", "No model calls in the last 30 days.")));

  const b = u.budget || {};
  const saveBudget = (patch) => ctx.saveSettings({ budget: patch }).then(() => toast("Limit saved", "ok", 1400)).catch((e) => toast(e.message, "err"));
  pane.append(card("Spending limits", "A run stops before the next model call once a limit is reached (0 = no limit). Only priced models count.", null,
    row("Per thread", "USD a single thread may spend", el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, "$", num(b.perThread ?? 0, { min: 0, max: 100000, step: 0.5, onChange: (v) => saveBudget({ perThread: v }) }))),
    row("Per day", "USD across all threads today", el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, "$", num(b.perDay ?? 0, { min: 0, max: 100000, step: 0.5, onChange: (v) => saveBudget({ perDay: v }) })))));
}

function stat(label, value) {
  return el("div", { style: { background: "var(--panel-2)", borderRadius: "10px", padding: "10px 12px" } }, el("div", { style: { fontSize: "11px", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 600 } }, label), el("div", { style: { fontSize: "18px", fontWeight: 650, marginTop: "2px" } }, value));
}
