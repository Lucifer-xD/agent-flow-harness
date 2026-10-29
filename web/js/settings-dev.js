// Settings tabs for scheduled jobs and developer access (API keys, the local API, the SDKs).

import { api, native } from "./api.js";
import { ago, basename, confirmDialog, copyText, el, ico, toast, toggle } from "./ui.js";

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const card = (title, sub, action, ...children) => el("div.card", el("div.card-head", el("div", el("h3", title), sub ? el("p", sub) : null), action || null), ...children);
const row = (title, sub, control) => el("div.row", el("div.rl", el("b", title), sub ? el("span", sub) : null), control);
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const when = (ms) => (ms ? new Date(ms).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");

export function describeSchedule(j) {
  if (j.every === "interval") return j.minutes % 60 === 0 ? `Every ${j.minutes / 60} hour${j.minutes === 60 ? "" : "s"}` : `Every ${j.minutes} minutes`;
  if (j.every === "hourly") return `Every hour at :${j.time.slice(3)}`;
  if (j.every === "weekdays") return `Weekdays at ${j.time}`;
  if (j.every === "weekly") return `Every ${DAYS[j.weekday]} at ${j.time}`;
  return `Every day at ${j.time}`;
}

// ---- Schedules ---------------------------------------------------------------------------------

export async function schedulesPane(pane, ctx) {
  pane.append(...header("Schedules", "Run a prompt on a timetable — \"every morning, update dependencies and run the tests\". Each run is a new thread in that project, so you can read what happened. Jobs run while AFH is open; one that was due while it was closed runs soon after AFH starts."));
  const list = el("div");
  const formBox = el("div");
  pane.append(card("Jobs", null, el("button.btn.primary.sm", { on: { click: () => edit() } }, ico("plus"), "New job"), formBox, list));
  let jobs = [];

  const draw = () => {
    list.replaceChildren();
    if (!jobs.length) list.append(el("div.empty-row", "No scheduled jobs yet."));
    for (const j of jobs) {
      list.append(el("div.list-item.sched-row",
        el("span.sched-ico", ico("clock")),
        el("div.li-main",
          el("div.li-title", j.name, el("span.pill-tag", describeSchedule(j))),
          el("div.li-sub", { title: j.prompt }, `${basename(j.directory)} · ${j.prompt.slice(0, 90)}`),
          el("div.li-sub.sched-meta", j.enabled ? `Next: ${when(j.nextRun)}` : "Paused", j.lastRun ? ` · Last: ${ago(j.lastRun)}${j.lastStatus?.startsWith("failed") ? " (failed)" : ""}` : "")),
        j.lastSession ? el("button.btn.ghost.sm", { title: "Open the last run", on: { click: () => ctx.openThread?.(j.lastSession, j.directory) } }, ico("eye")) : null,
        el("button.btn.ghost.sm", { title: "Run now", on: { click: async () => {
          try { const r = await api.post(`/api/schedules/${j.id}/run`); toast(`Started "${j.name}"`, "ok"); load(); ctx.openThread?.(r.sessionID, j.directory); } catch (e) { toast(e.message, "err"); }
        } } }, ico("zap")),
        el("button.btn.ghost.sm", { title: "Edit", on: { click: () => edit(j) } }, ico("edit")),
        toggle(j.enabled, async (v) => { try { await api.put(`/api/schedules/${j.id}`, { ...j, enabled: v }); load(); } catch (e) { toast(e.message, "err"); } }),
        el("button.btn.ghost.sm.danger", { title: "Delete", on: { click: async () => {
          if (!(await confirmDialog({ title: `Delete "${j.name}"?`, body: "Threads from earlier runs stay.", confirm: "Delete", danger: true }))) return;
          await api.del(`/api/schedules/${j.id}`); load();
        } } }, ico("trash"))));
    }
  };

  const load = async () => {
    try { jobs = await api.get("/api/schedules"); } catch (e) { toast(e.message, "err"); }
    draw();
  };

  function edit(job) {
    const j = job || { name: "", directory: ctx.project?.() || ctx.S.settings.projects?.[0] || "", prompt: "", every: "daily", time: "09:00", minutes: 60, weekday: 0, mode: "full", model: null, enabled: true };
    const name = el("input.inp", { value: j.name, placeholder: "Morning checks" });
    const prompt = el("textarea.ta", { rows: 4, value: j.prompt, placeholder: "Update the dependencies, run the tests, and fix anything that broke. Summarise what changed." });
    const dir = el("select.sel", null, [...new Set([j.directory, ...(ctx.S.settings.projects || [])].filter(Boolean))].map((p) => el("option", { value: p, selected: p === j.directory }, p)));
    const pick = el("button.btn.ghost.sm", { type: "button", on: { click: async () => {
      if (!native.available()) return toast("Folder picking needs the desktop window", "info");
      const p = await native.pickFolder();
      if (p) { dir.append(el("option", { value: p }, p)); dir.value = p; }
    } } }, ico("folder"), "Other…");
    const every = el("select.sel", null, [["interval", "Every few minutes / hours"], ["hourly", "Every hour"], ["daily", "Every day"], ["weekdays", "Weekdays (Mon–Fri)"], ["weekly", "Once a week"]].map(([v, l]) => el("option", { value: v, selected: v === j.every }, l)));
    const time = el("input.inp", { type: "time", value: j.time, style: { width: "120px" } });
    const minutes = el("select.sel", { style: { width: "160px" } }, [[15, "15 minutes"], [30, "30 minutes"], [60, "1 hour"], [120, "2 hours"], [240, "4 hours"], [360, "6 hours"], [720, "12 hours"]].map(([v, l]) => el("option", { value: v, selected: v === j.minutes }, l)));
    const weekday = el("select.sel", { style: { width: "160px" } }, DAYS.map((d, i) => el("option", { value: i, selected: i === j.weekday }, d)));
    const models = ctx.S.models || [];
    const model = el("select.sel", null, el("option", { value: "" }, "The default model"), models.map((m) => {
      const v = `${m.providerID}/${m.id}`;
      return el("option", { value: v, selected: v === j.model }, `${m.name || m.id} · ${m.providerID}`);
    }));
    const mode = el("select.sel", null, [["full", "Full access — no approvals (recommended for jobs)"], ["build", "Build"], ["plan", "Plan only (no edits)"]].map(([v, l]) => el("option", { value: v, selected: v === j.mode }, l)));
    const whenRow = el("div.grid2");
    const syncWhen = () => {
      whenRow.replaceChildren(field("Repeat", every),
        every.value === "interval" ? field("Every", minutes) : every.value === "hourly" ? field("At minute", time, "Only the minutes count") : every.value === "weekly" ? el("div.grid2", field("Day", weekday), field("Time", time)) : field("Time", time));
    };
    every.addEventListener("change", syncWhen);
    syncWhen();
    const form = el("div.inline-form",
      el("div.grid2", field("Name", name), field("Project", el("div.inline", dir, pick))),
      field("Prompt", prompt, "What the agent should do each time. It works like a message you'd send."),
      whenRow,
      el("div.grid2", field("Model", model), field("Permissions", mode)),
      el("div.actions",
        el("button.btn.ghost", { on: { click: () => formBox.replaceChildren() } }, "Cancel"),
        el("button.btn.primary", { on: { click: async () => {
          const body = { ...j, name: name.value.trim(), prompt: prompt.value.trim(), directory: dir.value, every: every.value, time: time.value || "09:00", minutes: Number(minutes.value), weekday: Number(weekday.value), model: model.value || null, mode: mode.value };
          try {
            if (job) await api.put(`/api/schedules/${job.id}`, body); else await api.post("/api/schedules", body);
            toast(job ? "Job saved" : "Job scheduled", "ok");
            formBox.replaceChildren();
            load();
          } catch (e) { toast(e.message, "err"); }
        } } }, ico("check"), job ? "Save" : "Schedule it")));
    formBox.replaceChildren(form);
    name.focus();
  }

  load();
}

// ---- Developer ---------------------------------------------------------------------------------

export async function developerPane(pane, ctx) {
  pane.append(...header("Developer", "Drive AFH from your own scripts and tools through its local API — start threads, send prompts, read replies, follow live events. Keys work on this computer only."));
  let info;
  try { info = await api.get("/api/developer"); } catch (e) { pane.append(el("div.error-card", ico("alert"), el("div", e.message))); return; }

  const keys = el("div");
  const fresh = el("div");
  const drawKeys = () => {
    keys.replaceChildren();
    if (!info.keys.length) keys.append(el("div.empty-row", "No API keys yet."));
    for (const k of info.keys) {
      keys.append(el("div.list-item", ico("key"),
        el("div.li-main", el("div.li-title", k.name, el("span.pill-tag.mono", `${k.prefix}…`)), el("div.li-sub", `Created ${ago(k.created)}${k.lastUsed ? ` · last used ${ago(k.lastUsed)}` : " · never used"}`)),
        el("button.btn.ghost.sm.danger", { title: "Revoke", on: { click: async () => {
          if (!(await confirmDialog({ title: `Revoke "${k.name}"?`, body: "Scripts using this key stop working right away.", confirm: "Revoke", danger: true }))) return;
          await api.del(`/api/developer/keys/${k.id}`);
          info.keys = info.keys.filter((x) => x.id !== k.id);
          drawKeys();
        } } }, ico("trash"))));
    }
  };
  drawKeys();
  const keyName = el("input.inp", { placeholder: "e.g. CI script", style: { width: "220px" } });
  const create = el("button.btn.primary.sm", { on: { click: async () => {
    try {
      const k = await api.post("/api/developer/keys", { name: keyName.value.trim() || "API key" });
      info.keys.push(k);
      keyName.value = "";
      drawKeys();
      fresh.replaceChildren(el("div.note.key-once", el("b", "Copy your key now — it won't be shown again."),
        el("div.key-box", el("code", k.key), el("button.btn.sm", { on: { click: () => copyText(k.key).then(() => toast("Copied", "ok", 1200)) } }, ico("copy"), "Copy"))));
    } catch (e) { toast(e.message, "err"); }
  } } }, ico("plus"), "Create key");
  pane.append(card("API keys", "Send one as Authorization: Bearer afh_…", el("div.inline", keyName, create), fresh, keys));

  const portInput = el("input.inp", { type: "number", min: 0, max: 65535, value: info.port || "", placeholder: "random", style: { width: "110px" } });
  portInput.addEventListener("change", () => ctx.saveSettings({ developer: { port: Number(portInput.value) || 0 } }).then(() => toast("Saved — used from the next start", "ok")));
  pane.append(card("Where the API is", null, null,
    row("Address right now", "Changes every start unless you fix a port. Scripts find it in the discovery file.", el("code.mono", location.origin)),
    row("Discovery file", "Written while AFH runs: {url, version, pid}", el("code.mono", { title: info.discovery }, info.discovery)),
    row("Fixed port", "Optional, for tools that need a stable address (empty = random)", portInput),
    row("Interactive reference", "Every endpoint with its fields, generated from this version", el("button.btn.ghost.sm", { on: { click: () => window.open(`/api/docs?token=${encodeURIComponent(sessionStorage.getItem("afh-token") || "")}`, "_blank") } }, ico("book"), "Open"))));

  const py = `# copy sdk/python/afh_sdk.py next to your script\nfrom afh_sdk import AFH\nafh = AFH()   # reads AFH_API_KEY and finds the app\nout = afh.run("Add a /health endpoint with a test", directory=r"C:\\code\\api")\nprint(out["reply"])`;
  const js = `import { AFH } from "./afh.mjs";\nconst afh = await AFH.connect();\nconst out = await afh.run("Add a /health endpoint with a test", { directory: "C:/code/api" });\nconsole.log(out.reply);`;
  const curl = `curl -X POST ${location.origin}/api/v1/run \\\n  -H "Authorization: Bearer $AFH_API_KEY" -H "Content-Type: application/json" \\\n  -d '{"directory": "C:/code/api", "prompt": "Run the tests and fix what fails"}'`;
  const snip = (title, code) => el("div.snippet", el("div.snip-head", el("span", title), el("button.btn.ghost.sm", { on: { click: () => copyText(code).then(() => toast("Copied", "ok", 1200)) } }, ico("copy"))), el("pre", el("code", code)));
  pane.append(card("Quick start", "Set AFH_API_KEY to one of your keys. The SDKs are single files in the sdk/ folder of the AFH repository; the API guide on the AFH website covers every call.", null,
    snip("Python", py), snip("JavaScript (Node 18+)", js), snip("curl", curl)));
}

// ---- Report a bug --------------------------------------------------------------------------

export async function bugPane(pane) {
  pane.append(...header("Report a bug", "Describe what went wrong and AFH packs a zip with what's needed to look into it: the version, your system, your settings and the backend log — with every key, token and password removed. It's saved to Downloads and sent nowhere."));
  const what = el("textarea.ta", { rows: 6, placeholder: "What happened, and what did you expect? Steps to make it happen again help the most.\n\ne.g. I pasted a screenshot, sent the message, and the thread stopped with \"Run failed\"." });
  let includeLog = true;
  const withLog = toggle(true, (v) => { includeLog = v; });
  const result = el("div");
  const make = el("button.btn.primary", { on: { click: async () => {
    make.disabled = true;
    try {
      const out = await api.post("/api/bugreport", { description: what.value, includeLog });
      result.replaceChildren(el("div.note", el("b", "Saved. "), `${basename(out.path)} (${Math.max(1, Math.round(out.size / 1024))} KB) is in your Downloads folder — attach it to an email or an issue.`));
      toast("Bug report saved", "ok", 2000);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      make.disabled = false;
    }
  } } }, ico("download"), "Create report");
  pane.append(card("What went wrong", null, null, el("div.card-body", what),
    row("Include the backend log", "The last 1.5 MB, keys masked. It's usually where the cause is", withLog),
    el("div.card-body", el("div.btn-row", make), result)));

  const box = el("div.card-body", el("div.help", "Loading…"));
  pane.append(card("What goes in the zip", null, null, box));
  try {
    const p = await api.get("/api/bugreport");
    const sys = p.system || {};
    box.replaceChildren(
      el("pre.h-pre", [
        `README.md        your description and the recent warnings and errors`,
        `system.json      AFH ${sys.app} · ${sys.os} · Python ${sys.python} · browsers: ${(sys.browsers || []).join(", ") || "none"}`,
        `settings.json    your settings, keys and personal text removed`,
        `providers.json   ${(p.providers || []).map((x) => x.name).join(", ") || "no providers"} (names and models, never keys)`,
        `afh-backend.log  ${Math.round((p.logBytes || 0) / 1024)} KB`,
      ].join("\n")),
      p.problems?.length ? el("details", el("summary", `${p.problems.length} recent warnings and errors`), el("pre.h-pre", p.problems.join("\n"))) : el("div.help", "No warnings or errors in the log right now."));
  } catch (e) {
    box.replaceChildren(el("div.help", e.message));
  }
}
