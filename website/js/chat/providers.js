// The model providers: the desktop's list (assets/providers.json, the same file the phone app ships),
// with brand colours and key pages for the ones people pick most.
import { settings } from "./store.js";

const LOOKS = {
  openai: ["#10A37F", "GPT models", "https://platform.openai.com/api-keys", "sk-…"],
  anthropic: ["#D97757", "Claude Opus, Sonnet and Haiku", "https://console.anthropic.com/settings/keys", "sk-ant-…"],
  gemini: ["#4F8DF7", "Gemini Pro and Flash", "https://aistudio.google.com/apikey", "AIza…"],
  chatgpt: ["#10A37F", "Use your ChatGPT Plus, Pro or Team plan"],
  "github-copilot": ["#8B949E", "Use your GitHub Copilot plan"],
  openrouter: ["#8B7CF6", "Hundreds of models with one account", "https://openrouter.ai/keys", "sk-or-…"],
  kimi: ["#3B82F6", "Kimi coding plan", "https://platform.kimi.ai"],
  moonshot: ["#6366F1", "Kimi models", "https://platform.moonshot.ai/console/api-keys", "sk-…"],
  zai: ["#2563EB", "GLM models", "https://z.ai/manage-apikey/apikey-list"],
  "zai-coding": ["#1D4ED8", "GLM coding plan", "https://z.ai/manage-apikey/apikey-list"],
  deepseek: ["#4D6BFE", "DeepSeek chat and reasoner", "https://platform.deepseek.com/api_keys", "sk-…"],
  groq: ["#F55036", "Very fast open models", "https://console.groq.com/keys", "gsk_…"],
  mistral: ["#FF7000", "Mistral Large, Medium and Codestral", "https://console.mistral.ai/api-keys"],
  xai: ["#A3A3A3", "Grok models", "https://console.x.ai", "xai-…"],
  together: ["#0F6FFF", "Open models in the cloud", "https://api.together.ai/settings/api-keys"],
  fireworks: ["#7C3AED", "Fast open models", "https://fireworks.ai/account/api-keys", "fw_…"],
  cerebras: ["#F97316", "The fastest open models", "https://cloud.cerebras.ai", "csk-…"],
  perplexity: ["#20B8CD", "Sonar models that search the web", "https://www.perplexity.ai/settings/api", "pplx-…"],
  ollama: ["#9CA3AF", "Ollama on this computer"],
  lmstudio: ["#6D28D9", "LM Studio on this computer"],
  vllm: ["#0EA5E9", "vLLM on a server you run"],
  custom: ["#BDB0A5", "Any other OpenAI-compatible server"],
};

function hashColor(id) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) & 0x7fffffff;
  return `hsl(${h % 360} 55% 55%)`;
}

export class Provider {
  constructor(j) {
    this.id = j.id;
    this.name = j.name;
    this.wire = j.wire;
    this.base = j.base || "";
    this.docs = j.docs || "";
    this.featured = !!j.featured;
    this.fallback = j.models || [];
    this.login = j.login || null;
    this.loginOnly = !!j.loginOnly;
    this.noKey = !!j.noKey;
    this.local = !!j.local;
    this.noFetch = !!j.noFetch;
    this.params = (j.params || []).map((p) => ({ name: p.name, label: p.label, fallback: p.default || "" }));
    this.hint = j.hint || "";
    this.headers = j.headers || {};
    this.authHeader = (j.authHeader || "authorization").toLowerCase();
    this.authPrefix = j.authPrefix ?? "Bearer ";
    const look = LOOKS[this.id] || [];
    this.color = look[0] || hashColor(this.id);
    this.blurb = look[1] || (this.wire === "anthropic" ? "Anthropic-compatible API" : this.wire === "gemini" ? "Gemini API" : this.local ? "A server on this computer" : "OpenAI-compatible API");
    this.keysUrl = look[2] || this.docs;
    this.keyHint = look[3] || "";
  }

  get custom() { return this.id === "custom"; }
  get needsAddress() { return this.custom || this.local; }
  get signedIn() { return !!settings.auth[this.id]; }
  get initial() { return (this.name.replace(/[^A-Za-z0-9]/g, "")[0] || "?").toUpperCase(); }

  /** Something the user set up: a key, a sign-in, or (for local servers) an address. */
  get ready() {
    if (this.loginOnly) return this.signedIn;
    if (settings.keys[this.id]) return true;
    return this.needsAddress && !!settings.base[this.id];
  }

  /** The address requests go to: the user's own, or the built-in one with its fields filled in. */
  baseUrl() {
    let url = settings.base[this.id] || (this.local ? "" : this.base);
    url = url.replace(/\$\{([A-Z0-9_]+)\}/g, (m, name) => {
      const p = this.params.find((x) => x.name === name);
      const v = settings.params[this.id]?.[name] || p?.fallback || "";
      return v || m;
    });
    url = url.replace(/\/+$/, "");
    if (!url) return url;
    if (this.wire === "anthropic" && !url.endsWith("/v1")) url += "/v1";
    if (this.wire === "gemini" && !/\/v1(beta)?$/.test(url)) url += "/v1beta";
    return url;
  }
  get missingParams() { return /\$\{/.test(this.baseUrl()); }

  get models() {
    const got = settings.models[this.id];
    return got?.length ? got : this.fallback;
  }
}

export let providers = [];

export async function loadProviders() {
  const j = await (await fetch("/assets/providers.json")).json();
  const list = j.providers.map((p) => new Provider(p));
  const cut = list.map((p) => p.featured).lastIndexOf(true) + 1;
  list.splice(cut, 0, new Provider({ id: "custom", name: "Custom server", wire: "openai", base: "", featured: true, noKey: true }));
  providers = list;
}

export const providerById = (id) => providers.find((p) => p.id === id);
