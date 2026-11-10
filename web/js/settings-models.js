// Settings → Models & accounts. An overview (default model, your providers, the rules for several
// accounts), a page per provider (Accounts · Models · Connection) and one Connect dialog for every
// way in: sign in with a plan, paste an API key, models on this computer, or a custom endpoint.

import { api, native } from "./api.js";
import { modelFacts, modelPicker } from "./model-picker.js";
import { confirmDialog, copyText, el, fmtTokens, ico, icon, modal, modalityBadges, popover, toast, toggle } from "./ui.js";

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

const hue = (s) => { let h = 7; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const initials = (label) => { const w = String(label).replace(/[()]/g, "").split(/[\s\-_.]+/).filter(Boolean); return ((w[0]?.[0] || "?") + (w[1]?.[0] || "")).toUpperCase(); };
const mono = (label, id, size = "") => el(`span.pv-mono${size ? "." + size : ""}`, { style: { "--h": String(hue(id)) }, "aria-hidden": "true" }, initials(label));
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const timeOf = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const LOCAL_IDS = new Set(["ollama", "lmstudio", "vllm", "llamacpp", "llama-cpp", "jan"]);

/** How a provider is connected, in a few words. */
function howConnected(p) {
  const n = p.accounts?.length || 0;
  if (p.signedIn && p.login !== "openrouter") return n > 1 ? `${plural(n, "account")} signed in` : p.account ? `Signed in as ${p.account}` : "Signed in";
  if (p.keyFromEnv) return "Key from your environment";
  if (n > 1) return `${plural(n, "key")}`;
  if (p.hasKey) return `API key ${p.keyHint || ""}`.trim();
  if (LOCAL_IDS.has(p.catalog || p.id) || /localhost|127\.0\.0\.1/.test(p.base_url || "")) return "On this computer";
  return p.catalog ? "No key yet" : "Custom endpoint";
}
function statusOf(p) {
  if (p.enabled === false) return ["off", "Off"];
  if (!p.connected) return ["bad", "Needs attention"];
  return ["ok", "Connected"];
}

export async function modelsPane(pane, ctx, opts = {}) {
  const S = ctx.S;
  let data = await api.get("/api/providers");
  let view = opts.open && opts.open !== "__new__" ? { provider: opts.open, tab: opts.tab || "accounts" } : { provider: null };
  const root = el("div.mv");
  pane.append(root);

  const reload = async (o = {}) => {
    await ctx.reloadCatalog();
    data = await api.get("/api/providers");
    if (o.provider !== undefined) view = { provider: o.provider, tab: o.tab || "accounts" };
    if (view.provider && !data.configured.some((p) => p.id === view.provider)) view = { provider: null };
    draw("none");
  };
  const go = (next, dir) => { view = next; draw(dir); pane.closest(".m-scroll")?.scrollTo({ top: 0 }); };
  const afterSignIn = async (v) => reload({ provider: v.providerID || null });

  function draw(dir = "none") {
    const page = view.provider ? providerPage(data.configured.find((p) => p.id === view.provider)) : overview();
    page.classList.add("mv-page", `in-${dir}`);
    root.replaceChildren(page);
  }

  // ======================================================================================
  // Overview: default model, your providers, connect, account rules
  // ======================================================================================

  function overview() {
    const page = el("div");
    const configured = data.configured;
    if (opts.onboarding || !configured.length) {
      page.append(el("div.mv-welcome", logoMark(), el("div",
        el("h2", "Welcome to Agent Flow Harness"),
        el("p.lead", "Connect one model provider to start. Sign in with a plan you already pay for, paste an API key, or use a model running on this computer — those need no key at all."))));
    } else {
      page.append(el("h2", "Models & accounts"),
        el("p.lead", "The services AFH talks to, the accounts it uses for each, and which models show in the picker."));
    }

    // ---- OpenCode migration (one-time offer)
    const mig = S.migration || {};
    if (mig.db && !mig.done) {
      const status = el("div.help", { style: { padding: "0 20px 14px", color: "var(--text-3)" } });
      page.append(el("div.card", el("div.card-head", el("div", el("h3", "Import from OpenCode"), el("p", "AFH found an OpenCode install on this computer. Bring over its API keys, custom endpoints, MCP servers and threads.")),
        el("button.btn.primary.sm", { on: { click: async (e) => {
          e.currentTarget.disabled = true;
          status.replaceChildren(el("span.spinner"), " Importing…");
          const out = await guard(() => api.post("/api/migrate/opencode", { sessions: true }));
          if (out) {
            S.migration = { ...mig, done: true };
            status.textContent = `Imported ${out.providers?.added?.length || 0} providers, ${out.mcp?.length || 0} MCP servers and ${out.sessions?.imported || 0} threads.`;
            toast("OpenCode data imported", "ok");
            setTimeout(() => reload(), 1200);
          } else e.currentTarget.disabled = false;
        } } }, ico("arrow-down"), "Import")), status));
    }

    if (!configured.length) {
      // first run: the connect choices right here, no extra click
      const box = el("div.card.cn-inline");
      page.append(box);
      connectView(box, { inline: true });
      return page;
    }

    // ---- default model
    if (S.models.length) {
      const has = (r) => r && S.models.some((m) => m.id === r.id && m.providerID === r.providerID);
      const def = [S.settings.defaultModel, S.defaultModel].find(has);
      const m = def && S.models.find((x) => x.id === def.id && x.providerID === def.providerID);
      const change = el("button.btn.sm", { type: "button" }, ico("refresh"), "Change");
      change.addEventListener("click", () => modelPicker(change, {
        models: S.models, current: def, providerName: (pid) => S.providerNames?.[pid] || pid, align: "right", placeholder: "Search for the default model",
        onPick: (ref) => ctx.saveSettings({ defaultModel: { providerID: ref.providerID, id: ref.id } }).then(() => { toast("Default model saved", "ok", 1400); reload(); }),
      }));
      page.append(el("div.card.dm-card",
        el("div.dm-icon", ico("cpu")),
        el("div.dm-text", el("span.dm-label", "Default model"),
          el("b.dm-name", m ? m.name : "None chosen"),
          el("span.dm-sub", m ? [S.providerNames?.[m.providerID] || m.providerID, modelFacts(m)].filter(Boolean).join("  ·  ") : "Pick the model new threads start with")),
        el("div.dm-side", el("span.dm-count", `${S.models.length} in the picker`), change)));
    }

    // ---- providers
    const grid = el("div.pv-grid");
    for (const p of configured) grid.append(providerTile(p));
    grid.append(el("button.pv-tile.pv-new", { type: "button", on: { click: () => openConnect() } },
      el("span.pv-new-icon", ico("plus")), el("b", "Connect a provider"), el("span", "Sign in, paste a key, or find models on this computer")));
    const refreshAll = el("button.btn.ghost.sm", { type: "button", title: "Ask every provider for its current model list", on: { click: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.replaceChildren(el("span.spinner"), "Refreshing…");
      if (await guard(() => api.post("/api/models/refresh"), "Model lists refreshed")) await reload();
      b.disabled = false; b.replaceChildren(ico("refresh"), "Refresh models");
    } } }, ico("refresh"), "Refresh models");
    page.append(el("div.mv-section", el("div.mv-section-text", el("h3", "Your providers"), el("p", `${plural(configured.length, "provider")} · open one to manage its accounts and models`)),
      refreshAll, el("button.btn.primary.sm", { type: "button", on: { click: () => openConnect() } }, ico("plus"), "Connect")), grid);

    page.append(rulesCard(configured));
    return page;
  }

  function providerTile(p) {
    const [st, stText] = statusOf(p);
    const shown = p.models.filter((m) => !m.hidden).length;
    const usage = el("div.pv-usage");
    const tile = el(`button.pv-tile${p.enabled === false ? ".off" : ""}`, { type: "button", on: { click: () => go({ provider: p.id, tab: "accounts" }, "fwd") } },
      el("div.pv-top", mono(p.name, p.id), el("div.pv-name", el("b", p.name), el("span", howConnected(p))), el(`span.pv-state.${st}`, { title: stText }, el("i"), stText)),
      usage,
      el("div.pv-meta",
        el("span", ico("cpu"), `${shown} of ${p.models.length} models`),
        (p.accounts?.length || 0) > 1 ? el("span", ico("user"), plural(p.accounts.length, "account")) : null,
        el("span.pv-go", { html: icon("chev") })));
    if (p.accounts?.length && p.enabled !== false) {
      api.get(`/api/providers/${p.id}/accounts`).then((a) => {
        const act = (a.accounts || []).find((x) => x.state === "active") || (a.accounts || [])[0];
        const w = (act?.windows || []).filter((x) => x.usedPercent != null).sort((x, y) => y.usedPercent - x.usedPercent)[0];
        if (!w) return;
        const pct = Math.round(w.usedPercent);
        usage.replaceChildren(el("span.pv-u-label", `${act.label} · ${w.label}`), el(`span.pv-u-track${pct >= (a.prefs?.threshold || 90) ? ".hot" : pct >= 70 ? ".warm" : ""}`, el("i", { style: { width: `${Math.min(100, pct)}%` } })), el("span.pv-u-pct", `${pct}%`));
        usage.classList.add("on");
      }).catch(() => {});
    }
    return tile;
  }

  function rulesCard(configured) {
    const ap = { threshold: 90, order: "fill", whenAllUsed: "wait", ...(S.settings.accounts || {}) };
    const save = (patch) => { Object.assign(ap, patch); ctx.saveSettings({ accounts: { ...ap } }).then(() => toast("Saved", "ok", 1100)); };
    const thr = el("select.sel", { style: { width: "190px" }, on: { change: (e) => save({ threshold: Number(e.target.value) }) } },
      [70, 80, 85, 90, 95, 100].map((v) => el("option", { value: v, selected: Number(ap.threshold) === v }, v === 100 ? "Only when refused" : `At ${v}% of a limit`)));
    const seg = (key, options) => el("div.seg", options.map(([v, l]) => el(`button${ap[key] === v ? ".on" : ""}`, { type: "button", on: { click: (e) => {
      e.currentTarget.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.currentTarget)); save({ [key]: v });
    } } }, l)));
    const multi = configured.filter((p) => (p.accounts?.length || 0) > 1).length;
    return el("div.card",
      el("div.card-head", el("div", el("h3", "Several accounts"),
        el("p", multi ? `${multi === 1 ? "One provider has" : `${multi} providers have`} more than one account. AFH moves a running task to the next account, between steps, before the one in use runs out.`
          : "Give a provider a second key or sign-in and AFH moves to it before the first one runs out, between steps, without stopping the task."))),
      row("Switch", "When the account in use reaches this share of its 5-hour, weekly or other plan limit. A refused request switches at once.", thr),
      row("Order", "One after another uses each account fully and keeps the prompt cache warm.", seg("order", [["fill", "One after another"], ["least", "Least used first"]])),
      row("When every account is used up", null, seg("whenAllUsed", [["wait", "Wait, then continue"], ["stop", "Stop the task"]])),
      el("div.card-foot", ico("info"), el("span", "Google, OpenAI and xAI don't allow getting around their limits, and Kimi and Z.ai don't allow sharing accounts. Use accounts that are yours, at your own risk.")));
  }

  // ======================================================================================
  // One provider: Accounts · Models · Connection
  // ======================================================================================

  function providerPage(p) {
    const page = el("div.pv-page");
    const [st, stText] = statusOf(p);
    const back = el("button.mv-back", { type: "button", on: { click: () => go({ provider: null }, "back") } }, el("span", { html: icon("chev") }), "Models & accounts");
    const testBtn = el("button.btn.sm", { type: "button", title: "Send a tiny request to check the key and the address", on: { click: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.replaceChildren(el("span.spinner"), "Testing…");
      const out = await guard(() => api.post(`/api/providers/${p.id}/test`));
      b.disabled = false; b.replaceChildren(ico("check"), "Test");
      if (out) out.ok ? toast(`${p.name} works (${out.model})`, "ok") : toast(`${p.name}: ${out.error || "failed"}`, "err", 8000);
    } } }, ico("check"), "Test");
    const more = el("button.icon-btn", { type: "button", title: "More", html: icon("more") });
    more.addEventListener("click", () => popover(more, [
      { title: "Refresh models", sub: "Ask the provider for its list again", icon: "refresh", onSelect: async () => { if (await guard(() => api.post(`/api/providers/${p.id}/refresh`), "Models refreshed")) reload(); } },
      { title: p.enabled === false ? "Turn on" : "Turn off", sub: p.enabled === false ? "Show its models in the picker again" : "Keep it, but hide its models", icon: p.enabled === false ? "zap" : "eye", onSelect: async () => {
        if (await guard(() => api.post(`/api/providers/${p.id}/enabled`, { enabled: p.enabled === false }), p.enabled === false ? `${p.name} is on` : `${p.name} is off`)) reload();
      } },
      { sep: true },
      { title: p.signedIn && p.login && p.login !== "openrouter" ? "Sign out and remove" : "Remove provider", icon: "trash", danger: true, onSelect: () => removeProvider(p) },
    ], { align: "right", width: 250 }));

    const tabsDef = [["accounts", "Accounts", p.accounts?.length || 0], ["models", "Models", `${p.models.filter((m) => !m.hidden).length}/${p.models.length}`], ["connection", "Connection", null]];
    if (!tabsDef.some((t) => t[0] === view.tab)) view.tab = "accounts";
    const body = el("div.pv-body");
    const tabs = el("div.seg.pv-tabs", tabsDef.map(([id, label, n]) => el(`button${view.tab === id ? ".on" : ""}`, { type: "button", dataset: { tab: id }, on: { click: () => {
      if (view.tab === id) return;
      const from = tabsDef.findIndex((t) => t[0] === view.tab), to = tabsDef.findIndex((t) => t[0] === id);
      view.tab = id;
      tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
      drawTab(to > from ? "fwd" : "back");
    } } }, label, n !== null && n !== "" ? el("span.pv-tab-n", String(n)) : null)));
    const drawTab = (dir = "none") => {
      const inner = view.tab === "models" ? modelsTab(p) : view.tab === "connection" ? connectionTab(p) : accountsTab(p);
      inner.classList.add("pv-tab-body", `in-${dir}`);
      body.replaceChildren(inner);
    };
    page.append(back,
      el("div.pv-hero", mono(p.name, p.id, "lg"),
        el("div.pv-hero-text", el("h2", p.name), el("div.pv-hero-sub", el(`span.pv-state.${st}`, el("i"), stText), el("span", howConnected(p)), el("code", p.base_url || ""))),
        el("div.pv-hero-actions", testBtn, more)),
      tabs, body);
    drawTab();
    return page;
  }

  async function removeProvider(p) {
    const n = p.accounts?.length || 1;
    const signin = p.signedIn && p.login && p.login !== "openrouter";
    if (!(await confirmDialog({ title: `${signin ? "Sign out of" : "Remove"} ${p.name}?`,
      body: n > 1 ? `AFH forgets all ${n} accounts and removes the provider. Threads that used it keep their history.` : "AFH forgets its key or sign-in and removes it. Threads that used it keep their history. You can connect it again any time.",
      confirm: signin ? "Sign out" : "Remove", danger: true }))) return;
    const ok = await guard(() => (signin ? api.post(`/api/providers/${p.id}/logout`) : api.del(`/api/providers/${p.id}`)), `${p.name} removed`);
    if (ok) { view = { provider: null }; await reload(); }
  }

  // ---- Accounts ------------------------------------------------------------------------

  function accountsTab(p) {
    const wrap = el("div");
    const signInMethod = p.login && !["openrouter", "poe", "digitalocean", "chatgpt-web"].includes(p.login) ? p.login : null;
    const known = data.catalog.find((c) => c.id === p.catalog);
    const takesKey = !p.login || (known && known.needsKey !== false && known.login !== p.login) || p.accounts?.some((a) => a.kind === "key");
    const n = p.accounts?.length || 0;
    const list = el("div.ac-list");
    const autoRow = n > 1 ? row("Switch automatically", "Move to the next account before the one in use runs out. The rules are on the Models & accounts page.",
      toggle(p.rotation !== false, async (on) => { await guard(() => api.post(`/api/providers/${p.id}/rotation`, { enabled: on }), on ? "Automatic switching on" : "Automatic switching off"); p.rotation = on; })) : null;
    wrap.append(el("div.card",
      el("div.card-head", el("div", el("h3", n > 1 ? `${plural(n, "account")}` : "Account"),
        el("p", n > 1 ? "AFH uses one at a time, top first. Use, rename, reorder or turn off any of them." : "Add a second key or sign-in and AFH switches to it when this one nears its limit.")),
        el("div.ac-adds",
          signInMethod ? el("button.btn.sm", { type: "button", on: { click: () => signIn(signInMethod, { another: true, onDone: () => reload() }) } }, ico("plus"), "Sign in another") : null,
          takesKey ? el("button.btn.sm", { type: "button", on: { click: () => addKey(p) } }, ico("key"), "Add key") : null)),
      list, autoRow));

    const drawList = (acc) => {
      const items = acc?.accounts || (p.accounts || []).map((a) => ({ ...a, state: a.active ? "active" : a.enabled ? "ready" : "off", windows: [] }));
      if (!items.length) { list.replaceChildren(el("div.empty-row", "No key or sign-in yet. Add one above.")); return; }
      const thr = acc?.prefs?.threshold || 90;
      list.replaceChildren(...items.map((a, i) => {
        const stateText = a.state === "active" ? "In use" : a.state === "resting" ? `Resting until ${timeOf(a.restUntil)}` : a.state === "off" ? "Off" : "Ready";
        const bars = (a.windows || []).filter((w) => w.usedPercent != null).slice(0, 3).map((w) => {
          const pct = Math.round(w.usedPercent);
          return el(`div.ac-bar${pct >= thr ? ".hot" : pct >= 70 ? ".warm" : ""}`, { title: w.resetsAt ? `Resets ${new Date(w.resetsAt).toLocaleString()}` : "" },
            el("span.ab-label", w.label), el("span.ab-track", el("i", { style: { width: `${Math.min(100, pct)}%` } })), el("span.ab-pct", `${pct}%`));
        });
        const patch = (body, msg) => guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, body), msg).then((ok) => ok && load());
        const menu = el("button.icon-btn.sm", { type: "button", title: "More", html: icon("more") });
        menu.addEventListener("click", () => popover(menu, [
          { title: "Rename", icon: "edit", onSelect: () => renameAccount(p, a, load) },
          i > 0 ? { title: "Move up", icon: "arrow-up", onSelect: () => patch({ move: -1 }) } : null,
          i < items.length - 1 ? { title: "Move down", icon: "arrow-down", onSelect: () => patch({ move: 1 }) } : null,
          { title: a.state === "off" ? "Turn on" : "Turn off", sub: a.state === "off" ? "AFH may use it again" : "AFH skips it until you turn it on", icon: a.state === "off" ? "zap" : "eye", onSelect: () => patch({ enabled: a.state === "off" }) },
          { sep: true },
          { title: "Remove", icon: "trash", danger: true, onSelect: async () => {
            if (!(await confirmDialog({ title: `Remove ${a.label}?`, body: items.length === 1 ? "This is the provider's only account. AFH can't use the provider until you add a key or sign in again." : "AFH forgets this key or sign-in. The other accounts stay.", confirm: "Remove", danger: true }))) return;
            if (await guard(() => api.del(`/api/providers/${p.id}/accounts/${a.id}`), "Account removed")) reload();
          } },
        ].filter(Boolean), { align: "right", width: 230 }));
        return el(`div.ac-row.${a.state}`,
          el("span.ac-avatar", { style: { "--h": String(hue(a.label + a.id)) } }, initials(a.label), el("i.ac-dot")),
          el("div.ac-main",
            el("div.ac-title", el("b", a.label), el("span.ac-kind", a.kind === "signin" ? "sign-in" : a.keyHint ? `key ${a.keyHint}` : "key"), el(`span.ac-state.${a.state}`, stateText)),
            a.state === "resting" && a.restWhy ? el("div.ac-sub", a.restWhy) : a.usageError ? el("div.ac-sub", `Usage: ${a.usageError}`) : null,
            bars.length ? el("div.ac-bars", bars) : null),
          a.state !== "active" && a.state !== "off" ? el("button.btn.ghost.sm", { type: "button", title: "Use this account now", on: { click: () => patch({ active: true }, `Now using ${a.label}`) } }, "Use") : null,
          menu);
      }));
    };
    const load = async () => { try { drawList(await api.get(`/api/providers/${p.id}/accounts`)); } catch { drawList(null); } };
    drawList(null);
    if (n) load();
    return wrap;
  }

  function addKey(p) {
    const keyIn = el("input.inp", { type: "password", placeholder: "Paste another API key", autocomplete: "off" });
    const nameIn = el("input.inp", { placeholder: "Work account" });
    const go2 = async () => { if (await guard(() => api.post(`/api/providers/${p.id}/accounts`, { apiKey: keyIn.value, label: nameIn.value }), "Key added")) { dlg.close(); reload(); } };
    keyIn.addEventListener("keydown", (e) => e.key === "Enter" && go2());
    const dlg = modal(el("div.m-body.dlg", el("div.dlg-icon", ico("key")),
      el("h2", `Add a key to ${p.name}`),
      el("p.lead", "Use a key from a different account or project. Keys from the same account share one limit, so switching between them gains nothing."),
      field("API key", keyIn), field("Name (optional)", nameIn),
      el("div.actions", el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"), el("button.btn.primary", { on: { click: go2 } }, ico("plus"), "Add key"))), { small: true });
    setTimeout(() => keyIn.focus(), 30);
  }

  function renameAccount(p, a, done) {
    const inp = el("input.inp", { value: a.named ? a.label : "", placeholder: a.label });
    const save = async () => { if (await guard(() => api.patch(`/api/providers/${p.id}/accounts/${a.id}`, { label: inp.value }))) { dlg.close(); done(); } };
    inp.addEventListener("keydown", (e) => e.key === "Enter" && save());
    const dlg = modal(el("div.m-body.dlg", el("h2", "Rename account"), field("Name", inp),
      el("div.actions", el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"), el("button.btn.primary", { on: { click: save } }, "Save"))), { small: true });
    setTimeout(() => { inp.focus(); inp.select(); }, 30);
  }

  // ---- Models ---------------------------------------------------------------------------

  function modelsTab(p) {
    const wrap = el("div");
    const pending = new Map();
    let timer = 0;
    const status = el("span.mt-status");
    const count = el("span.mt-count");
    const q = el("input.inp.mt-q", { placeholder: `Filter ${p.models.length} models`, spellcheck: false });
    const list = el("div.mt-list");
    const shownNow = () => p.models.filter((m) => !(pending.has(m.id) ? pending.get(m.id) : m.hidden)).length;
    const setCount = () => (count.textContent = `${shownNow()} of ${p.models.length} in the picker`);
    // changes save on their own a moment after the last click
    const queue = (m, hidden) => {
      if (hidden === m.hidden) pending.delete(m.id); else pending.set(m.id, hidden);
      setCount();
      clearTimeout(timer);
      if (!pending.size) { status.replaceChildren(); return; }
      status.replaceChildren(el("span.spinner"), "Saving…");
      timer = setTimeout(async () => {
        const changes = [...pending.entries()].map(([id, h]) => ({ providerID: p.id, id, hidden: h }));
        const ok = await guard(() => api.post("/api/models/visibility", { changes }));
        if (!ok) { status.replaceChildren(); return; }
        for (const [id, h] of pending) { const m = p.models.find((x) => x.id === id); if (m) m.hidden = h; }
        pending.clear();
        status.replaceChildren(ico("check"), "Saved");
        ctx.reloadCatalog().catch(() => {});
        setTimeout(() => status.classList.add("fade"), 1400);
        status.classList.remove("fade");
      }, 650);
    };
    const drawModels = () => {
      const needle = q.value.trim().toLowerCase();
      const items = p.models.filter((m) => !needle || `${m.name} ${m.id}`.toLowerCase().includes(needle));
      if (!items.length) { list.replaceChildren(el("div.empty-row", p.models.length ? "No model matches." : "No models yet. Refresh the list from the ⋯ menu, or add model ids under Connection.")); return; }
      list.replaceChildren(...items.map((m) => {
        const hidden = pending.has(m.id) ? pending.get(m.id) : m.hidden;
        const r = el(`div.mt-row${hidden ? ".hidden" : ""}`,
          el("div.mt-main",
            el("div.mt-name", el("b", m.name), modalityBadges(m.input), m.reasoning ? el("span.mp-tag", "thinks") : null, m.tools === false ? el("span.mp-tag.warn", "no tools") : null, m.overridden ? el("span.mp-tag.acc", "edited") : null),
            el("div.mt-sub", [m.id !== m.name ? m.id : null, m.context ? `${fmtTokens(m.context)} context` : null, m.output ? `${fmtTokens(m.output)} out` : null, m.variants?.length ? `effort ${m.variants.join(" · ")}` : null].filter(Boolean).join("  ·  "))),
          el("button.icon-btn.sm", { type: "button", title: "Correct this model's context, effort levels or inputs", html: icon("edit"), on: { click: () => editModel(p, m) } }),
          toggle(!hidden, (on) => { r.classList.toggle("hidden", !on); queue(m, !on); }));
        return r;
      }));
    };
    const bulk = (hide) => { for (const m of p.models) queue(m, hide); drawModels(); };
    q.addEventListener("input", drawModels);
    wrap.append(el("div.card",
      el("div.mt-tools", el("label.mt-search", ico("search"), q), count, status, el("span.mp-grow"),
        el("button.btn.ghost.sm", { type: "button", on: { click: () => bulk(false) } }, "Show all"),
        el("button.btn.ghost.sm", { type: "button", on: { click: () => bulk(true) } }, "Hide all")),
      list));
    setCount();
    drawModels();
    return wrap;
  }

  /** Hand corrections for one model: AFH uses them over models.dev and the provider's own list. */
  function editModel(p, m) {
    const ctxIn = el("input.inp", { type: "number", min: 1000, value: m.context || "" });
    const outIn = el("input.inp", { type: "number", min: 256, value: m.output || "" });
    const effIn = el("input.inp", { value: (m.variants || []).join(", "), placeholder: "low, high, max" });
    const kinds = new Set(m.input || ["text"]);
    const checks = el("div.chk-row", ["image", "video", "audio", "pdf"].map((k) => {
      const box = el("input", { type: "checkbox", checked: kinds.has(k), on: { change: (e) => (e.target.checked ? kinds.add(k) : kinds.delete(k)) } });
      return el("label.chk", box, el("span", k));
    }));
    const save = async (reset) => {
      const body = reset ? {} : { context: Number(ctxIn.value) || null, output: Number(outIn.value) || null, variants: effIn.value.split(",").map((v) => v.trim()).filter(Boolean), input: ["text", ...[...kinds].filter((k) => k !== "text")] };
      if (await guard(() => api.put(`/api/providers/${p.id}/models/${encodeURIComponent(m.id)}`, body), reset ? "Back to the catalog's facts" : "Saved")) { dlg.close(); reload(); }
    };
    const dlg = modal(el("div.m-body.dlg",
      el("h2", `Edit ${m.name}`),
      el("p.lead", "AFH reads these from models.dev and the provider. Correct them here if they are wrong; your values win."),
      el("div.grid2", field("Context window (tokens)", ctxIn), field("Max output (tokens)", outIn)),
      field("Effort levels", effIn, "Comma-separated, as the API names them. “default” (no effort sent) is always offered."),
      field("Takes in besides text", checks),
      el("div.actions", m.overridden ? el("button.btn.ghost", { on: { click: () => save(true) } }, "Reset") : null, el("span", { style: { flex: 1 } }),
        el("button.btn.ghost", { on: { click: () => dlg.close() } }, "Cancel"), el("button.btn.primary", { on: { click: () => save(false) } }, "Save"))), { small: true });
  }

  // ---- Connection -----------------------------------------------------------------------

  function connectionTab(p) {
    const wrap = el("div");
    const signedIn = p.signedIn && p.login && p.login !== "openrouter";
    if (signedIn) {
      wrap.append(el("div.card",
        el("div.card-head", el("div", el("h3", "Sign-in"), el("p", p.account ? `Signed in as ${p.account}${(p.accounts?.length || 0) > 1 ? `, plus ${plural(p.accounts.length - 1, "more account")}` : ""}.` : "Signed in."))),
        row("Sign in again", "If the sign-in stopped working or expired.", el("button.btn.sm", { type: "button", on: { click: () => (p.login === "chatgpt-web" ? connectChatGPTWeb(afterSignIn) : signIn(p.login, { onDone: afterSignIn })) } }, ico("refresh"), "Sign in again")),
        row("Address", null, el("code.mv-code", p.base_url || ""))));
    } else {
      const box = el("div.card");
      wrap.append(box);
      providerForm(box, { existing: p });
    }
    wrap.append(el("div.card.danger-zone",
      row(p.enabled === false ? "Turned off" : "Turned on", p.enabled === false ? "Its models are hidden from the picker." : "Turn off to hide its models without removing it.",
        toggle(p.enabled !== false, async (on) => { if (await guard(() => api.post(`/api/providers/${p.id}/enabled`, { enabled: on }))) reload(); })),
      row(signedIn ? "Sign out and remove" : "Remove this provider", "Its keys, sign-ins and settings are deleted from AFH. Threads keep their history.",
        el("button.btn.sm.danger", { type: "button", on: { click: () => removeProvider(p) } }, ico("trash"), signedIn ? "Sign out" : "Remove"))));
    return wrap;
  }

  /** One form for a catalog provider, editing a configured one, or a custom endpoint. `done(out)` after saving. */
  function providerForm(box, { existing = null, cat = null, onCancel = null, done = null } = {}) {
    const isCustom = !cat && !(existing && existing.catalog);
    const catalogId = cat?.id || existing?.catalog || null;
    const known = catalogId ? data.catalog.find((c) => c.id === catalogId) : null;
    const f = {
      id: el("input.inp", { placeholder: "my-gateway", value: existing?.id || "", disabled: !!existing }),
      name: el("input.inp", { placeholder: "My gateway", value: existing?.name || known?.name || "" }),
      base_url: el("input.inp", { placeholder: known?.base_url || "http://localhost:11434/v1", value: existing?.base_url || (known?.params?.length ? "" : known?.base_url) || "" }),
      api_key: el("input.inp", { type: "password", placeholder: existing?.hasKey ? `Unchanged (${existing.keyHint})` : known && !known.needsKey ? "Optional" : "Paste your API key", autocomplete: "off" }),
      models: el("textarea.ta", { rows: 2, placeholder: "qwen3-coder:30b, llama4:scout — optional when the endpoint lists its models", value: (existing?.models || []).filter((m) => !m.fetched).map((m) => m.id).join(", ") }),
    };
    const paramFields = known?.params || [];
    const paramIns = Object.fromEntries(paramFields.map((x) => [x.name, el("input.inp", { placeholder: x.default || x.name, value: existing?.params?.[x.name] || x.default || "" })]));
    let kind = existing?.kind || known?.kind || "openai";
    const kindSeg = el("div.seg", [["openai", "OpenAI-compatible"], ["anthropic", "Anthropic"], ["gemini", "Gemini"]].map(([v, l]) => el(`button${v === kind ? ".on" : ""}`, { type: "button", on: { click: (e) => {
      kind = v; kindSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.currentTarget));
    } } }, l)));
    const advanced = !!known && !known.customUrl && !existing;
    const urlField = field(known && !known.customUrl ? "Base URL" : "Base URL", f.base_url, known && !known.customUrl ? "Only change this for a proxy or a regional address." : null);
    const more = advanced ? el("details.pf-more", el("summary", "Advanced: address and model ids"), urlField, field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them. Empty uses the list the endpoint reports.")) : null;
    const submit = el("button.btn.primary", { type: "button" }, existing ? "Save changes" : "Connect");
    submit.addEventListener("click", async () => {
      submit.disabled = true;
      const body = { id: existing?.id || (isCustom ? f.id.value.trim() : catalogId), catalog: isCustom ? null : catalogId, kind, name: f.name.value, base_url: f.base_url.value, api_key: f.api_key.value, models: f.models.value,
        params: Object.fromEntries(Object.entries(paramIns).map(([k, inp]) => [k, inp.value.trim()])) };
      const out = await guard(() => api.post("/api/providers", body), existing ? "Saved" : `${body.name || body.id} connected`);
      submit.disabled = false;
      if (!out) return;
      if (done) done(out); else reload({ provider: out.id, tab: "accounts" });
    });
    box.replaceChildren(
      el("div.card-head", el("div", el("h3", existing ? "Connection" : known ? `Connect ${known.name}` : "Custom endpoint"),
        el("p", existing ? "Change the key, address or model list." : known?.hint || (isCustom ? "Any server that speaks the OpenAI, Anthropic or Gemini API." : "Your key is stored only on this computer, in ~/.afh/providers.json."))),
        known?.docs ? el("button.btn.ghost.sm", { type: "button", on: { click: () => native.openExternal(known.docs) } }, ico("external"), "Get a key") : null),
      el("div.card-body.pf",
        known?.login && !existing ? el("div.pf-signin", ico("user"), el("span", "Have an account with a plan?"), el("button.btn.sm.primary", { type: "button", on: { click: () => signIn(known.login, { onDone: afterSignIn }) } }, "Sign in instead")) : null,
        isCustom ? field("API format", kindSeg) : null,
        isCustom ? el("div.grid2", field("Name", f.name), field("Id", f.id, "Lowercase letters and dashes")) : null,
        paramFields.length ? el("div.grid2", paramFields.map((x) => field(x.label, paramIns[x.name], `Also read from ${x.name}.`))) : null,
        field(existing ? "API key of the account in use" : "API key", f.api_key, known?.env?.[0] ? `AFH also reads ${known.env[0]} from your environment.` : null),
        advanced ? more : urlField,
        advanced ? null : field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them. Empty uses the list the endpoint reports."),
        el("div.actions", onCancel ? el("button.btn.ghost", { type: "button", on: { click: onCancel } }, "Back") : null, submit)));
    setTimeout(() => (isCustom && !existing ? f.id : paramFields.length && !existing ? Object.values(paramIns)[0] : f.api_key).focus(), 60);
  }

  // ======================================================================================
  // Connect: sign-ins, API keys, this computer and custom endpoints in one place
  // ======================================================================================

  function openConnect(start = "signin") {
    const shell = el("div.cn-modal");
    const dlg = modal(shell, { small: true });
    dlg.box.classList.add("cn-box");
    connectView(shell, { start, close: () => dlg.close() });
  }

  function connectView(host, { inline = false, start = "signin", close = null } = {}) {
    const byId = Object.fromEntries(data.configured.map((p) => [p.id, p]));
    const available = data.catalog.filter((c) => !c.configured);
    const FEATURED = ["openai", "anthropic", "gemini", "openrouter", "kimi", "zai-coding", "deepseek", "xai", "mistral", "groq", "azure", "amazon-bedrock", "ollama", "lmstudio"];
    const keyed = available.filter((c) => c.needsKey !== false && !LOCAL_IDS.has(c.id))
      .sort((a, b) => (FEATURED.indexOf(a.id) + 1 || 99) - (FEATURED.indexOf(b.id) + 1 || 99) || a.name.localeCompare(b.name));
    let cat = start;
    let query = "";
    const CATS = [["signin", "Sign in", "user", "With a plan you pay for"], ["key", "API key", "key", `${keyed.length} providers`], ["local", "This computer", "monitor", "Free and private"], ["custom", "Custom endpoint", "code", "Any compatible server"]];
    const q = el("input.cn-q", { placeholder: "Search providers: OpenAI, Gemini, Kimi, Ollama…", spellcheck: false, autocomplete: "off" });
    const rail = el("div.cn-rail");
    const list = el("div.cn-list");
    const stage = el("div.cn-stage", list);
    const finish = (out) => { close?.(); reload({ provider: out?.id || null, tab: "accounts" }); };
    const doSignIn = (x) => { close?.(); x.custom ? connectChatGPTWeb(afterSignIn) : signIn(x.method, { onDone: afterSignIn }); };
    const keyForm = (c) => {
      const box = el("div.card.cn-form");
      stage.replaceChildren(box);
      box.classList.add("in-fwd");
      providerForm(box, { cat: c, onCancel: () => { stage.replaceChildren(list); drawList(); }, done: finish });
    };
    const entry = (opts2) => el(`button.cn-item${opts2.on ? ".on" : ""}`, { type: "button", disabled: !!opts2.on, on: { click: opts2.click } },
      opts2.icon ? el("span.cn-ic", ico(opts2.icon)) : mono(opts2.title, opts2.id || opts2.title),
      el("span.cn-text", el("b", opts2.title, opts2.tag ? el("span.cn-tag", opts2.tag) : null), el("span", opts2.sub)),
      el("span.cn-go", opts2.on ? el("span.cn-done", ico("check"), "Connected") : { html: icon("chev") }));
    const signInItems = () => SIGN_INS.map((x) => {
      const have = byId[x.provider];
      const on = have && (have.signedIn || (x.method === "openrouter" && have.hasKey));
      return entry({ id: x.provider, icon: x.icon, title: x.name, sub: on ? (have.account ? `Signed in as ${have.account}` : "Connected") : x.sub, on, tag: x.warning ? "read first" : null, click: () => doSignIn(x) });
    });
    const keyItems = (pool) => pool.map((c) => entry({ id: c.id, title: c.name, sub: [c.params?.length ? `needs ${c.params.map((x) => x.label.toLowerCase()).join(", ")}` : null, c.models ? plural(c.models, "model") : null, c.kind !== "openai" ? c.kind : null].filter(Boolean).join(" · ") || "API key",
      tag: c.login ? "or sign in" : null, click: () => keyForm(c) }));
    const drawList = () => {
      rail.querySelectorAll(".cn-cat").forEach((b) => b.classList.toggle("on", !query && b.dataset.cat === cat));
      const parts = [];
      if (query) {
        const words = query.split(/\s+/);
        const hit = (s) => words.every((w) => s.toLowerCase().includes(w));
        const s = SIGN_INS.filter((x) => hit(`${x.name} ${x.provider} ${x.sub}`));
        const k = keyed.filter((c) => hit(`${c.name} ${c.id}`)).slice(0, 60);
        if (s.length) parts.push(el("div.cn-group", "Sign in"), ...signInItems().filter((_, i) => s.includes(SIGN_INS[i])));
        if (k.length) parts.push(el("div.cn-group", "API key"), ...keyItems(k));
        if (!parts.length) parts.push(el("div.cn-empty", ico("search"), el("b", "No provider by that name"), el("span", "Add it as a custom endpoint if it speaks the OpenAI, Anthropic or Gemini API."),
          el("button.btn.sm", { type: "button", on: { click: () => { q.value = ""; query = ""; cat = "custom"; drawList(); } } }, ico("code"), "Custom endpoint")));
      } else if (cat === "signin") {
        parts.push(el("p.cn-lead", "Use a plan you already pay for, no API key. Anthropic doesn't allow Claude Pro or Max in other apps: use an API key for Claude, or Claude through Copilot."), ...signInItems());
      } else if (cat === "key") {
        parts.push(el("p.cn-lead", "Paste a key from the provider's website. Keys stay on this computer."), ...keyItems(keyed.slice(0, 80)));
        if (keyed.length > 80) parts.push(el("div.cn-more", `${keyed.length - 80} more. Search to find them.`));
      } else if (cat === "local") {
        const box = el("div.cn-local", el("div.cn-scan", el("span.spinner"), "Looking for Ollama, LM Studio, vLLM, llama.cpp and Jan…"));
        parts.push(el("p.cn-lead", "Models running on this computer: free, private, no key."), box);
        api.get("/api/providers/detect-local").then((found) => {
          box.replaceChildren(...(found.length ? found.map((srv) => entry({ id: srv.id || srv.name, icon: "monitor", title: srv.name, on: srv.configured,
            sub: `${plural(srv.models.length, "model")} · ${srv.base_url}`, click: async (e) => {
              e.currentTarget.disabled = true;
              const body = srv.catalog ? { catalog: srv.catalog, id: srv.catalog } : { id: srv.id, name: srv.name, kind: "openai", base_url: srv.base_url };
              const out = await guard(() => api.post("/api/providers", body), `${srv.name} added with ${plural(srv.models.length, "model")}`);
              if (out) finish(out); else e.currentTarget.disabled = false;
            } })) : [el("div.cn-empty", ico("monitor"), el("b", "Nothing running right now"), el("span", "Start Ollama, LM Studio, vLLM, llama.cpp or Jan, then look again."),
            el("button.btn.sm", { type: "button", on: { click: () => drawList() } }, ico("refresh"), "Look again"))]));
        }).catch((e) => box.replaceChildren(el("div.cn-empty", ico("alert"), el("b", "Couldn't look"), el("span", e.message))));
      } else if (cat === "custom") {
        const box = el("div.card.cn-form");
        parts.push(box);
        providerForm(box, { done: finish });
      }
      list.replaceChildren(...parts);
      list.scrollTop = 0;
    };
    rail.append(...CATS.map(([id, label, ic, sub]) => el("button.cn-cat", { type: "button", dataset: { cat: id }, on: { click: () => { cat = id; q.value = ""; query = ""; stage.replaceChildren(list); drawList(); } } },
      ico(ic), el("span", el("b", label), el("small", sub)))));
    q.addEventListener("input", () => { query = q.value.trim().toLowerCase(); stage.replaceChildren(list); drawList(); });
    host.append(
      inline ? null : el("div.cn-head", el("div", el("h2", "Connect a provider"), el("p", "Pick how you want to connect. You can add more accounts to it afterwards.")),
        el("button.icon-btn", { type: "button", title: "Close", html: icon("x"), on: { click: () => close?.() } })),
      el("label.cn-search", ico("search"), q),
      el("div.cn-cols", rail, stage));
    drawList();
    if (!inline) setTimeout(() => q.focus(), 40);
  }

  function logoMark() { return el("span.mv-logo", ico("sparkle")); }

  if (opts.connect || opts.open === "__new__") setTimeout(() => openConnect(opts.open === "__new__" ? "custom" : "signin"), 120);
  draw();
}

const row = (title, sub, control) => el("div.row", el("div.rl", el("b", title), sub ? el("span", sub) : null), control);
