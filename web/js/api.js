// Talks to AFH's Python backend. The per-launch token arrives in the URL hash.

/** Opened from the phone app, AFH lives under /r/<computer>/ on agentflowharness.com; locally it's "". */
export const BASE = location.pathname.match(/^\/r\/[\w-]+/)?.[0] || "";

const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
let token = fromHash;
try {
  if (fromHash) sessionStorage.setItem("afh-token", fromHash);
  else token = sessionStorage.getItem("afh-token");
} catch {}
if (fromHash) history.replaceState(null, "", location.pathname);

async function request(method, path, body, retries = 6) {
  const res = await fetch(BASE + path, {
    method,
    headers: { "content-type": "application/json", "x-afh-token": token || "" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { error: text };
  }
  if (res.status === 503 && retries > 0) {
    // The engine is reloading after a settings change; wait for it.
    await new Promise((r) => setTimeout(r, 1500));
    return request(method, path, body, retries - 1);
  }
  if (res.status === 401 && BASE) location.href = "/m/"; // the AFH account sign-in ran out
  else if (res.status === 401 && hooks.onUnauthorized) hooks.onUnauthorized(data);
  if (!res.ok) throw new Error(data?.error || `${res.status} ${res.statusText}`);
  return data;
}

export const hooks = { onUnauthorized: null };

export function setToken(t) {
  token = t;
  try {
    sessionStorage.setItem("afh-token", t);
  } catch {}
}

/** Remote devices sign in with the password set in Settings → Remote control. */
export async function remoteLogin(password) {
  const res = await fetch(BASE + "/api/remote/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ password }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Sign-in failed");
  setToken(data.token);
  return data.token;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b = {}) => request("POST", p, b),
  put: (p, b = {}) => request("PUT", p, b),
  patch: (p, b = {}) => request("PATCH", p, b),
  del: (p, b) => request("DELETE", p, b),
  q: (path, params) => path + "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null)),
  /** POST raw bytes (a pasted image, recorded audio) instead of JSON. */
  raw: async (path, blob, headers = {}) => {
    const res = await fetch(BASE + path, { method: "POST", headers: { "content-type": blob.type || "application/octet-stream", "x-afh-token": token || "", ...headers }, body: blob });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  },
  /** A URL for <img src> and links, which can't send the token header. */
  url: (path, params = {}) => BASE + path + "?" + new URLSearchParams({ ...params, token: token || "" }),
};

export function connectEvents(onEvent, onState) {
  let es;
  const open = () => {
    es = new EventSource(`${BASE}/api/events?token=${encodeURIComponent(token || "")}`);
    es.onopen = () => onState("open");
    es.onerror = () => onState("error");
    es.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data));
      } catch (err) {
        console.error("bad event", err);
      }
    };
  };
  open();
  return () => es?.close();
}

// Native dialogs: the Electron preload exposes window.afh; the pywebview window exposes pywebview.api.
export const native = {
  available: () => !!(window.afh || window.pywebview?.api),
  electron: () => !!window.afh,
  pickFolder: () => (window.afh ? window.afh.pickFolder() : window.pywebview?.api?.pick_folder?.()),
  pickFiles: () => (window.afh ? window.afh.pickFiles() : window.pywebview?.api?.pick_files?.()),
  openExternal: (url) => (window.afh ? window.afh.openExternal(url) : window.open(url, "_blank", "noopener")),
};
