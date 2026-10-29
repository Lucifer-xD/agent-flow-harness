// Settings → Models & providers: paste an API key for a known provider or add any
// OpenAI/Anthropic/Gemini-compatible endpoint, then keep only the models you use in the picker.

import { api, native } from "./api.js";
import { confirmDialog, el, fmtTokens, ico, icon, toast, toggle } from "./ui.js";

const header = (title, lead) => [el("h2", title), lead ? el("p.lead", lead) : null];
const field = (label, input, help) => el("div.field", el("label", label), input, help ? el("div.help", help) : null);

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
    const def = S.settings.defaultModel || S.defaultModel;
    const sel = el("select.sel", { style: { width: "340px" }, on: { change: (e) => {
      const [providerID, ...rest] = e.target.value.split("/");
      ctx.saveSettings({ defaultModel: { providerID, id: rest.join("/") } }).then(() => toast("Default model saved", "ok"));
    } } });
    for (const m of S.models) sel.append(el("option", { value: `${m.providerID}/${m.id}`, selected: def && def.id === m.id && def.providerID === m.providerID }, `${m.name}  —  ${S.providerNames?.[m.providerID] || m.providerID}`));
    pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Default model"), el("p", `${S.models.length} models in the picker`)), sel)));
  }

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

  function providerCard(p) {
    const how = p.catalog ? (p.hasKey ? `API key ${p.keyHint || ""}` : "no key") : `custom · ${p.kind}`;
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
          el("div.li-main", el("div.li-title", m.name, m.tools === false ? el("span.pill-tag", "no tools") : null, m.reasoning ? el("span.pill-tag", "reasoning") : null),
            el("div.li-sub", `${m.id}${m.context ? ` · ${fmtTokens(m.context)} ctx` : ""}${m.variants?.length ? ` · effort: ${m.variants.join(", ")}` : ""}`)),
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
        el("div.provider-tools", q, el("span", { style: { flex: 1 } }),
          el("button.btn.ghost.sm", { on: { click: () => bulk(false) } }, "Show all"), el("button.btn.ghost.sm", { on: { click: () => bulk(true) } }, "Hide all"),
          el("button.btn.ghost.sm", { title: "Fetch the model list again", on: { click: async () => { if (await guard(() => api.post(`/api/providers/${p.id}/refresh`), "Models refreshed")) { await ctx.reloadCatalog(); redraw({ open: p.id }); } } } }, ico("refresh")),
          testBtn,
          el("button.btn.ghost.sm", { title: "Change the key, URL or model list", on: { click: () => showForm(p) } }, ico("edit"), "Edit"),
          toggle(p.enabled !== false, async (on) => { if (await guard(() => api.post(`/api/providers/${p.id}/enabled`, { enabled: on }))) { await ctx.reloadCatalog(); redraw({ open: p.id }); } }),
          el("button.btn.ghost.sm.danger", { title: "Remove this provider and its key", on: { click: async () => {
            if (!(await confirmDialog({ title: `Remove ${p.name}?`, body: "Its key and settings are deleted from AFH. Threads that used it keep their history.", confirm: "Remove", danger: true }))) return;
            if (await guard(() => api.del(`/api/providers/${p.id}`), "Removed")) { await ctx.reloadCatalog(); redraw(); }
          } } }, ico("trash"), "Remove")),
        body));
    return details;
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
  const search = el("input.inp", { placeholder: `Search ${available.length} providers — OpenAI, Anthropic, Gemini, Kimi, Z.AI, DeepSeek, Groq, OpenRouter, Ollama…` });
  const results = el("div", { style: { maxHeight: "280px", overflowY: "auto", marginTop: "8px" } });
  const formBox = el("div");
  const featured = ["openai", "anthropic", "gemini", "kimi", "zai-coding", "deepseek", "openrouter", "groq", "xai", "mistral", "ollama", "lmstudio"];
  const drawResults = () => {
    const needle = search.value.toLowerCase();
    const rows = available.filter((c) => !needle || `${c.name} ${c.id}`.toLowerCase().includes(needle));
    rows.sort((a, b) => (featured.indexOf(a.id) + 1 || 99) - (featured.indexOf(b.id) + 1 || 99) || a.name.localeCompare(b.name));
    results.replaceChildren(...rows.map((c) => el("button.pop-item", { type: "button", on: { click: () => showForm(null, c) } },
      el("div.pi-main", el("div.pi-title", c.name), el("div.pi-sub", c.needsKey ? `API key${c.env?.[0] ? ` (or env ${c.env[0]})` : ""}` : "local server · no key needed")),
      el("span.pill-tag", c.kind))));
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
      base_url: el("input.inp", { placeholder: "http://localhost:11434/v1", value: existing?.base_url || known?.base_url || "" }),
      api_key: el("input.inp", { type: "password", placeholder: existing?.hasKey ? `unchanged (${existing.keyHint})` : known && !known.needsKey ? "optional" : "Paste API key", autocomplete: "off" }),
      models: el("textarea.ta", { rows: 2, placeholder: "qwen3-coder:30b, llama4:scout — optional when the endpoint lists its models", value: (existing?.models || []).filter((m) => !m.fetched).map((m) => m.id).join(", ") }),
    };
    let kind = existing?.kind || known?.kind || "openai";
    const seg = el("div.seg", [["openai", "OpenAI-compatible"], ["anthropic", "Anthropic"], ["gemini", "Gemini"]].map(([v, l]) => el(`button${v === kind ? ".on" : ""}`, { type: "button", on: { click: (e) => { kind = v; seg.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); } } }, l)));
    const title = existing ? `Edit ${existing.name}` : known ? `Connect ${known.name}` : "Custom endpoint";
    const box = el("div.inline-form",
      el("div", { style: { fontWeight: 600, marginBottom: "10px", display: "flex", alignItems: "center", gap: "8px" } }, title, el("span", { style: { flex: 1 } }),
        known?.docs ? el("a", { href: known.docs, target: "_blank", rel: "noopener", style: { color: "var(--accent)", fontSize: "12.5px" }, on: { click: (e) => { e.preventDefault(); native.openExternal(known.docs); } } }, "API docs") : null,
        el("button.icon-btn", { html: icon("x"), on: { click: () => formBox.replaceChildren() } })),
      isCustom ? field("API format", seg) : null,
      isCustom ? el("div.grid2", field("Provider id", f.id, "lowercase, letters and dashes"), field("Display name", f.name)) : null,
      el("div.grid2", field(known && !known.customUrl ? "Base URL (advanced)" : "Base URL", f.base_url), field("API key", f.api_key, known?.env?.[0] ? `Also read from ${known.env[0]} if set in your environment.` : null)),
      field("Model ids", f.models, "Comma-separated, exactly as the endpoint names them. Leave empty to use the list the endpoint reports."),
      el("div.actions", el("button.btn.ghost", { on: { click: () => formBox.replaceChildren() } }, "Cancel"),
        el("button.btn.primary", { on: { click: async (e) => {
          e.currentTarget.disabled = true;
          const body = { id: existing?.id || (isCustom ? f.id.value.trim() : catalogId), catalog: isCustom ? null : catalogId, kind, name: f.name.value, base_url: f.base_url.value, api_key: f.api_key.value, models: f.models.value };
          const out = await guard(() => api.post("/api/providers", body), existing ? "Saved" : `${body.name || body.id} added`);
          e.currentTarget.disabled = false;
          if (out) { await ctx.reloadCatalog(); redraw({ open: out.id }); }
        } } }, existing ? "Save" : "Connect")));
    formBox.append(box);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    (isCustom && !existing ? f.id : f.api_key).focus();
  }

  if (opts.open === "__new__") showForm(null, null);
}
