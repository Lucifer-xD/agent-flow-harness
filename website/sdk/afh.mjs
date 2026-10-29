// JavaScript client for the Agent Flow Harness local API (Node 18+, no dependencies).
//
//   import { AFH } from "./afh.mjs";
//   const afh = await AFH.connect();            // finds the running app; key from AFH_API_KEY
//   const out = await afh.run("Add a /health endpoint and a test", { directory: "C:/code/api" });
//   console.log(out.reply);
//   for await (const ev of afh.events()) console.log(ev.type);
//
// Create an API key in AFH → Settings → Developer. AFH must be running.

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export class AFHError extends Error {
  constructor(status, message) {
    super(`${status}: ${message}`);
    this.status = status;
  }
}

export class AFH {
  /** Connect to the running app. Options: { apiKey, url }. */
  static async connect({ apiKey = process.env.AFH_API_KEY, url = process.env.AFH_URL } = {}) {
    if (!url) {
      const home = process.env.AFH_HOME || join(homedir(), ".afh");
      try {
        url = JSON.parse(await readFile(join(home, "api.json"), "utf8")).url;
      } catch {
        throw new AFHError(0, "AFH doesn't seem to be running (no ~/.afh/api.json). Start the app, or pass { url }");
      }
    }
    if (!apiKey) throw new AFHError(0, "No API key: pass { apiKey } or set AFH_API_KEY (create one in Settings → Developer)");
    return new AFH(url, apiKey);
  }

  constructor(url, apiKey) {
    this.url = url.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  async request(method, path, body, params) {
    const qs = params ? "?" + new URLSearchParams(params) : "";
    const res = await fetch(this.url + path + qs, {
      method,
      headers: { authorization: `Bearer ${this.apiKey}`, "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new AFHError(res.status, data?.error || res.statusText);
    return data;
  }

  /** Start a thread in `directory` (or continue `sessionID`), send `prompt`, wait for the answer. */
  run(prompt, { directory, sessionID, model, agent, mode = "full", wait = true, timeout = 1800 } = {}) {
    return this.request("POST", "/api/v1/run", { prompt, directory, sessionID, model, agent, mode, wait, timeout });
  }

  sessions(directory, archived = false) { return this.request("GET", "/api/sessions", undefined, { directory, archived: String(archived) }); }
  createSession(directory, { title, model, agent, mode, worktree } = {}) {
    const [providerID, ...rest] = (model || "").split("/");
    return this.request("POST", "/api/sessions", { directory, title, agent, mode, worktree, model: model ? { providerID, id: rest.join("/") } : undefined });
  }
  session(id) { return this.request("GET", `/api/sessions/${id}`); }
  messages(id) { return this.request("GET", `/api/sessions/${id}/messages`); }
  prompt(id, text, files = []) { return this.request("POST", `/api/sessions/${id}/prompt`, { text, files }); }
  reply(id) { return this.request("GET", `/api/v1/sessions/${id}/reply`); }
  interrupt(id) { return this.request("POST", `/api/sessions/${id}/interrupt`); }
  deleteSession(id) { return this.request("DELETE", `/api/sessions/${id}`); }
  todos(id) { return this.request("GET", `/api/sessions/${id}/todos`); }
  setTodos(id, todos) { return this.request("PUT", `/api/sessions/${id}/todos`, { todos }); }
  goal(id) { return this.request("GET", `/api/sessions/${id}/goal`); }
  setGoal(id, text, { criteria = "", autopilot = true, start = false } = {}) { return this.request("PUT", `/api/sessions/${id}/goal`, { text, criteria, autopilot, start }); }
  diff(id) { return this.request("GET", `/api/sessions/${id}/diff`); }
  usage(id) { return this.request("GET", `/api/sessions/${id}/usage`); }
  models() { return this.request("GET", "/api/models"); }
  schedules() { return this.request("GET", "/api/schedules"); }
  runSchedule(id) { return this.request("POST", `/api/schedules/${id}/run`); }
  saveSchedule(job) { return job.id ? this.request("PUT", `/api/schedules/${job.id}`, job) : this.request("POST", "/api/schedules", job); }
  deleteSchedule(id) { return this.request("DELETE", `/api/schedules/${id}`); }
  approvals(id) { return this.request("GET", `/api/sessions/${id}/permissions`); }
  /** decision: "once", "always" or "reject". */
  approve(id, requestID, decision = "once", message) { return this.request("POST", `/api/sessions/${id}/permissions/${requestID}`, { decision, message }); }

  /** Live events (Server-Sent Events) as an async iterator, optionally for one thread. */
  async *events(sessionID) {
    const res = await fetch(this.url + "/api/events", { headers: { authorization: `Bearer ${this.apiKey}`, accept: "text/event-stream" } });
    if (!res.ok) throw new AFHError(res.status, res.statusText);
    const decoder = new TextDecoder();
    let buf = "";
    for await (const chunk of res.body) {
      buf += decoder.decode(chunk, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const line = block.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (sessionID && ev.data?.sessionID !== sessionID) continue;
        yield ev;
      }
    }
  }
}
