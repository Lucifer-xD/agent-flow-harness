// Settings → Models & providers: connect by sign-in or API key, hide models you don't use,
// add your own endpoints.

import { api, native } from "./api.js";
import { confirmDialog, el, fmtTokens, ico, icon, toast, toggle } from "./ui.js";

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);

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

export async function modelsPane(pane, ctx, opts = {}) {
  const S = ctx.S;
  const redraw = () => ctx.redraw("models");
  pane.append(...header("Models & providers", "Sign in with the subscriptions you already pay for, or paste an API key. Then keep only the models you actually use in the picker."));

  // ---- default model
  const def = S.settings.defaultModel || S.defaultModel;
  const sel = el("select.sel", { style: { width: "340px" }, on: { change: (e) => {
    const [providerID, ...rest] = e.target.value.split("/");
    ctx.saveSettings({ defaultModel: { providerID, id: rest.join("/") } }).then(() => toast("Default model saved", "ok"));
  } } });
  for (const m of S.models) sel.append(el("option", { value: `${m.providerID}/${m.id}`, selected: def && def.id === m.id && def.providerID === m.providerID }, `${m.name}  —  ${m.providerID}`));
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Default model"), el("p", `${S.models.length} models in the picker`)), sel)));

  const data = await api.get("/api/providers");
  const connected = data.integrations.filter((i) => i.connected);
  const available = data.integrations.filter((i) => !i.connected && (i.methods.includes("key") || i.oauth.length));

  // ---- connected providers with their models
  const pending = new Map(); // "pid/mid" -> hidden
  const applyBar = el("div.apply-bar", { hidden: true },
    el("span", "Model visibility changed."),
    el("button.btn.ghost.sm", { on: { click: () => { pending.clear(); redraw(); } } }, "Discard"),
    el("button.btn.primary.sm", { on: { click: async () => {
      const changes = [...pending.entries()].map(([k, hidden]) => { const [providerID, ...rest] = k.split("/"); return { providerID, id: rest.join("/"), hidden }; });
      if (await guard(() => api.post("/api/models/visibility", { changes }))) pending.clear();
    } } }, "Apply (restarts OpenCode)"));
  const list = el("div");
  for (const i of connected) list.append(providerCard(i));
  if (!connected.length) list.append(el("div.empty-row", "No providers connected yet — add one below."));
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Your providers"), el("p", "Toggle which models appear in the model picker")), el("button.btn.sm", { title: "Ask every provider for its current model list", on: { click: async () => { if (await guard(() => api.post("/api/models/refresh"), "Model lists refreshed")) { await ctx.reloadCatalog(); redraw(); } } } }, ico("refresh"), "Refresh models")), list, applyBar));

  function providerCard(i) {
    const cred = i.credentials.find((cr) => cr.active) || i.credentials[0];
    const how = i.custom ? "custom endpoint" : cred ? (cred.type === "oauth" ? "signed in" : cred.type === "key" ? `API key ${cred.hint || ""}` : cred.type) : "available";
    const shown = i.models.filter((m) => !m.hidden).length;
    const body = el("div.model-list");
    const q = el("input.inp", { placeholder: "Filter models…", style: { height: "30px", fontSize: "12.5px", width: "200px" } });
    const drawModels = () => {
      body.replaceChildren();
      const needle = q.value.toLowerCase();
      const rows = i.models.filter((m) => !needle || `${m.name} ${m.id}`.toLowerCase().includes(needle));
      if (!rows.length) body.append(el("div.empty-row", i.models.length ? "No model matches" : "This provider reports no models (check its key or plan)."));
      for (const m of rows) {
        const key = `${i.id}/${m.id}`;
        const hidden = pending.has(key) ? pending.get(key) : m.hidden;
        body.append(el(`div.model-row${hidden ? ".hidden" : ""}`,
          el("div.li-main", el("div.li-title", m.name, m.status === "deprecated" ? el("span.pill-tag", "deprecated") : null, m.tools === false ? el("span.pill-tag", "no tools") : null),
            el("div.li-sub", `${m.id}${m.context ? ` · ${fmtTokens(m.context)} ctx` : ""}${m.variants?.length ? ` · effort: ${m.variants.join(", ")}` : ""}`)),
          toggle(!hidden, (on) => { if (on === !m.hidden) pending.delete(key); else pending.set(key, !on); applyBar.hidden = !pending.size; })));
      }
    };
    q.addEventListener("input", drawModels);
    drawModels();
    const bulk = (hide) => { for (const m of i.models) { const key = `${i.id}/${m.id}`; if (hide === m.hidden) pending.delete(key); else pending.set(key, hide); } applyBar.hidden = !pending.size; drawModels(); };
    const card = el("div.provider", { open: opts.open === i.id },
      el("summary.provider-head",
        el("span.status-dot.connected"),
        el("div.li-main", el("div.li-title", i.name, el("span.pill-tag", how)), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, `${shown} of ${i.models.length} models shown`)),
        el("span.chev", { html: icon("chev-down") })),
      el("div.provider-body",
        el("div.provider-tools", q, el("span", { style: { flex: 1 } }),
          el("button.btn.ghost.sm", { on: { click: () => bulk(false) } }, "Show all"), el("button.btn.ghost.sm", { on: { click: () => bulk(true) } }, "Hide all"),
          i.oauth.length || i.methods.includes("key") ? el("button.btn.ghost.sm", { title: "Add another key or sign in again", on: { click: () => showConnect(i) } }, ico("key"), "Reconnect") : null,
          i.credentials.length ? el("button.btn.ghost.sm.danger", { on: { click: async () => { if (await confirmDialog({ title: `Disconnect ${i.name}?`, body: "Removes its saved key or sign-in. You can connect again any time.", confirm: "Disconnect", danger: true })) { await guard(() => api.del(`/api/credentials/by-integration/${i.id}`), "Disconnected"); await ctx.reloadCatalog(); redraw(); } } } }, ico("x"), "Disconnect") : null,
          el("button.btn.ghost.sm.danger", { title: i.custom ? "Delete this endpoint" : "Remove this provider from AFH (you can restore it below)", on: { click: async () => {
            if (!(await confirmDialog({ title: `Remove ${i.name}?`, body: i.custom ? "The endpoint is deleted. OpenCode restarts." : "Its models leave the picker and AFH stops loading it. It stays in your OpenCode config; restore it any time from “Removed providers”. OpenCode restarts.", confirm: "Remove", danger: true }))) return;
            guard(() => i.custom ? api.del(`/api/providers/custom/${i.id}`) : api.post(`/api/providers/${i.id}/remove`));
          } } }, ico("trash"), "Remove")),
        body));
    card.replaceWith(); // (details element is created below so <summary> works)
    const details = el("details.provider", { open: opts.open === i.id || connected.length <= 2 });
    details.append(...card.childNodes);
    return details;
  }

  if (data.hidden?.length) {
    pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Removed providers"), el("p", "Not loaded. Restore to bring their models back."))),
      el("div", data.hidden.map((h) => el("div.list-item", ico("x"), el("div.li-main", el("div.li-title", h.name), el("div.li-sub", h.id)),
        el("button.btn.sm", { on: { click: () => guard(() => api.post(`/api/providers/${h.id}/restore`)) } }, ico("refresh"), "Restore"))))));
  }

  // ---- add a provider
  const search = el("input.inp", { placeholder: `Search ${available.length} providers — OpenAI, Anthropic, Google, OpenRouter, Groq, Mistral…` });
  const results = el("div", { style: { maxHeight: "260px", overflowY: "auto", marginTop: "8px" } });
  const connectBox = el("div");
  const featured = ["openai", "anthropic", "google", "github-copilot", "openrouter", "groq", "mistral", "xai", "deepseek", "ollama"];
  const drawResults = () => {
    const needle = search.value.toLowerCase();
    const rows = available.filter((i) => !needle || `${i.name} ${i.id}`.toLowerCase().includes(needle));
    rows.sort((a, b) => (featured.indexOf(a.id) + 1 || 99) - (featured.indexOf(b.id) + 1 || 99) || a.name.localeCompare(b.name));
    results.replaceChildren(...rows.slice(0, 60).map((i) => el("button.pop-item", { type: "button", on: { click: () => showConnect(i) } },
      el("div.pi-main", el("div.pi-title", i.name), el("div.pi-sub", i.oauth.length ? i.oauth.map((o) => o.label).join(" · ") : i.env[0] ? `API key (or env ${i.env[0]})` : "API key")),
      i.oauth.length ? el("span.pill-tag.accent", "sign in") : null)));
    if (!rows.length) results.append(el("div.empty-row", "No provider matches. Add it as a custom endpoint below."));
  };
  search.addEventListener("input", drawResults);
  drawResults();
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Add a provider"), el("p", "Providers with “sign in” use your existing subscription instead of an API key"))), el("div.card-body", search, results), connectBox));

  function showConnect(i) {
    connectBox.replaceChildren();
    const box = el("div.inline-form");
    connectBox.append(box);
    const title = el("div", { style: { fontWeight: 600, marginBottom: "10px", display: "flex", alignItems: "center", gap: "8px" } }, `Connect ${i.name}`, el("span", { style: { flex: 1 } }), el("button.icon-btn", { html: icon("x"), on: { click: () => connectBox.replaceChildren() } }));
    box.append(title);
    const methods = el("div.methods");
    for (const m of i.oauth) methods.append(el("button.btn", { on: { click: () => startOauth(i, m, box) } }, ico("user"), m.label || "Sign in"));
    if (i.methods.includes("key")) methods.append(el("button.btn", { on: { click: () => keyForm(i, box) } }, ico("key"), "Use an API key"));
    box.append(methods, el("div.help", { style: { fontSize: "12px", color: "var(--text-3)", marginTop: "10px" } }, i.env.length ? `Also works if ${i.env[0]} is set in your environment.` : ""));
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function keyForm(i, box) {
    const key = el("input.inp", { type: "password", placeholder: "Paste API key", autocomplete: "off" });
    const label = el("input.inp", { placeholder: "Label (optional)" });
    const form = el("div", { style: { marginTop: "12px" } }, el("div.grid2", field("API key", key), field("Label", label)),
      el("div.actions", el("button.btn.primary", { on: { click: async () => {
        if (await guard(() => api.post("/api/credentials", { integrationID: i.id, key: key.value, label: label.value }), `${i.name} connected`)) { await ctx.reloadCatalog(); ctx.redraw("models", { open: i.id }); }
      } } }, "Connect")));
    box.querySelector(".oauth-flow, .key-flow")?.remove();
    form.className = "key-flow";
    box.append(form);
    key.focus();
  }

  async function startOauth(i, m, box) {
    box.querySelector(".oauth-flow, .key-flow")?.remove();
    const flow = el("div.oauth-flow", { style: { marginTop: "12px" } });
    box.append(flow);
    let answer = null;
    if (m.form?.length) {
      // e.g. GitHub Copilot asks for the deployment type first
      answer = {};
      const fields = [];
      for (const f of m.form) {
        let input;
        if (f.options?.length) input = el("select.sel", f.options.map((o) => el("option", { value: o.value }, o.label || o.value)));
        else input = el("input.inp", { placeholder: f.placeholder || "" });
        fields.push(field(f.title || f.key, input, f.description));
        input.addEventListener("change", () => (answer[f.key] = input.value));
        answer[f.key] = input.value;
      }
      await new Promise((resolve) => {
        flow.append(...fields, el("div.actions", el("button.btn.primary", { on: { click: resolve } }, "Continue")));
      });
      flow.replaceChildren();
    }
    const status = el("div.oauth-status", el("span.spinner"), el("span", "Starting sign-in…"));
    flow.append(status);
    let attempt;
    try {
      attempt = await api.post(`/api/integrations/${i.id}/oauth`, { methodId: m.id, answer });
    } catch (e) {
      status.replaceChildren(ico("alert"), el("span", e.message));
      return;
    }
    const aid = attempt.attemptID || attempt.attempt_id;
    const url = attempt.url;
    if (url) native.openExternal(url);
    const codeInput = el("input.inp", { placeholder: "Paste the code shown after signing in", style: { maxWidth: "360px" } });
    status.replaceChildren(
      el("div", { style: { display: "flex", flexDirection: "column", gap: "8px" } },
        el("div", el("b", "Your browser opened the sign-in page. "), attempt.instructions || "Finish signing in there, then come back."),
        url ? el("div", el("a", { href: url, target: "_blank", rel: "noopener", style: { color: "var(--accent)" } }, "Open the sign-in page again")) : null,
        attempt.mode === "code" ? el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } }, codeInput, el("button.btn.primary", { on: { click: async () => { if (await guard(() => api.post(`/api/integrations/${i.id}/oauth/${aid}/complete`, { code: codeInput.value }))) poll(); } } }, "Complete")) : null,
        el("div", { style: { display: "flex", alignItems: "center", gap: "10px", color: "var(--text-3)", fontSize: "12.5px" } }, el("span.spinner"), el("span.oauth-wait", "Waiting for the sign-in to finish…"), el("button.btn.ghost.sm", { on: { click: async () => { stop = true; await api.del(`/api/integrations/${i.id}/oauth/${aid}`).catch(() => {}); connectBox.replaceChildren(); } } }, "Cancel"))));
    let stop = false;
    const poll = async () => {
      while (!stop) {
        await new Promise((r) => setTimeout(r, 2000));
        let st;
        try { st = await api.get(`/api/integrations/${i.id}/oauth/${aid}`); } catch { continue; }
        if (st.status === "complete") { toast(`${i.name} connected`, "ok"); await ctx.reloadCatalog(); ctx.redraw("models", { open: i.id }); return; }
        if (st.status === "failed" || st.status === "expired") { status.replaceChildren(ico("alert"), el("span", st.message || `Sign-in ${st.status}. Try again.`)); return; }
      }
    };
    poll();
  }

  // ---- custom endpoints
  const f = { id: el("input.inp", { placeholder: "ollama-local" }), name: el("input.inp", { placeholder: "Ollama (local)" }), baseURL: el("input.inp", { placeholder: "http://localhost:11434/v1" }), apiKey: el("input.inp", { type: "password", placeholder: "optional", autocomplete: "off" }), models: el("input.inp", { placeholder: "qwen3-coder:30b, llama4:scout" }) };
  let kind = "openai";
  const seg = el("div.seg", [["openai", "OpenAI-compatible"], ["anthropic", "Anthropic-compatible"]].map(([v, l]) => el(`button${v === kind ? ".on" : ""}`, { type: "button", on: { click: (e) => { kind = v; seg.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); } } }, l)));
  const form = el("div.inline-form", { hidden: true },
    field("API format", seg),
    el("div.grid2", field("Provider id", f.id), field("Display name", f.name)),
    el("div.grid2", field("Base URL", f.baseURL), field("API key", f.apiKey)),
    field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them."),
    el("div.actions", el("button.btn.ghost", { on: { click: () => (form.hidden = true) } }, "Cancel"),
      el("button.btn.primary", { on: { click: () => guard(() => api.post("/api/providers/custom", { kind, id: f.id.value, name: f.name.value, baseURL: f.baseURL.value, apiKey: f.apiKey.value, models: f.models.value })) } }, "Add endpoint")));
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Custom endpoint"), el("p", "Ollama, LM Studio, vLLM, a gateway, or any OpenAI/Anthropic-compatible server")), el("button.btn.sm", { on: { click: () => (form.hidden = !form.hidden) } }, ico("plus"), "Add")), form));
}
