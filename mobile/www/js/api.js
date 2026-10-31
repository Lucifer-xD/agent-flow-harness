// Talks to the AFH account server and, through it, to AFH on the user's computers. The app signs
// in with a bearer token kept on the phone; requests to /r/<computer>/ are passed by the relay to
// that computer's own AFH, which answers them as if the user were sitting at it.

const KEY = "afh.app";
const saved = (() => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } })();

export const SERVER = (saved.server || "https://agentflowharness.com").replace(/\/$/, "");
export const auth = {
  get token() { return saved.token || ""; },
  get email() { return saved.email || ""; },
  set(token, email) { Object.assign(saved, { token, email }); persist(); },
  clear() { delete saved.token; delete saved.email; persist(); },
};

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

let onSignedOut = () => {};
export const whenSignedOut = (fn) => { onSignedOut = fn; };

async function request(method, path, body, { signal, quiet } = {}) {
  let res;
  try {
    res = await fetch(SERVER + path, {
      method, signal,
      headers: { ...(auth.token ? { authorization: `Bearer ${auth.token}` } : {}), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("No connection. Check your internet and try again.", 0);
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const detail = data && (data.error || (typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg));
    if (res.status === 401 && path.startsWith("/relay/api/me") && !quiet) { auth.clear(); onSignedOut(); }
    throw new ApiError(detail || `Something went wrong (${res.status})`, res.status);
  }
  return data;
}

export const account = {
  async signIn(email, password, create) {
    const got = await request("POST", `/relay/api/${create ? "signup" : "signin"}`, { email, password, kind: "app" });
    auth.set(got.token, got.user.email);
    return got;
  },
  me: () => request("GET", "/relay/api/me"),
  async signOut() {
    await request("POST", "/relay/api/signout", {}).catch(() => {});
    auth.clear();
  },
};

/** One computer's AFH, reached through the relay. */
export function computer(id) {
  const base = `/r/${encodeURIComponent(id)}`;
  return {
    get: (path, opts) => request("GET", base + path, undefined, opts),
    post: (path, body = {}, opts) => request("POST", base + path, body, opts),
    /** Live events from that AFH (every thread); calls onEvent per event and reconnects until stop(). */
    events(onEvent, onState = () => {}) {
      let ctrl = null;
      let stopped = false;
      let wait = 1000;
      (async () => {
        while (!stopped) {
          ctrl = new AbortController();
          try {
            const res = await fetch(`${SERVER}${base}/api/events`, { headers: { authorization: `Bearer ${auth.token}`, accept: "text/event-stream" }, signal: ctrl.signal });
            if (!res.ok || !res.body) throw new ApiError(`events ${res.status}`, res.status);
            onState("live");
            wait = 1000;
            const reader = res.body.getReader();
            const dec = new TextDecoder();
            let buf = "";
            for (;;) {
              const { value, done } = await reader.read();
              if (done) break;
              buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
              let cut;
              while ((cut = buf.indexOf("\n\n")) >= 0) {
                const chunk = buf.slice(0, cut);
                buf = buf.slice(cut + 2);
                const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
                if (!data) continue;
                try { onEvent(JSON.parse(data)); } catch (err) { console.warn("event", err); }
              }
            }
          } catch (err) {
            if (stopped) return;
          }
          if (stopped) return;
          onState("reconnecting");
          await new Promise((r) => setTimeout(r, wait));
          wait = Math.min(wait * 2, 15000);
        }
      })();
      return { stop() { stopped = true; ctrl?.abort(); } };
    },
  };
}

/** Opens a page in the system browser (Custom Tabs / Safari view) when running as the app. */
export function openWeb(url) {
  const Browser = window.Capacitor?.isNativePlatform?.() ? window.Capacitor.registerPlugin("Browser") : null;
  if (Browser) return Browser.open({ url, toolbarColor: "#0b0908" });
  window.open(url, "_blank", "noopener");
}
