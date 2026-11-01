// What the web chat keeps, all in this browser: settings, keys and sign-ins in localStorage, chats in
// IndexedDB (photos make them too big for localStorage). Nothing here goes to AFH's server.

const KEY = "afh.web.v1";
const listeners = new Set();

const defaults = () => ({
  keys: {},      // provider id → API key
  auth: {},      // provider id → sign-in tokens (ChatGPT, Copilot)
  base: {},      // provider id → the user's own address
  params: {},    // provider id → { VAR: value }
  models: {},    // provider id → fetched model ids
  model: null,   // { provider, id }
  theme: "system",
  system: "",
  memory: [],
  tools: true,
  sideOpen: true,
});

function load() {
  try {
    return { ...defaults(), ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return defaults();
  }
}

export const settings = load();

export function save(patch) {
  if (patch) Object.assign(settings, patch);
  try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch { /* private mode: keep it for this visit */ }
  for (const f of listeners) f();
}
export const onSettings = (f) => { listeners.add(f); return () => listeners.delete(f); };

// ---- chats -------------------------------------------------------------------------------------

let dbp = null;
function db() {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open("afh-chat", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("chats", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}
async function tx(mode, f) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction("chats", mode);
    const out = f(t.objectStore("chats"));
    t.oncomplete = () => resolve(out?.result ?? out);
    t.onerror = () => reject(t.error);
  });
}

const memoryChats = new Map(); // when IndexedDB is unavailable (some private windows)

export async function allChats() {
  try {
    const list = await tx("readonly", (s) => s.getAll());
    return list.sort((a, b) => b.updated - a.updated);
  } catch {
    return [...memoryChats.values()].sort((a, b) => b.updated - a.updated);
  }
}
export async function putChat(chat) {
  memoryChats.set(chat.id, chat);
  try { await tx("readwrite", (s) => s.put(structuredClone(chat))); } catch { /* kept in memory */ }
}
export async function deleteChat(id) {
  memoryChats.delete(id);
  try { await tx("readwrite", (s) => s.delete(id)); } catch { /* gone from memory */ }
}
export async function deleteAllChats() {
  memoryChats.clear();
  try { await tx("readwrite", (s) => s.clear()); } catch { /* gone from memory */ }
}

export const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

/** A short title from the first message, so the list reads well without an extra request. */
export function titleFrom(text) {
  let t = String(text || "").trim().replace(/\s+/g, " ");
  t = t.replace(/^(hey|hi|hello|please|can you|could you)[,!\s]+/i, "");
  if (!t) return "New chat";
  t = t[0].toUpperCase() + t.slice(1);
  return t.length > 48 ? t.slice(0, 46).trimEnd() + "…" : t;
}
