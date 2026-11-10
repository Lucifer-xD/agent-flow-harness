// Settings → Models & providers: paste an API key for a known provider or add any
// OpenAI/Anthropic/Gemini-compatible endpoint, then keep only the models you use in the picker.

import { api, native } from "./api.js";
import { confirmDialog, copyText, el, fmtTokens, ico, icon, modal, modalityBadges, toast, toggle } from "./ui.js";

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);

const SIGN_INS = [
  { method: "chatgpt", provider: "chatgpt", name: "ChatGPT (Codex)", sub: "Use your Plus, Pro or Team plan — no API key", icon: "sparkle", alt: "chatgpt-device" },
  { method: "chatgpt-web", provider: "chatgpt-chat", name: "ChatGPT (chat)", sub: "The real GPT-6 family (Astra, Sol, Terra…) from your browser login — uses your ChatGPT plan, not your Codex credits", icon: "sparkle", custom: true },
  { method: "copilot", provider: "github-copilot", name: "GitHub Copilot", sub: "Claude, GPT and Gemini through your Copilot plan", icon: "github", site: "GitHub" },
  { method: "xai", provider: "xai", name: "Grok (xAI)", sub: "Use your SuperGrok or X Premium+ plan — no API key", icon: "zap", site: "xAI",
    warning: "xAI lets your SuperGrok or X Premium+ plan pay only for its own Grok CLI, so AFH tells xAI it is the Grok CLI. xAI could stop this from working, or act on your account. Use it only if you accept that risk. An xAI API key has no such risk." },
  { method: "antigravity", provider: "antigravity", name: "Google Antigravity", sub: "Gemini and Claude on your Google account's Antigravity quota", icon: "globe",
    warning: "Google has suspended Antigravity access for some accounts that signed in through apps other than Antigravity itself (OpenCode, OpenClaw). "
      + "AFH signs in the same way, so your Google account's Antigravity access could be suspended. Your other Google services were not reported affected. "
      + "Use an account you can afford to lose Antigravity on." },
  { method: "openrouter", provider: "openrouter", name: "OpenRouter", sub: "Hundreds of models on one account; creates a key for you", icon: "globe" },
  { method: "minimax", provider: "minimax-coding-plan", name: "MiniMax Token Plan", sub: "MiniMax models on your Token Plan (minimax.io); the China site is under Add a provider", icon: "cpu", site: "MiniMax" },
  { method: "poe", provider: "poe", name: "Poe", sub: "GPT, Claude, Gemini, Grok and more on your Poe points; creates a key for you", icon: "bot" },
  { method: "digitalocean", provider: "digitalocean", name: "DigitalOcean", sub: "Serverless inference on your DigitalOcean account", icon: "globe" },
];
// Sign-ins that only appear inside another one's dialog, or in Add a provider.
const OTHER_SIGN_INS = [
  { method: "chatgpt-device", provider: "chatgpt", name: "ChatGPT (Codex)", site: "OpenAI" },
  { method: "minimax-cn", provider: "minimax-cn-coding-plan", name: "MiniMax Token Plan (China)", site: "MiniMax" },
];

/** Sign-in dialog: opens the provider's page (or shows GitHub's device code) and waits for it. */
export async function signIn(method, { onDone, another = false } = {}) {
  const meta = [...SIGN_INS, ...OTHER_SIGN_INS].find((x) => x.method === method) || { name: method };
  if (meta.warning && !(await confirmDialog({ title: `Sign in to ${meta.name}?`, body: meta.warning, confirm: "I understand, sign in", danger: true }))) return;
  const status = el("div.signin-status", el("span.spinner"), " Starting…");
  const bodyBox = el("div.signin-body");
  let login = null;
  let timer = null;
  let finished = false;
  const dlg = modal(el("div.m-body.signin", { style: { padding: "24px" } },
    el("h2", another ? `Add another ${meta.name} account` : `Sign in to ${meta.name}`),
    another ? el("p.lead", "Pick a different account in the browser. AFH adds it to the list and keeps using the one you have now.") : null,
    bodyBox, status,
    el("div.actions", el("span", { style: { flex: 1 } }), el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"))),
  { small: true, onClose: () => { clearTimeout(timer); if (login && !finished) api.del(`/api/auth/login/${login.id}`).catch(() => {}); } });
  try {
    login = await api.post("/api/auth/login", { method, another });
  } catch (e) {
    status.replaceChildren(el("span.err-text", e.message));
    return;
  }
  const open = () => login.url && native.openExternal(login.url);
  const site = meta.site || meta.name;
  if (login.userCode) {
    bodyBox.replaceChildren(el("p.lead", `Enter this code on ${site} to connect your plan. You can do it on any device.`), el("div.device-code", login.userCode),
      el("button.btn.primary", { on: { click: async () => { await copyText(login.userCode); open(); } } }, ico("copy"), `Copy code & open ${site}`),
      login.url ? el("p.help", { style: { marginTop: "10px", wordBreak: "break-all" } }, login.url) : null);
    status.replaceChildren(el("span.spinner"), ` Waiting for ${site}…`);
  } else if (login.url) {
    const alt = meta.alt && [...SIGN_INS, ...OTHER_SIGN_INS].find((x) => x.method === meta.alt);
    bodyBox.replaceChildren(el("p.lead", "Finish signing in in your browser. AFH continues on its own when you are done."),
      el("button.btn", { on: { click: open } }, ico("external"), "Open the sign-in page again"),
      alt ? el("button.btn.ghost.sm", { style: { marginLeft: "8px" }, title: "For a browser on another device, or when this one can't reach AFH", on: { click: () => { dlg.close(); signIn(alt.method, { onDone }); } } }, "Use a code instead") : null);
    status.replaceChildren(el("span.spinner"), " Waiting for the browser…");
    open();
  }
  const poll = async () => {
    let v;
    try { v = await api.get(`/api/auth/login/${login.id}`); } catch { v = login; }
    if (v.status === "pending") { timer = setTimeout(poll, 1500); return; }
    finished = true;
    if (v.status === "done") {
      dlg.close();
      toast(another ? `Added ${v.account || "the account"} to ${meta.name}` : `Signed in to ${meta.name}${v.account ? ` as ${v.account}` : ""}`, "ok");
      onDone?.(v);
    } else if (v.status === "error") {
      status.replaceChildren(el("div.err-text", (v.error || "Sign-in failed").split("\n").map((line) => el("div", line))));
    }
  };
  if (login.status !== "pending") poll(); else timer = setTimeout(poll, 1500);
}

/** Connect the ChatGPT normal-chat lane: try the browser's saved login, fall back to pasting the token. */
export async function connectChatGPTWeb(onDone) {
  const status = el("div.signin-status");
  const paste = el("textarea.q-other", { rows: 4, placeholder: "Paste your __Secure-next-auth.session-token (or a session export JSON)" });
  const pasteBox = el("div", { hidden: true, style: { marginTop: "12px" } },
    el("p.lead", "AFH couldn't read your browser login automatically. In your browser, open ",
      el("a", { href: "#", on: { click: (e) => { e.preventDefault(); native.openExternal("https://chatgpt.com"); } } }, "chatgpt.com"),
      ", then DevTools → Application → Cookies → chatgpt.com, and copy the value of __Secure-next-auth.session-token."),
    paste,
    el("div.actions", { style: { marginTop: "10px" } }, el("span", { style: { flex: 1 } }),
      el("button.btn.primary", { on: { click: () => submit("paste") } }, ico("check"), "Connect")));
  const retry = el("button.btn", { hidden: true, on: { click: () => submit("chrome") } }, ico("refresh"), "Try the browser again");
  const dlg = modal(el("div.m-body.signin", { style: { padding: "24px" } },
    el("h2", "Connect ChatGPT (chat)"),
    el("p.lead", "Uses your existing ChatGPT login from your browser for the normal chat models. These don't use your Codex/work credits."),
    status, pasteBox,
    el("div.actions", el("span", { style: { flex: 1 } }), retry, el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"))),
    { small: true });

  async function submit(mode) {
    retry.hidden = true;
    status.replaceChildren(el("span.spinner"), mode === "chrome" ? " Reading your browser login…" : " Connecting…");
    let r;
    try {
      r = await api.post("/api/chatgpt-web/connect", mode === "paste" ? { mode, text: paste.value } : { mode });
    } catch (e) {
      status.replaceChildren(el("span.err-text", e.message));
      return;
    }
    if (r.ok) {
      dlg.close();
      toast(`Connected ChatGPT chat${r.account ? ` · ${r.account}` : ""}${r.source ? ` (from ${r.source})` : ""}`, "ok");
      onDone?.({ providerID: "chatgpt-chat" });
      return;
    }
    status.replaceChildren(el("span.err-text", r.error || "Couldn't connect"));
    pasteBox.hidden = false;         // offer the reliable path
    if (r.reason === "locked") retry.hidden = false;  // closing the browser may fix it
  }
  submit("chrome");
}

async function guard(fn, okMsg) {
  try {
    const out = await fn();
    if (okMsg) toast(okMsg, "ok");
    return out ?? true;
  } catch (e) {
    toast(e.message, "err", 6000);
    return null;
  }
}

export async function modelsPane(pane, ctx, opts = {}) {
  const S = ctx.S;
  const redraw = (o = {}) => ctx.redraw("models", o);
  const data = await api.get("/api/providers");
  const configured = data.configured;
  const catalog = data.catalog;

  if (opts.onboarding || !configured.length) {
    pane.append(el("div.card.welcome",
      el("h2", "Welcome to Agent Flow Harness"),
      el("p.lead", "Connect at least one model provider to start. Pick a provider below and paste its API key — local servers like Ollama or LM Studio need no key at all.")));
  } else {
    pane.append(...header("Models & providers", "Paste an API key for the providers you use, or add any compatible endpoint. Then keep only the models you actually use in the picker."));
  }

  // ---- OpenCode migration (one-time offer)
  const mig = S.migration || {};
  if (mig.db && !mig.done) {
    const status = el("div.help", { style: { marginTop: "8px", color: "var(--text-3)" } });
    pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Import from OpenCode"), el("p", "AFH found an OpenCode install on this computer. Bring over its API keys, custom endpoints, MCP servers and threads.")),
      el("button.btn.primary.sm", { on: { click: async (e) => {
        e.currentTarget.disabled = true;
        status.replaceChildren(el("span.spinner"), " Importing…");
        const out = await guard(() => api.post("/api/migrate/opencode", { sessions: true }));
        if (out) {
          S.migration = { ...mig, done: true };
          status.textContent = `Imported ${out.providers?.added?.length || 0} providers, ${out.mcp?.length || 0} MCP servers and ${out.sessions?.imported || 0} threads.`;
          toast("OpenCode data imported", "ok");
          await ctx.reloadCatalog();
          setTimeout(() => redraw(), 1200);
        } else e.currentTarget.disabled = false;
      } } }, ico("arrow-down"), "Import")), status));
  }

  // ---- default model
  if (S.models.length) {
    const has = (r) => r && S.models.some((m) => m.id === r.id && m.providerID === r.providerID);
    const def = [S.settings.defaultModel, S.defaultModel].find(has);  // a removed default shows what is really used
    const sel = el("select.sel", { style: { width: "340px" }, on: { change: (e) => {
      const [providerID, ...rest] = e.target.value.split("/");
      ctx.saveSettings({ defaultModel: { providerID, id: rest.join("/") } }).then(() => toast("Default model saved", "ok"));
    } } });
    for (const m of S.models) sel.append(el("option", { value: `${m.providerID}/${m.id}`, selected: def && def.id === m.id && def.providerID === m.providerID }, `${m.name}  —  ${S.providerNames?.[m.providerID] || m.providerID}`));
    pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Default model"), el("p", `${S.models.length} models in the picker`)), sel)));
  }

  // ---- sign in with an account instead of an API key
  const byId = Object.fromEntries(configured.map((p) => [p.id, p]));
  const afterSignIn = async (v) => { await ctx.reloadCatalog(); redraw({ open: v.providerID }); };
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Sign in"), el("p", "Use a plan you already pay for. Anthropic does not allow Claude Pro/Max sign-in in other apps — use an API key for Claude, or Claude through Copilot."))),
    el("div.signin-grid", SIGN_INS.map((x) => {
      const have = byId[x.provider];
      const signed = have && (have.signedIn || (x.method === "openrouter" && have.hasKey));
      return el(`div.signin-tile${signed ? ".on" : ""}`,
        el("div.st-icon", { html: icon(x.icon) }),
        el("div.li-main", el("div.li-title", x.name), el("div.li-sub", signed ? (have.account ? `Signed in as ${have.account}` : "Connected") + ((have.accounts?.length || 0) > 1 ? ` · ${have.accounts.length} accounts` : "") : x.sub)),
        signed ? el("button.btn.ghost.sm", { on: { click: async () => {
          const n = have.accounts?.length || 1;
          if (!(await confirmDialog({ title: `Sign out of ${x.name}?`, body: n > 1 ? `AFH forgets all ${n} accounts and removes the provider. To remove only one, open the provider below → Accounts.` : "AFH forgets the sign-in and removes the provider. You can sign in again any time.", confirm: "Sign out", danger: true }))) return;
          if (await guard(() => api.post(`/api/providers/${x.provider}/logout`), "Signed out")) { await ctx.reloadCatalog(); redraw(); }
        } } }, "Sign out")
          : el("button.btn.primary.sm", { on: { click: () => (x.custom ? connectChatGPTWeb(afterSignIn) : signIn(x.method, { onDone: afterSignIn })) } }, "Sign in"));
    }))));

  // ---- configured providers with their models
  const pending = new Map(); // "pid/mid" -> hidden
  const applyBar = el("div.apply-bar", { hidden: true },
    el("span", "Model visibility changed."),
    el("button.btn.ghost.sm", { on: { click: () => { pending.clear(); redraw(); } } }, "Discard"),
    el("button.btn.primary.sm", { on: { click: async () => {
      const changes = [...pending.entries()].map(([k, hidden]) => { const [providerID, ...rest] = k.split("/"); return { providerID, id: rest.join("/"), hidden }; });
      if (await guard(() => api.post("/api/models/visibility", { changes }), "Picker updated")) { pending.clear(); await ctx.reloadCatalog(); redraw(); }
    } } }, "Apply"));
  const list = el("div");
  for (const p of configured) list.append(providerCard(p));
  if (!configured.length) list.append(el("div.empty-row", "No providers yet — add one below."));
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Your providers"), el("p", "Toggle which models appear in the model picker")),
    el("button.btn.sm", { title: "Ask every provider for its current model list", on: { click: async () => { if (await guard(() => api.post("/api/models/refresh"), "Model lists refreshed")) { await ctx.reloadCatalog(); redraw(); } } } }, ico("refresh"), "Refresh models")), list, applyBar));

  // ---- switching between accounts
  {
    const ap = { threshold: 90, order: "fill", whenAllUsed: "wait", ...(S.settings.accounts || {}) };
    const save = (patch) => { Object.assign(ap, patch); ctx.saveSettings({ accounts: { ...ap } }).then(() => toast("Saved", "ok", 1200)); };
    const thr = el("select.sel", { on: { change: (e) => save({ threshold: Number(e.target.value) }) } },
      [70, 80, 85, 90, 95, 100].map((v) => el("option", { value: v, selected: Number(ap.threshold) === v }, v === 100 ? "Only when refused" : `${v}% of a limit`)));
    const seg = (key, opts) => el("div.seg", opts.map(([v, l]) => el(`button${ap[key] === v ? ".on" : ""}`, { type: "button", on: { click: (e) => {
      e.currentTarget.parentElement.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); save({ [key]: v });
    } } }, l)));
    const multi = configured.filter((p) => (p.accounts?.length || 0) > 1).length;
    pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Several accounts"),
      el("p", multi ? `${multi} provider${multi === 1 ? " has" : "s have"} more than one account. These rules apply to all of them.`
        : "Give a provider more than one key or sign-in (open it above → Accounts) and AFH moves to the next one before the one in use runs out."))),
      el("div.card-body.acct-prefs",
        field("Switch at", thr, "When the account in use reaches this share of its 5-hour, weekly or other plan limit. A refused request switches at once."),
        field("Order", seg("order", [["fill", "One after another"], ["least", "Least used first"]]), "One after another uses each account fully and keeps the prompt cache warm."),
        field("When every account is used up", seg("whenAllUsed", [["wait", "Wait, then continue"], ["stop", "Stop the task"]])),
        el("div.help", "Sign-ins: Google, OpenAI and xAI don't allow getting around their limits, and Kimi and Z.ai don't allow sharing accounts. Use accounts that are yours, at your own risk."))));
  }

  /** Hand corrections for one model: AFH uses them over models.dev and the provider's own list. */
  function editModel(p, m) {
    const ctxIn = el("input.inp", { type: "number", min: 1000, value: m.context || "" });
    const outIn = el("input.inp", { type: "number", min: 256, value: m.output || "" });
    const effIn = el("input.inp", { value: (m.variants || []).join(", "), placeholder: "low, high, max" });
    const kinds = new Set(m.input || ["text"]);
    const checks = el("div", { style: { display: "flex", gap: "14px", flexWrap: "wrap" } }, ["image", "video", "audio", "pdf"].map((k) => {
      const box = el("input", { type: "checkbox", checked: kinds.has(k), on: { change: (e) => (e.target.checked ? kinds.add(k) : kinds.delete(k)) } });
      return el("label", { style: { display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "13px" } }, box, k);
    }));
    const save = async (reset) => {
      const body = reset ? {} : { context: Number(ctxIn.value) || null, output: Number(outIn.value) || null, variants: effIn.value.split(",").map((v) => v.trim()).filter(Boolean), input: ["text", ...[...kinds].filter((k) => k !== "text")] };
      if (await guard(() => api.put(`/api/providers/${p.id}/models/${encodeURIComponent(m.id)}`, body), reset ? "Back to the catalog's facts" : "Saved")) { dlg.close(); await ctx.reloadCatalog(); redraw({ open: p.id }); }
    };
    const dlg = modal(el("div.m-body", { style: { padding: "22px 24px" } },
      el("h2", `Edit ${m.name}`),
      el("p.lead", "AFH reads these from models.dev and the provider. Correct them here if they are wrong; your values win."),
      el("div.grid2", field("Context window (tokens)", ctxIn), field("Max output (tokens)", outIn)),
      field("Effort levels", effIn, "Comma-separated, as the API names them. \"default\" (no effort sent) is always offered."),
      field("Takes in besides text", checks),
      el("div.actions", m.overridden ? el("button.btn.ghost", { on: { click: () => save(true) } }, "Reset") : null, el("span", { style: { flex: 1 } }),
        el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"), el("button.btn.primary", { on: { click: () => save(false) } }, "Save"))), { small: true });
  }

  function providerCard(p) {
    const how = p.signedIn && p.login !== "openrouter" ? `signed in${p.account ? ` · ${p.account}` : ""}` : p.keyFromEnv ? "key from environment"
      : p.catalog ? (p.hasKey ? `API key ${p.keyHint || ""}` : "no key") : `custom · ${p.kind}`;
    const shown = p.models.filter((m) => !m.hidden).length;
    const body = el("div.model-list");
    const q = el("input.inp", { placeholder: "Filter models…", style: { height: "30px", fontSize: "12.5px", width: "200px" } });
    const drawModels = () => {
      body.replaceChildren();
      const needle = q.value.toLowerCase();
      const rows = p.models.filter((m) => !needle || `${m.name} ${m.id}`.toLowerCase().includes(needle));
      if (!rows.length) body.append(el("div.empty-row", p.models.length ? "No model matches" : "No models yet — click Refresh, or add model ids under Edit."));
      for (const m of rows) {
        const key = `${p.id}/${m.id}`;
        const hidden = pending.has(key) ? pending.get(key) : m.hidden;
        body.append(el(`div.model-row${hidden ? ".hidden" : ""}`,
          el("div.li-main", el("div.li-title", m.name, modalityBadges(m.input), m.tools === false ? el("span.pill-tag", "no tools") : null, m.reasoning ? el("span.pill-tag", "reasoning") : null, m.overridden ? el("span.pill-tag.accent", "edited") : null),
            el("div.li-sub", `${m.id}${m.context ? ` · ${fmtTokens(m.context)} context` : ""}${m.output ? ` · ${fmtTokens(m.output)} out` : ""}${m.variants?.length ? ` · effort: default, ${m.variants.join(", ")}` : ""}`)),
          el("button.icon-btn.sm", { title: "Correct this model's context, effort levels or inputs", html: icon("edit"), on: { click: () => editModel(p, m) } }),
          toggle(!hidden, (on) => { if (on === !m.hidden) pending.delete(key); else pending.set(key, !on); applyBar.hidden = !pending.size; })));
      }
    };
    q.addEventListener("input", drawModels);
    drawModels();
    const bulk = (hide) => { for (const m of p.models) { const key = `${p.id}/${m.id}`; if (hide === m.hidden) pending.delete(key); else pending.set(key, hide); } applyBar.hidden = !pending.size; drawModels(); };
    const testBtn = el("button.btn.ghost.sm", { title: "Send a tiny request to check the key and endpoint", on: { click: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.replaceChildren(el("span.spinner"), " Testing…");
      const out = await guard(() => api.post(`/api/providers/${p.id}/test`));
      b.disabled = false; b.replaceChildren(ico("check"), "Test");
      if (!out) return;
      if (out.ok) toast(`${p.name} works (${out.model})`, "ok"); else toast(`${p.name}: ${out.error || "failed"}`, "err", 8000);
    } } }, ico("check"), "Test");
    const details = el("details.provider", { open: opts.open === p.id || configured.length <= 2 },
      el("summary.provider-head",
        el("span", { className: `status-dot ${p.enabled === false ? "disabled" : p.connected ? "connected" : "failed"}` }),
        el("div.li-main", el("div.li-title", p.name, el("span.pill-tag", how), p.enabled === false ? el("span.pill-tag", "off") : null), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, `${shown} of ${p.models.length} models shown · ${p.base_url}`)),
        el("span.chev", { html: icon("chev-down") })),
      el("div.provider-body",
        accountsBox(p),
        el("div.provider-tools", q, el("span", { style: { flex: 1 } }),
          el("button.btn.ghost.sm", { on: { click: () => bulk(false) } }, "Show all"), el("button.btn.ghost.sm", { on: { click: () => bulk(true) } }, "Hide all"),
          el("button.btn.ghost.sm", { title: "Fetch the model list again", on: { click: async () => { if (await guard(() => api.post(`/api/providers/${p.id}/refresh`), "Models refreshed")) { await ctx.reloadCatalog(); redraw({ open: p.id }); } } } }, ico("refresh")),
          testBtn,
          p.login && p.signedIn && p.login !== "openrouter" ? el("button.btn.ghost.sm", { title: "Sign in again", on: { click: () => (p.login === "chatgpt-web" ? connectChatGPTWeb(afterSignIn) : signIn(p.login, { onDone: afterSignIn })) } }, ico("refresh"), "Sign in again")
            : el("button.btn.ghost.sm", { title: "Change the key, URL or model list", on: { click: () => showForm(p) } }, ico("edit"), "Edit"),
          toggle(p.enabled !== false, async (on) => { if (await guard(() => api.post(`/api/providers/${p.id}/enabled`, { enabled: on }))) { await ctx.reloadCatalog(); redraw({ open: p.id }); } }),
          el("button.btn.ghost.sm.danger", { title: "Remove this provider and its key", on: { click: async () => {
            if (!(await confirmDialog({ title: `Remove ${p.name}?`, body: "Its key and settings are deleted from AFH. Threads that used it keep their history.", confirm: "Remove", danger: true }))) return;
            if (await guard(() => api.del(`/api/providers/${p.id}`), "Removed")) { await ctx.reloadCatalog(); redraw(); }
          } } }, ico("trash"), "Remove")),
        body));
    return details;
  }

  /** Keys and sign-ins of one provider. With two or more, AFH moves to the next one when the one in use nears its limit. */
  function accountsBox(p) {
    const box = el("div.acct-box");
    const signInMethod = p.login && !["openrouter", "poe", "digitalocean", "chatgpt-web"].includes(p.login) ? p.login : null;
    const known = catalog.find((c) => c.id === p.catalog);
    const takesKey = !p.login || (known && known.needsKey !== false && known.login !== p.login) || p.accounts?.some((a) => a.kind === "key");
    const reopen = async () => { await ctx.reloadCatalog(); redraw({ open: p.id }); };
    const addKey = () => {
      const keyIn = el("input.inp", { type: "password", placeholder: "Paste another API key", autocomplete: "off" });
      const nameIn = el("input.inp", { placeholder: "Name (optional), e.g. Work account" });
      const dlg = modal(el("div.m-body", { style: { padding: "22px 24px" } },
        el("h2", `Add a key to ${p.name}`),
        el("p.lead", "Use a key from a different account or project. Keys from the same account share one limit, so switching between them gains nothing."),
        field("API key", keyIn), field("Name", nameIn),
        el("div.actions", el("span", { style: { flex: 1 } }), el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"),
          el("button.btn.primary", { on: { click: async () => {
            if (await guard(() => api.post(`/api/providers/${p.id}/accounts`, { apiKey: keyIn.value, label: nameIn.value }), "Key added")) { dlg.close(); reopen(); }
          } } }, ico("plus"), "Add key"))), { small: true });
      keyIn.focus();
    };
    const head = el("div.acct-head",
      el("div.li-main", el("div.acct-title", "Accounts"),
        el("div.li-sub", (p.accounts?.length || 0) > 1 ? "AFH uses one at a time and moves to the next when it nears its limit, between steps, without stopping the task." : "Add another key or sign-in and AFH switches to it when this one nears its limit.")),
      (p.accounts?.length || 0) > 1 ? el("label.acct-auto", { title: "Move to the next account automatically" }, el("span", "Switch automatically"),
        toggle(p.rotation !== false, async (on) => { await guard(() => api.post(`/api/providers/${p.id}/rotation`, { enabled: on }), on ? "Automatic switching on" : "Automatic switching off"); })) : null,
      signInMethod ? el("button.btn.ghost.sm", { on: { click: () => signIn(signInMethod, { another: true, onDone: reopen }) } }, ico("plus"), "Add account") : null,
      takesKey ? el("button.btn.ghost.sm", { on: { click: addKey } }, ico("key"), "Add key") : null);
    const rows = el("div.acct-rows");
    box.append(head, rows);
    const draw = (data) => {
      const list = data?.accounts || (p.accounts || []).map((a) => ({ ...a, state: a.active ? "active" : a.enabled ? "ready" : "off", windows: [] }));
      if (!list.length) { rows.replaceChildren(el("div.empty-row", "No key or sign-in yet.")); return; }
      rows.replaceChildren(...list.map((a, i) => {
        const stateText = a.state === "active" ? "In use" : a.state === "resting" ? `Resting until ${new Date(a.restUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : a.state === "off" ? "Off" : "Ready";
        const bars = (a.windows || []).filter((w) => w.usedPercent != null).slice(0, 3).map((w) => {
          const pct = Math.round(w.usedPercent);
          const lvl = pct >= (data?.prefs?.threshold || 90) ? "hot" : pct >= 70 ? "warm" : "";
          return el(`div.acct-bar${lvl ? "." + lvl : ""}`, { title: w.resetsAt ? `Resets ${new Date(w.resetsAt).toLocaleString()}` : "" },
            el("span.ab-label", w.label), el("span.ab-track", el("span.ab-fill", { style: { width: `${Math.min(100, pct)}%` } })), el("span.ab-pct", `${pct}%`));
        });
        const rename = async () => {
          const inp = el("input.inp", { value: a.named ? a.label : "", placeholder: a.label });
          const dlg = modal(el("div.m-body", { style: { padding: "22px 24px" } }, el("h2", "Rename account"), field("Name", inp),
            el("div.actions", el("span", { style: { flex: 1 } }), el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"),
              el("button.btn.primary", { on: { click: async () => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { label: inp.value }))) { dlg.close(); load(); } } } }, "Save"))), { small: true });
          inp.focus();
        };
        return el(`div.acct-row.${a.state}`,
          el("span.acct-dot"),
          el("div.li-main",
            el("div.li-title", a.label, el("span.pill-tag", a.kind === "signin" ? "sign-in" : "key"), el(`span.acct-state.${a.state}`, stateText)),
            a.state === "resting" && a.restWhy ? el("div.li-sub", a.restWhy) : a.usageError ? el("div.li-sub", `Usage: ${a.usageError}`) : null,
            bars.length ? el("div.acct-bars", bars) : null),
          a.state !== "active" ? el("button.btn.ghost.sm", { title: "Use this account now", on: { click: async () => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { active: true }), `Now using ${a.label}`)) load(); } } }, "Use") : null,
          el("button.icon-btn.sm", { title: "Move up", disabled: i === 0, html: icon("chev-down"), style: { transform: "rotate(180deg)" }, on: { click: async () => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { move: -1 }))) load(); } } }),
          el("button.icon-btn.sm", { title: "Move down", disabled: i === list.length - 1, html: icon("chev-down"), on: { click: async () => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { move: 1 }))) load(); } } }),
          el("button.icon-btn.sm", { title: "Rename", html: icon("edit"), on: { click: rename } }),
          toggle(a.state !== "off", async (on) => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { enabled: on }))) load(); }),
          el("button.icon-btn.sm.danger", { title: "Remove this account", html: icon("trash"), on: { click: async () => {
            if (!(await confirmDialog({ title: `Remove ${a.label}?`, body: list.length === 1 ? "This is the provider's only account. AFH can't use the provider until you add a key or sign in again." : "AFH forgets this key or sign-in. The other accounts stay.", confirm: "Remove", danger: true }))) return;
            if (await guard(() => api.del(`/api/providers/${p.id}/accounts/${a.id}`), "Account removed")) reopen();
          } } }));
      }));
    };
    const load = async (force = false) => {
      try { draw(await api.get(`/api/providers/${p.id}/accounts${force ? "?force=true" : ""}`)); } catch { draw(null); }
    };
    draw(null);
    if ((p.accounts?.length || 0) > 0) load();
    return box;
  }

  // ---- local model servers (Ollama, LM Studio, vLLM, llama.cpp, Jan)
  const localBox = el("div");
  const scan = async (btn) => {
    if (btn) { btn.disabled = true; btn.replaceChildren(el("span.spinner"), " Scanning…"); }
    let found = [];
    try { found = await api.get("/api/providers/detect-local"); } catch (e) { toast(e.message, "err"); }
    if (btn) { btn.disabled = false; btn.replaceChildren(ico("search"), "Scan again"); }
    localBox.replaceChildren(...(found.length ? found.map((srv) => el("div.list-item", ico("cpu"),
      el("div.li-main", el("div.li-title", srv.name, el("span.pill-tag", `${srv.models.length} model${srv.models.length === 1 ? "" : "s"}`), srv.configured ? el("span.pill-tag.accent", "added") : null),
        el("div.li-sub", { title: srv.models.join(", ") }, `${srv.base_url}${srv.models.length ? " · " + srv.models.slice(0, 4).join(", ") + (srv.models.length > 4 ? "…" : "") : ""}`)),
      srv.configured ? null : el("button.btn.sm.primary", { on: { click: async (e) => {
        e.currentTarget.disabled = true;
        const body = srv.catalog ? { catalog: srv.catalog, id: srv.catalog } : { id: srv.id, name: srv.name, kind: "openai", base_url: srv.base_url };
        const out = await guard(() => api.post("/api/providers", body), `${srv.name} added with ${srv.models.length} models`);
        if (out) { await ctx.reloadCatalog(); redraw({ open: out.id }); }
      } } }, ico("plus"), "Add")))
      : [el("div.empty-row", "No local model server is running. Start Ollama, LM Studio, vLLM, llama.cpp or Jan, then scan again.")]));
  };
  const scanBtn = el("button.btn.sm", { on: { click: (e) => scan(e.currentTarget) } }, ico("search"), "Scan");
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Models on this computer"), el("p", "Finds Ollama, LM Studio, vLLM, llama.cpp and Jan servers running locally — free, private, no key")), scanBtn), localBox));
  scan(null);

  // ---- add a provider
  const available = catalog.filter((c) => !c.configured);
  const search = el("input.inp", { placeholder: `Search ${available.length} providers — OpenAI, Anthropic, Gemini, Azure, Bedrock, Mistral, Kimi, DeepSeek, OpenRouter…` });
  const results = el("div", { style: { maxHeight: "360px", overflowY: "auto", marginTop: "8px" } });
  const formBox = el("div");
  const featured = ["openai", "anthropic", "gemini", "chatgpt", "github-copilot", "antigravity", "openrouter", "kimi", "zai-coding", "deepseek", "xai", "mistral", "groq", "azure", "amazon-bedrock", "ollama", "lmstudio"];
  const subFor = (c) => {
    if (c.login && !c.needsKey) return "sign in with your account";
    if (!c.needsKey) return "local server · no key needed";
    const bits = [c.login ? "sign in or API key" : `API key${c.env?.[0] ? ` (or ${c.env[0]})` : ""}`];
    if (c.params?.length) bits.push(`needs ${c.params.map((x) => x.label.toLowerCase()).join(", ")}`);
    if (c.models) bits.push(`${c.models} models`);
    return bits.join(" · ");
  };
  const drawResults = () => {
    const needle = search.value.toLowerCase();
    const rows = available.filter((c) => !needle || `${c.name} ${c.id}`.toLowerCase().includes(needle));
    rows.sort((a, b) => (featured.indexOf(a.id) + 1 || 99) - (featured.indexOf(b.id) + 1 || 99) || a.name.localeCompare(b.name));
    const limit = needle ? 200 : 60;
    results.replaceChildren(...rows.slice(0, limit).map((c) => el("button.pop-item", { type: "button", on: { click: () => (c.login && !c.needsKey ? signIn(c.login, { onDone: afterSignIn }) : showForm(null, c)) } },
      el("div.pi-main", el("div.pi-title", c.name), el("div.pi-sub", subFor(c))),
      c.login ? el("span.pill-tag.accent", "sign in") : null,
      el("span.pill-tag", c.kind === "openai" ? "openai-compatible" : c.kind))));
    if (rows.length > limit) results.append(el("div.empty-row", `${rows.length - limit} more — type to search all ${rows.length}.`));
    if (!rows.length) results.append(el("div.empty-row", "No provider matches. Add it as a custom endpoint below."));
  };
  search.addEventListener("input", drawResults);
  drawResults();
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Add a provider"), el("p", "Keys are stored only on this computer, in ~/.afh/providers.json")),
    el("button.btn.sm", { on: { click: () => showForm(null, null) } }, ico("plus"), "Custom endpoint")), el("div.card-body", search, results), formBox));

  /** One form for all three cases: a catalog provider, editing a configured one, or a custom endpoint. */
  function showForm(existing, cat) {
    formBox.replaceChildren();
    const isCustom = !cat && !(existing && existing.catalog);
    const catalogId = cat?.id || existing?.catalog || null;
    const known = catalogId ? catalog.find((c) => c.id === catalogId) : null;
    const f = {
      id: el("input.inp", { placeholder: "my-gateway", value: existing?.id || "", disabled: !!existing }),
      name: el("input.inp", { placeholder: "My gateway", value: existing?.name || known?.name || "" }),
      base_url: el("input.inp", { placeholder: known?.base_url || "http://localhost:11434/v1", value: existing?.base_url || (known?.params?.length ? "" : known?.base_url) || "" }),
      api_key: el("input.inp", { type: "password", placeholder: existing?.hasKey ? `unchanged (${existing.keyHint})` : known && !known.needsKey ? "optional" : "Paste API key", autocomplete: "off" }),
      models: el("textarea.ta", { rows: 2, placeholder: "qwen3-coder:30b, llama4:scout — optional when the endpoint lists its models", value: (existing?.models || []).filter((m) => !m.fetched).map((m) => m.id).join(", ") }),
    };
    const paramFields = known?.params || [];
    const paramIns = Object.fromEntries(paramFields.map((x) => [x.name, el("input.inp", { placeholder: x.default || x.name, value: existing?.params?.[x.name] || x.default || "" })]));
    let kind = existing?.kind || known?.kind || "openai";
    const seg = el("div.seg", [["openai", "OpenAI-compatible"], ["anthropic", "Anthropic"], ["gemini", "Gemini"]].map(([v, l]) => el(`button${v === kind ? ".on" : ""}`, { type: "button", on: { click: (e) => { kind = v; seg.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); } } }, l)));
    const title = existing ? `Edit ${existing.name}` : known ? `Connect ${known.name}` : "Custom endpoint";
    const box = el("div.inline-form",
      el("div", { style: { fontWeight: 600, marginBottom: "10px", display: "flex", alignItems: "center", gap: "8px" } }, title, el("span", { style: { flex: 1 } }),
        known?.docs ? el("a", { href: known.docs, target: "_blank", rel: "noopener", style: { color: "var(--accent)", fontSize: "12.5px" }, on: { click: (e) => { e.preventDefault(); native.openExternal(known.docs); } } }, "API docs") : null,
        el("button.icon-btn", { html: icon("x"), on: { click: () => formBox.replaceChildren() } })),
      isCustom ? field("API format", seg) : null,
      isCustom ? el("div.grid2", field("Provider id", f.id, "lowercase, letters and dashes"), field("Display name", f.name)) : null,
      known?.hint ? el("div.help", { style: { marginBottom: "10px" } }, known.hint) : null,
      known?.login ? el("div.signin-inline", el("span", "Have an account?"), el("button.btn.sm.primary", { type: "button", on: { click: () => signIn(known.login, { onDone: afterSignIn }) } }, "Sign in instead"), el("span.muted", "or paste a key below")) : null,
      paramFields.length ? el("div.grid2", paramFields.map((x) => field(x.label, paramIns[x.name], `Also read from ${x.name}.`))) : null,
      el("div.grid2", field(known && !known.customUrl ? "Base URL (advanced)" : "Base URL", f.base_url), field("API key", f.api_key, known?.env?.[0] ? `Also read from ${known.env[0]} if set in your environment.` : null)),
      field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them. Leave empty to use the list the endpoint reports."),
      el("div.actions", el("button.btn.ghost", { on: { click: () => formBox.replaceChildren() } }, "Cancel"),
        el("button.btn.primary", { on: { click: async (e) => {
          e.currentTarget.disabled = true;
          const body = { id: existing?.id || (isCustom ? f.id.value.trim() : catalogId), catalog: isCustom ? null : catalogId, kind, name: f.name.value, base_url: f.base_url.value, api_key: f.api_key.value, models: f.models.value,
            params: Object.fromEntries(Object.entries(paramIns).map(([k, inp]) => [k, inp.value.trim()])) };
          const out = await guard(() => api.post("/api/providers", body), existing ? "Saved" : `${body.name || body.id} added`);
          e.currentTarget.disabled = false;
          if (out) { await ctx.reloadCatalog(); redraw({ open: out.id }); }
        } } }, existing ? "Save" : "Connect")));
    formBox.append(box);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    (isCustom && !existing ? f.id : paramFields.length && !existing ? Object.values(paramIns)[0] : f.api_key).focus();
  }

  if (opts.open === "__new__") showForm(null, null);
}
