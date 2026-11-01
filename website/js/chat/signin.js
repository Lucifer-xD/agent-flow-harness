// Sign in to a provider instead of pasting a key — the same three ways as the phone and desktop:
//
//   openrouter  OAuth PKCE; OpenRouter sends the browser back here with a code for an API key
//   chatgpt     OAuth PKCE with the Codex client, whose only redirect is http://localhost:1455/…;
//               that page can't load, so the user pastes its address back in
//   copilot     GitHub device code; the GitHub token buys short-lived Copilot tokens
import { AiError, xfetch } from "./net.js";
import { save, settings } from "./store.js";

const CHATGPT_CLIENT = "app_EMoamEEZ73f0CkXaXp7hrann";
const CHATGPT_AUTH = "https://auth.openai.com/oauth/authorize";
const CHATGPT_TOKEN = "https://auth.openai.com/oauth/token";
const CHATGPT_REDIRECT = "http://localhost:1455/auth/callback";
export const CHATGPT_BASE = "https://chatgpt.com/backend-api/codex";

const COPILOT_CLIENT = "Iv1.b507a08c87ecfe98";
export const COPILOT_BASE = "https://api.githubcopilot.com";
const COPILOT_UA = "GitHubCopilotChat/0.26.0";
const COPILOT_HEADERS = { "editor-version": "vscode/1.99.0", "editor-plugin-version": "copilot-chat/0.26.0", "copilot-integration-id": "vscode-chat" };

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const random = (n) => b64url(crypto.getRandomValues(new Uint8Array(n)));
async function pkce() {
  const verifier = random(32);
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  return { verifier, challenge };
}
function claims(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(part))));
  } catch { return {}; }
}
const json = async (res) => { try { return await res.json(); } catch { return {}; } };

function setAuth(id, value) {
  const auth = { ...settings.auth };
  if (value) auth[id] = value; else delete auth[id];
  save({ auth });
}
export function signOut(id) {
  setAuth(id, null);
  if (id === "openrouter") { const keys = { ...settings.keys }; delete keys[id]; save({ keys }); }
}

// ---- OpenRouter ----------------------------------------------------------------------------------

export async function openrouterStart() {
  const { verifier, challenge } = await pkce();
  sessionStorage.setItem("afh.or", verifier);
  const back = `${location.origin}/chat?signin=openrouter`;
  location.href = `https://openrouter.ai/auth?${new URLSearchParams({ callback_url: back, code_challenge: challenge, code_challenge_method: "S256" })}`;
}

/** Back from OpenRouter with ?code=…: trade it for a key. Returns true when this page load was that. */
export async function openrouterFinish() {
  const q = new URLSearchParams(location.search);
  if (q.get("signin") !== "openrouter") return false;
  history.replaceState(null, "", "/chat" + location.hash);
  const verifier = sessionStorage.getItem("afh.or");
  sessionStorage.removeItem("afh.or");
  if (!q.get("code") || !verifier) throw new AiError("OpenRouter didn't finish the sign-in. Try again.");
  const res = await xfetch("https://openrouter.ai/api/v1/auth/keys", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ code: q.get("code"), code_verifier: verifier, code_challenge_method: "S256" }),
  });
  if (!res.ok) throw new AiError(`OpenRouter refused the sign-in (${res.status}).`);
  const key = (await json(res)).key;
  if (!key) throw new AiError("OpenRouter returned no key.");
  save({ keys: { ...settings.keys, openrouter: key } });
  return true;
}

// ---- ChatGPT -------------------------------------------------------------------------------------

/** Opens OpenAI's sign-in in a new tab; finish with chatgptFinish(the address it ends on). */
export async function chatgptStart() {
  const { verifier, challenge } = await pkce();
  const state = random(24);
  sessionStorage.setItem("afh.cg", JSON.stringify({ verifier, state }));
  const url = `${CHATGPT_AUTH}?${new URLSearchParams({
    response_type: "code", client_id: CHATGPT_CLIENT, redirect_uri: CHATGPT_REDIRECT, scope: "openid profile email offline_access",
    code_challenge: challenge, code_challenge_method: "S256", id_token_add_organizations: "true", codex_cli_simplified_flow: "true",
    state, originator: "codex_cli_rs",
  })}`;
  window.open(url, "_blank", "noopener");
}

function chatgptTokens(t, old = {}) {
  let c = claims(t.id_token || "");
  if (!Object.keys(c).length) c = claims(t.access_token || "");
  const info = c["https://api.openai.com/auth"] || {};
  return {
    type: "chatgpt",
    access: t.access_token || old.access || "",
    refresh: t.refresh_token || old.refresh || "",
    expires: Date.now() / 1000 + (t.expires_in || 3600),
    account_id: info.chatgpt_account_id || old.account_id || "",
    plan: info.chatgpt_plan_type || old.plan || "",
    account: c.email || old.account || "",
  };
}

export async function chatgptFinish(pasted) {
  let q;
  try { q = new URL(pasted.trim()).searchParams; } catch { throw new AiError("Paste the whole address from the tab that didn't load (it starts with http://localhost:1455)."); }
  const saved = JSON.parse(sessionStorage.getItem("afh.cg") || "null");
  if (!saved) throw new AiError("Start again with “Open ChatGPT sign-in”.");
  if (q.get("error")) throw new AiError(q.get("error_description") || q.get("error"));
  if (q.get("state") !== saved.state) throw new AiError("That address belongs to another sign-in. Start again.");
  if (!q.get("code")) throw new AiError("That address has no sign-in code in it.");
  const res = await xfetch(CHATGPT_TOKEN, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", code: q.get("code"), redirect_uri: CHATGPT_REDIRECT, client_id: CHATGPT_CLIENT, code_verifier: saved.verifier }).toString(),
  });
  if (!res.ok) throw new AiError(`OpenAI refused the sign-in (${res.status}). Codes work once and only for a few minutes — start again.`);
  const auth = chatgptTokens(await json(res));
  if (!auth.account_id) throw new AiError("This OpenAI account has no ChatGPT plan attached.");
  sessionStorage.removeItem("afh.cg");
  setAuth("chatgpt", auth);
  return auth.account;
}

// ---- GitHub Copilot ------------------------------------------------------------------------------

/** Device flow: onCode(code, url) shows the code to type on github.com; resolves when approved. */
export async function copilotSignIn(onCode, signal) {
  const res = await xfetch("https://github.com/login/device/code", {
    method: "POST", headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ client_id: COPILOT_CLIENT, scope: "read:user" }), signal,
  });
  if (!res.ok) throw new AiError(`GitHub refused the sign-in (${res.status}).`);
  const dev = await json(res);
  onCode(dev.user_code, dev.verification_uri || "https://github.com/login/device");
  let interval = dev.interval || 5;
  const deadline = Date.now() + 10 * 60 * 1000;
  let gh;
  while (!gh) {
    await new Promise((r, x) => { const t = setTimeout(r, interval * 1000); signal?.addEventListener("abort", () => { clearTimeout(t); x(new DOMException("", "AbortError")); }); });
    if (Date.now() > deadline) throw new AiError("The code expired. Try again.");
    const r = await xfetch("https://github.com/login/oauth/access_token", {
      method: "POST", headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify({ client_id: COPILOT_CLIENT, device_code: dev.device_code, grant_type: "urn:ietf:params:oauth:grant-type:device_code" }), signal,
    });
    const d = await json(r);
    if (d.access_token) gh = d.access_token;
    else if (d.error === "slow_down") interval += 5;
    else if (d.error !== "authorization_pending") throw new AiError(d.error_description || d.error || "GitHub stopped the sign-in.");
  }
  const user = await xfetch("https://api.github.com/user", { headers: { authorization: `token ${gh}` }, ua: COPILOT_UA });
  const login = user.ok ? (await json(user)).login || "" : "";
  const auth = await copilotToken({ type: "copilot", github: gh, account: login });
  setAuth("github-copilot", auth);
  return login;
}

async function copilotToken(auth) {
  const res = await xfetch("https://api.github.com/copilot_internal/v2/token", {
    headers: { authorization: `token ${auth.github}`, accept: "application/json", ...COPILOT_HEADERS }, ua: COPILOT_UA,
  });
  if (res.status === 401) throw new AiError("GitHub sign-in expired. Sign in to Copilot again in Settings → Providers.");
  if (!res.ok) throw new AiError(`This GitHub account has no Copilot access (${res.status}).`);
  const d = await json(res);
  return { ...auth, access: d.token || "", expires: d.expires_at || Date.now() / 1000 + 1500, api: (d.endpoints?.api || COPILOT_BASE).replace(/\/+$/, "") };
}

// ---- requests ----------------------------------------------------------------------------------

const refreshing = {};
async function refresh(id, auth) {
  if (auth.type === "chatgpt") {
    const res = await xfetch(CHATGPT_TOKEN, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ client_id: CHATGPT_CLIENT, grant_type: "refresh_token", refresh_token: auth.refresh || "", scope: "openid profile email" }),
    });
    if (!res.ok) throw new AiError("ChatGPT sign-in expired. Sign in again in Settings → Providers.");
    return chatgptTokens(await json(res), auth);
  }
  return copilotToken(auth);
}

/** Address, headers and User-Agent for a signed-in provider; refreshes a token about to expire. */
export async function signedRequest(p, force = false) {
  let auth = settings.auth[p.id];
  if (!auth) throw new AiError(`Sign in to ${p.name} first in Settings → Providers.`);
  if (force || !auth.access || (auth.expires || 0) < Date.now() / 1000 + 120) {
    refreshing[p.id] ??= refresh(p.id, auth).finally(() => delete refreshing[p.id]);
    auth = await refreshing[p.id];
    setAuth(p.id, auth);
  }
  const base = { "content-type": "application/json", authorization: `Bearer ${auth.access}` };
  if (auth.type === "chatgpt") {
    return { base: CHATGPT_BASE, headers: { ...base, "chatgpt-account-id": auth.account_id, "openai-beta": "responses=experimental", originator: "codex_cli_rs" }, ua: "codex_cli_rs/0.50.0" };
  }
  return { base: auth.api || COPILOT_BASE, headers: { ...base, "openai-intent": "conversation-edits", ...COPILOT_HEADERS }, ua: COPILOT_UA };
}
