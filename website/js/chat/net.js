// Reaching providers and the web from a browser. Most model APIs and every other site refuse
// requests from a web page (CORS), so those go through AFH's relay (/relay/api/fwd), which passes
// them on unchanged and streams the answer back — it stores and logs nothing. Servers on this
// computer (Ollama, LM Studio…) are called directly.

export class AiError extends Error {}

const isLocal = (host) =>
  host === "localhost" || host.endsWith(".localhost") || host === "[::1]" || /^127\./.test(host);

/**
 * fetch() for any URL. `ua` sets the User-Agent the far side sees (browsers can't).
 * Errors from the relay itself (signed out, refused address) become AiErrors; the provider's own
 * answers come back as they are.
 */
export async function xfetch(url, { method = "GET", headers = {}, body, signal, ua } = {}) {
  const u = new URL(url);
  if (isLocal(u.hostname)) {
    try {
      return await fetch(url, { method, headers, body, signal });
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw new AiError(`Couldn't reach ${u.host}. Is the server running, and does it allow requests from agentflowharness.com (for Ollama: OLLAMA_ORIGINS)?`);
    }
  }
  if (u.protocol !== "https:") throw new AiError("From the website, servers on other machines must use https. A server on this computer can use http://localhost.");
  const h = new Headers(headers);
  h.set("x-afh-target", url);
  if (ua) h.set("x-afh-ua", ua);
  let res;
  try {
    res = await fetch("/relay/api/fwd", { method, headers: h, body, signal, credentials: "same-origin" });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new AiError("You seem to be offline.");
  }
  if (!res.headers.get("x-afh-fwd")) {
    let msg = `Something went wrong (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch { /* not json */ }
    if (res.status === 401) {
      location.href = "/account?next=" + encodeURIComponent(location.pathname + location.hash);
      throw new AiError("Sign in again.");
    }
    throw new AiError(msg);
  }
  return res;
}

/** Lines of a server-sent event stream, as they arrive. */
export async function* sseLines(res) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).replace(/\r$/, "");
      buf = buf.slice(i + 1);
      yield line;
    }
  }
  if (buf.trim()) yield buf;
}
