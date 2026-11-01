// Chat with a model provider from the browser, the same way the phone app does (app/lib/ai.dart):
// four wire formats — OpenAI chat completions, OpenAI Responses (ChatGPT sign-in), Anthropic
// messages and Gemini — and a tool loop: the model answers or asks for tools, the page runs them
// (each shows as a step) and sends the results back, until the model answers in plain text.
import { AiError, sseLines, xfetch } from "./net.js";
import { signedRequest } from "./signin.js";
import { settings } from "./store.js";
import { ToolError, toolContext, webTools } from "./tools.js";

export { AiError };

async function prepare(p, force = false) {
  if (p.loginOnly) return signedRequest(p, force);
  const key = settings.keys[p.id] || "";
  const h = { "content-type": "application/json", ...p.headers };
  if (p.wire === "anthropic") Object.assign(h, { "x-api-key": key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" });
  else if (p.wire === "gemini") h["x-goog-api-key"] = key;
  else {
    if (key) h[p.authHeader] = p.authPrefix + key;
    if (p.id === "openrouter") Object.assign(h, { "HTTP-Referer": "https://agentflowharness.com", "X-Title": "AFH" });
  }
  return { base: p.baseUrl(), headers: h };
}

function errorText(status, body) {
  try {
    const j = JSON.parse(body);
    const e = Array.isArray(j) ? j[0]?.error : j.error ?? j.response?.error;
    const m = e && typeof e === "object" ? e.message || e.type : e || j.message || j.detail;
    if (m && String(m).trim()) return String(m);
  } catch { /* not json */ }
  return ({ 401: "The provider refused the key. Check it in Settings → Providers.", 403: "The provider refused the key. Check it in Settings → Providers.",
    404: "That model isn't available with this key.", 429: "Rate limited or out of credit. Try again in a moment." })[status] || `The provider answered ${status}.`;
}

/** The models this key or sign-in can use. */
export async function fetchModels(p) {
  let { base, headers, ua } = await prepare(p);
  if (!base) throw new AiError("Enter the server address first.");
  if (p.missingParams) throw new AiError("Fill in every field above first.");
  const url = p.wire === "gemini" ? `${base}/models?pageSize=200` : p.wire === "anthropic" ? `${base}/models?limit=100`
    : p.id === "chatgpt" ? `${base}/models?client_version=99.0.0` : `${base}/models`;
  let res = await xfetch(url, { headers: { ...headers, accept: "application/json" }, ua });
  if (res.status === 401 && p.signedIn) {
    ({ base, headers, ua } = await prepare(p, true));
    res = await xfetch(url, { headers: { ...headers, accept: "application/json" }, ua });
  }
  if ((res.status === 404 || res.status === 405 || p.noFetch) && res.status !== 401 && res.status !== 403 && p.fallback.length) return p.fallback;
  const body = await res.text();
  if (!res.ok) throw new AiError(errorText(res.status, body));
  const j = JSON.parse(body);
  let ids;
  if (p.wire === "gemini") {
    ids = (j.models || []).filter((m) => (m.supportedGenerationMethods || []).includes("generateContent")).map((m) => m.name.replace("models/", ""));
    ids = ids.filter((id) => !/embedding|aqa|imagen|tts|image-generation|learnlm/.test(id));
  } else if (p.id === "chatgpt") {
    ids = (j.models || []).filter((m) => m?.slug && m.visibility !== "hide" && m.supported_in_api !== false).map((m) => m.slug);
    if (!ids.length) throw new AiError("ChatGPT listed no models for this plan.");
    return ids;
  } else {
    const items = Array.isArray(j) ? j : j.data || [];
    ids = [];
    for (const m of items) {
      if (typeof m === "string") { ids.push(m); continue; }
      if (!m?.id) continue;
      const caps = m.capabilities;
      if (caps && typeof caps === "object" && ((caps.type || "chat") !== "chat" || m.model_picker_enabled === false || m.policy?.state === "disabled")) continue;
      ids.push(m.id);
    }
    if (p.id === "openai") ids = ids.filter((id) => /^(gpt|o\d|chatgpt)/.test(id) && !/audio|realtime|tts|transcribe|image|search|instruct|embedding|moderation|codex/.test(id) && !/-\d{4}-\d{2}-\d{2}$/.test(id));
    ids = [...new Set(ids.filter((id) => !/embed|whisper|tts|moderation|guard|dall-e|rerank/.test(id)))];
  }
  if (!ids.length && p.fallback.length) return p.fallback;
  if (!["openrouter", "github-copilot"].includes(p.id) && p.wire !== "anthropic") ids.sort((a, b) => b.localeCompare(a));
  return ids;
}

const summary = (out) => {
  const first = out.trim().split("\n").find((l) => l.trim()) || "";
  return first.length > 90 ? first.slice(0, 88) + "…" : first;
};

/** A reply being streamed: `for await (const d of run.start())`, run.cancel() to stop. */
export class Run {
  constructor(provider, model, history, { system = "", env = null } = {}) {
    Object.assign(this, { provider, model, history, system, env });
    this.ctrl = new AbortController();
    this.items = [];
    this.tools = [];
  }
  cancel() { this.cancelled = true; this.ctrl.abort(); }

  get sys() { return [this.system.trim(), this.env ? toolContext() : ""].filter(Boolean).join("\n\n"); }

  build(msgs) {
    let budget = 4; // photos: only the last few go along
    const withImages = new Set();
    for (const m of [...msgs].reverse()) if (m.images?.length && budget > 0) { withImages.add(m); budget -= m.images.length; }
    const w = this.provider.wire;
    if (w === "openai" && this.sys) this.items.push({ role: "system", content: this.sys });
    for (const m of msgs) {
      const imgs = withImages.has(m) ? m.images.map((u) => { const [, mime, b64] = /^data:([^;]+);base64,(.*)$/.exec(u) || []; return { mime, b64, url: u }; }).filter((x) => x.b64) : [];
      const text = !m.text && imgs.length ? "What do you see?" : m.text;
      if (w === "openai") this.items.push({ role: m.role, content: imgs.length ? [{ type: "text", text }, ...imgs.map((i) => ({ type: "image_url", image_url: { url: i.url } }))] : text });
      else if (w === "responses") this.items.push(m.role === "user"
        ? { role: "user", content: [{ type: "input_text", text }, ...imgs.map((i) => ({ type: "input_image", image_url: i.url }))] }
        : { type: "message", role: "assistant", content: [{ type: "output_text", text }] });
      else if (w === "anthropic") this.items.push({ role: m.role, content: [...imgs.map((i) => ({ type: "image", source: { type: "base64", media_type: i.mime, data: i.b64 } })), { type: "text", text }] });
      else this.items.push({ role: m.role === "assistant" ? "model" : "user", parts: [...imgs.map((i) => ({ inline_data: { mime_type: i.mime, data: i.b64 } })), { text }] });
    }
  }

  toolSpecs() {
    const t = this.tools;
    switch (this.provider.wire) {
      case "openai": return t.map((x) => ({ type: "function", function: { name: x.name, description: x.description, parameters: x.schema } }));
      case "responses": return t.map((x) => ({ type: "function", name: x.name, description: x.description, parameters: x.schema, strict: false }));
      case "anthropic": return t.map((x) => ({ name: x.name, description: x.description, input_schema: x.schema }));
      default: return [{ functionDeclarations: t.map((x) => ({ name: x.name, description: x.description, ...(Object.keys(x.properties).length ? { parameters: x.schema } : {}) })) }];
    }
  }

  request(base) {
    const tools = this.tools.length ? this.toolSpecs() : undefined;
    const { model, items, sys } = this;
    switch (this.provider.wire) {
      case "openai": return [`${base}/chat/completions`, { model, stream: true, messages: items, tools }];
      case "responses": return [`${base}/responses`, { model, instructions: sys || "You are a helpful assistant.", input: items, tools, stream: true, store: false }];
      case "anthropic": return [`${base}/messages`, { model, stream: true, max_tokens: 8192, system: sys || undefined, messages: items, tools }];
      default: return [`${base}/models/${model}:streamGenerateContent?alt=sse`, { systemInstruction: sys ? { parts: [{ text: sys }] } : undefined, contents: items, tools }];
    }
  }

  async send(round) {
    const p = this.provider;
    for (let attempt = 0; attempt < 3; attempt++) {
      const { base, headers, ua } = await prepare(p, attempt > 0 && p.signedIn);
      if (!base) throw new AiError(`Set up ${p.name} first in Settings → Providers.`);
      const [url, body] = this.request(base);
      const h = { ...headers, accept: "text/event-stream" };
      if (p.id === "github-copilot") h["x-initiator"] = round === 0 ? "user" : "agent";
      let res;
      try {
        res = await xfetch(url, { method: "POST", headers: h, body: JSON.stringify(body), signal: this.ctrl.signal, ua });
      } catch (e) {
        if (this.cancelled) return null;
        throw e instanceof AiError ? e : new AiError(`Couldn't reach ${p.name}.`);
      }
      if (res.ok) return res;
      const text = await res.text();
      if (res.status === 401 && p.signedIn && attempt === 0) continue;
      if (this.tools.length && round === 0 && [400, 404, 422].includes(res.status) && /tool|function/i.test(text)) { this.tools = []; continue; }
      throw new AiError(errorText(res.status, text));
    }
    throw new AiError(`${p.name} kept refusing the request.`);
  }

  async *start() {
    const msgs = this.history.filter((m) => (m.text?.trim() || m.images?.length) && !m.error);
    this.tools = this.env && settings.tools ? webTools() : [];
    this.build(msgs);
    let wrote = false;
    try {
      for (let round = 0; round < 12; round++) {
        const res = await this.send(round);
        if (!res) return;
        const turn = { text: "", calls: [], byIndex: {}, byItem: {}, raw: [], parts: 0 };
        let gap = wrote;
        for await (const line of sseLines(res)) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data || data === "[DONE]") continue;
          let j;
          try { j = JSON.parse(data); } catch { continue; }
          const d = this.parse(j, turn);
          if (!d) continue;
          if (d.text) {
            turn.text += d.text;
            if (gap) { gap = false; yield { text: "\n\n" }; }
            wrote = true;
          }
          yield d;
        }
        if (!turn.calls.length || this.cancelled) return;
        const results = [];
        for (const c of turn.calls) {
          const tool = this.tools.find((t) => t.name === c.name);
          let args = c.args;
          if (!args) { try { args = c.raw.trim() ? JSON.parse(c.raw) : {}; } catch { args = {}; } }
          const step = { tool: c.name, label: tool ? tool.label(args) : c.name, state: "running", detail: "" };
          yield { step };
          let out;
          try {
            if (!tool) throw new ToolError(`There is no tool called ${c.name}.`);
            out = await tool.run(args, this.env, step);
            step.state = "done";
            step.detail = summary(out);
          } catch (e) {
            const why = e instanceof ToolError || e instanceof AiError ? e.message : `Something went wrong: ${e.message || e}`;
            out = `Error: ${why}`;
            step.state = "error";
            step.detail = why;
          }
          if (this.cancelled) return;
          yield { step };
          c.args = args;
          results.push(out);
        }
        this.append(turn, results);
      }
      yield { text: "\n\n_(Stopped after many tool steps.)_" };
    } catch (e) {
      if (this.cancelled) return;
      if (e instanceof AiError) throw e;
      throw new AiError(`The connection to ${this.provider.name} dropped.`);
    }
  }

  append(t, results) {
    const { text, calls } = t;
    switch (this.provider.wire) {
      case "openai":
        this.items.push({ role: "assistant", content: text || null, tool_calls: calls.map((c) => ({ id: c.id, type: "function", function: { name: c.name, arguments: JSON.stringify(c.args) } })) });
        calls.forEach((c, i) => this.items.push({ role: "tool", tool_call_id: c.id, content: results[i] }));
        break;
      case "responses":
        if (text) this.items.push({ type: "message", role: "assistant", content: [{ type: "output_text", text }] });
        calls.forEach((c, i) => {
          this.items.push({ type: "function_call", call_id: c.id, name: c.name, arguments: JSON.stringify(c.args) });
          this.items.push({ type: "function_call_output", call_id: c.id, output: results[i] });
        });
        break;
      case "anthropic":
        this.items.push({ role: "assistant", content: [...(text ? [{ type: "text", text }] : []), ...calls.map((c) => ({ type: "tool_use", id: c.id, name: c.name, input: c.args }))] });
        this.items.push({ role: "user", content: calls.map((c, i) => ({ type: "tool_result", tool_use_id: c.id, content: results[i] })) });
        break;
      default: // Gemini checks the thought signatures on its own parts: send them back as they came
        this.items.push({ role: "model", parts: [...(text ? [{ text }] : []), ...t.raw] });
        this.items.push({ role: "user", parts: calls.map((c, i) => ({ functionResponse: { name: c.name, ...(c.id.startsWith("call_") ? {} : { id: c.id }), response: { result: results[i] } } })) });
    }
  }

  parse(j, turn) {
    const errMsg = (e) => (e && typeof e === "object" ? e.message : e) || "The provider reported an error.";
    switch (this.provider.wire) {
      case "openai": {
        if (j.error) throw new AiError(errMsg(j.error));
        const d = j.choices?.[0]?.delta;
        if (!d) return null;
        (d.tool_calls || []).forEach((tc, n) => {
          const i = tc.index ?? n;
          let c = turn.byIndex[i];
          if (!c) { c = { id: `call_${i}`, name: "", raw: "" }; turn.byIndex[i] = c; turn.calls.push(c); }
          if (tc.id) c.id = tc.id;
          if (typeof tc.function?.name === "string") c.name += tc.function.name;
          if (typeof tc.function?.arguments === "string") c.raw += tc.function.arguments;
          else if (tc.function?.arguments && typeof tc.function.arguments === "object") c.args = tc.function.arguments;
        });
        const text = d.content || "", reasoning = d.reasoning_content || d.reasoning || "";
        return text || reasoning ? { text, reasoning: typeof reasoning === "string" ? reasoning : "" } : null;
      }
      case "responses":
        switch (j.type) {
          case "response.output_text.delta": return { text: j.delta || "" };
          case "response.reasoning_summary_text.delta": case "response.reasoning_text.delta": return { reasoning: j.delta || "" };
          case "response.reasoning_summary_part.added": return turn.parts++ > 0 ? { reasoning: "\n\n" } : null;
          case "response.output_item.added":
            if (j.item?.type === "function_call") {
              const c = { id: j.item.call_id || j.item.id, name: j.item.name || "", raw: j.item.arguments || "" };
              turn.calls.push(c);
              turn.byItem[j.item.id] = c;
            }
            return null;
          case "response.function_call_arguments.delta": { const c = turn.byItem[j.item_id]; if (c) c.raw += j.delta || ""; return null; }
          case "response.output_item.done": { const c = turn.byItem[j.item?.id]; if (c && typeof j.item.arguments === "string") c.raw = j.item.arguments; return null; }
          case "response.failed": throw new AiError(errMsg(j.response?.error));
          case "error": throw new AiError(j.message || errMsg(j.error));
          default: return null;
        }
      case "anthropic":
        switch (j.type) {
          case "content_block_start":
            if (j.content_block?.type === "tool_use") {
              const c = { id: j.content_block.id, name: j.content_block.name, raw: "" };
              turn.calls.push(c);
              turn.byIndex[j.index] = c;
            }
            return null;
          case "content_block_delta": {
            const d = j.delta || {};
            if (d.type === "text_delta") return { text: d.text || "" };
            if (d.type === "thinking_delta") return { reasoning: d.thinking || "" };
            if (d.type === "input_json_delta" && turn.byIndex[j.index]) turn.byIndex[j.index].raw += d.partial_json || "";
            return null;
          }
          case "error": throw new AiError(errMsg(j.error));
          default: return null;
        }
      default: {
        if (j.error) throw new AiError(errMsg(j.error));
        const parts = j.candidates?.[0]?.content?.parts || [];
        let text = "", reasoning = "";
        for (const pt of parts) {
          if (pt.functionCall) {
            turn.calls.push({ id: pt.functionCall.id || `call_${turn.calls.length}`, name: pt.functionCall.name, raw: "", args: pt.functionCall.args || {} });
            turn.raw.push(pt);
            continue;
          }
          if (pt.thought) reasoning += pt.text || ""; else text += pt.text || "";
        }
        return text || reasoning ? { text, reasoning } : null;
      }
    }
  }
}
