// What the model can do from the website, besides talking — the phone app's tools (app/lib/tools.dart)
// that make sense in a browser: search and read the web, weather and where you are, a calculator,
// the clipboard, links, maps, email drafts, calendar events and reminders (as files your calendar
// opens), memory across chats, and handing work to AFH on your computers. Each tool reports what it
// did as a step under the reply; a step can carry a link or a file for the user to open.
import { AiError, xfetch } from "./net.js";
import { save, settings } from "./store.js";

export class ToolError extends Error {}

const str = (description) => ({ type: "string", description });
const num = (description) => ({ type: "number", description });
const bool = (description) => ({ type: "boolean", description });
const s = (a, k) => String(a?.[k] ?? "").trim();
const cut = (t, n) => (t.length <= n ? t : t.slice(0, n) + "…");

class Tool {
  constructor(name, description, properties, run, label, required = []) {
    Object.assign(this, { name, description, properties, run, label, required });
  }
  get schema() { return { type: "object", properties: this.properties, ...(this.required.length ? { required: this.required } : {}) }; }
}

/** The tools offered to the model right now (the computer ones only when a computer is linked). */
export function webTools() {
  return [...web, ...device, ...apps, ...memory, ...(window.afhMe?.computers?.length ? computers : [])];
}

/** Facts the model needs to use the tools well: today's date, where it runs, what it should remember. */
export function toolContext() {
  const now = new Date();
  const off = -now.getTimezoneOffset();
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const local = new Date(now.getTime() + off * 60000).toISOString().slice(0, 16);
  const sign = off < 0 ? "-" : "+";
  const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, "0"), mm = String(Math.abs(off) % 60).padStart(2, "0");
  return [
    "You are AFH, an assistant on the AFH website (agentflowharness.com), chatting in the user's web browser.",
    `Right now it is ${local} local time (UTC${sign}${hh}:${mm}, ${zone}).`,
    "You have tools: use them whenever they help instead of guessing — search the web for anything recent or factual you are " +
      "unsure of and read the pages you cite, check the weather or where the user is when asked, do exact math, prepare emails, " +
      "calendar events and reminders, and hand coding or computer work to AFH on the user's computer. Say briefly what you did. " +
      "Cite web sources as markdown links.",
    settings.memory.length ? `Things the user asked you to remember:\n${settings.memory.map((m) => `- ${m}`).join("\n")}` : "",
  ].filter(Boolean).join("\n\n");
}

// ---- the web -----------------------------------------------------------------------------------

const parseHtml = (text) => new DOMParser().parseFromString(text, "text/html");

async function webSearch(query, max) {
  if (!query) throw new ToolError("Give a query.");
  let results = [];
  try {
    const res = await xfetch("https://html.duckduckgo.com/html/", {
      method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ q: query, kl: "" }).toString(),
    });
    if (res.ok) {
      const doc = parseHtml(await res.text());
      for (const r of doc.querySelectorAll(".result")) {
        if (r.classList.contains("result--ad")) continue;
        const a = r.querySelector("a.result__a");
        if (!a) continue;
        let href = a.getAttribute("href") || "";
        try { const u = new URL(href, "https://duckduckgo.com"); if (u.searchParams.get("uddg")) href = u.searchParams.get("uddg"); } catch { /* keep */ }
        if (!href.startsWith("http")) continue;
        results.push({ title: a.textContent.trim(), url: href, snippet: r.querySelector(".result__snippet")?.textContent.trim() || "" });
      }
    }
  } catch (e) { if (e instanceof AiError) throw e; }
  if (!results.length) {
    try {
      const res = await xfetch(`https://www.bing.com/search?${new URLSearchParams({ q: query, setlang: "en" })}`, { headers: { "accept-language": "en" } });
      if (res.ok) {
        const doc = parseHtml(await res.text());
        for (const li of doc.querySelectorAll("li.b_algo")) {
          const a = li.querySelector("h2 a");
          const href = a?.getAttribute("href") || "";
          if (href.startsWith("http")) results.push({ title: a.textContent.trim(), url: href, snippet: (li.querySelector(".b_caption p") || li.querySelector("p"))?.textContent.trim() || "" });
        }
      }
    } catch (e) { if (e instanceof AiError) throw e; }
  }
  if (!results.length) throw new ToolError("The search found nothing (or the search engines could not be reached).");
  return results.slice(0, max).map((r, i) => `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.snippet}`).join("\n");
}

async function readPage(url) {
  let u;
  try { u = new URL(url); } catch { throw new ToolError("That is not an http(s) URL."); }
  if (u.protocol === "http:") u.protocol = "https:";
  if (u.protocol !== "https:") throw new ToolError("That is not an http(s) URL.");
  let res;
  try {
    res = await xfetch(u.href, { headers: { accept: "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5", "accept-language": "en" } });
  } catch (e) {
    throw new ToolError(e instanceof AiError ? e.message : `Could not reach ${u.host}.`);
  }
  if (res.status >= 400) throw new ToolError(`${u.host} answered ${res.status}.`);
  const type = res.headers.get("content-type") || "";
  if (type.includes("pdf")) throw new ToolError("That is a PDF, which can't be read here. Search for an HTML version instead.");
  if (/^(image|video|audio)\//.test(type)) throw new ToolError(`That is a ${type} file, not a page.`);
  const body = (await res.text()).slice(0, 3000000);
  if (!type.includes("html") && !body.trimStart().startsWith("<")) return cut(body, 15000);
  const doc = parseHtml(body);
  const title = doc.querySelector("title")?.textContent.trim() || "";
  doc.querySelectorAll("script,style,noscript,svg,nav,footer,header,form,iframe,aside,button,template").forEach((e) => e.remove());
  const root = doc.querySelector("article") || doc.querySelector("main") || doc.body;
  if (!root) return title;
  root.querySelectorAll("p,div,li,h1,h2,h3,h4,h5,h6,br,tr,section,blockquote,pre").forEach((e) => e.append("\n"));
  root.querySelectorAll("a[href]").forEach((e) => { const href = e.getAttribute("href"); if (href?.startsWith("http") && e.textContent.trim().length > 2) e.append(` (${href})`); });
  const text = root.textContent.split("\n").map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
  return cut(`${title ? `# ${title}\n\n` : ""}${text}`, 15000);
}

const WMO = { 0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
  55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow",
  75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
  95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail" };

async function getJson(url) {
  let res;
  try { res = await fetch(url); } catch { throw new ToolError("The weather service could not be reached."); }
  if (!res.ok) throw new ToolError(`The weather service answered ${res.status}.`);
  return res.json();
}

async function weather(place) {
  let lat, lon, name;
  if (!place) {
    const p = await position();
    ({ latitude: lat, longitude: lon } = p.coords);
    name = (await placeName(lat, lon)) || "your location";
  } else {
    const g = await getJson(`https://geocoding-api.open-meteo.com/v1/search?${new URLSearchParams({ name: place, count: "1" })}`);
    const hit = g.results?.[0];
    if (!hit) throw new ToolError(`No place called "${place}" was found.`);
    ({ latitude: lat, longitude: lon } = hit);
    name = [hit.name, hit.admin1, hit.country].filter(Boolean).join(", ");
  }
  const j = await getJson(`https://api.open-meteo.com/v1/forecast?${new URLSearchParams({
    latitude: lat, longitude: lon, timezone: "auto", forecast_days: "5",
    current: "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
    daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
  })}`);
  const c = j.current, d = j.daily;
  const days = d.time.map((t, i) => `${t}: ${WMO[d.weather_code[i]] || `code ${d.weather_code[i]}`}, ${d.temperature_2m_min[i]}–${d.temperature_2m_max[i]} °C, ` +
    `rain chance ${d.precipitation_probability_max[i] ?? "?"}%, sunrise ${String(d.sunrise[i]).split("T").pop()}, sunset ${String(d.sunset[i]).split("T").pop()}`);
  return `Weather for ${name} (${(+lat).toFixed(3)}, ${(+lon).toFixed(3)}), local time ${c.time}:\n` +
    `Now: ${WMO[c.weather_code] || c.weather_code}, ${c.temperature_2m} °C (feels like ${c.apparent_temperature} °C), humidity ${c.relative_humidity_2m}%, ` +
    `wind ${c.wind_speed_10m} km/h, precipitation ${c.precipitation} mm\nNext days:\n${days.join("\n")}`;
}

const web = [
  new Tool("web_search", "Search the web. Returns titles, links and snippets; read the best pages with read_webpage before answering from them.",
    { query: str("What to search for"), max_results: num("How many results (default 8, at most 15)") },
    (a) => webSearch(s(a, "query"), Math.min(15, Math.max(1, Math.round(a.max_results || 8)))),
    (a) => `Searched the web for "${s(a, "query")}"`, ["query"]),
  new Tool("read_webpage", "Read a web page (or a plain-text or JSON URL) and return its readable text.", { url: str("The full http(s) URL") },
    (a) => readPage(s(a, "url")), (a) => { try { return `Read ${new URL(s(a, "url")).host}`; } catch { return `Read ${s(a, "url")}`; } }, ["url"]),
  new Tool("get_weather", "Current weather and the next days' forecast for a place, or for where the user is when no place is given.",
    { place: str("A city or place name; leave empty for the user's location") },
    (a) => weather(s(a, "place")), (a) => (s(a, "place") ? `Checked the weather in ${s(a, "place")}` : "Checked the weather here")),
];

// ---- this browser ---------------------------------------------------------------------------------

function position() {
  if (!navigator.geolocation) return Promise.reject(new ToolError("This browser can't tell where it is."));
  return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve,
    (e) => reject(new ToolError(e.code === 1 ? "The user did not allow location access in the browser." : "The browser couldn't find where it is.")),
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 300000 }));
}

async function placeName(lat, lon) {
  try {
    const res = await xfetch(`https://nominatim.openstreetmap.org/reverse?${new URLSearchParams({ lat, lon, format: "jsonv2", zoom: "16" })}`,
      { headers: { accept: "application/json", "accept-language": navigator.language || "en" }, ua: "AFH-Web/1.11 (https://agentflowharness.com)" });
    return res.ok ? (await res.json()).display_name || null : null;
  } catch { return null; }
}

/** Exact arithmetic without eval: + - * / ^ % ( ), sqrt sin cos tan asin acos atan log ln abs round floor ceil exp, pi e. */
export function calc(expr) {
  const src = String(expr).replace(/\*\*/g, "^").replace(/×/g, "*").replace(/÷/g, "/");
  const tokens = src.match(/\d+(?:\.\d+)?(?:e[+-]?\d+)?|\.\d+|[a-z_]+|[-+*/^%(),!]/gi) || [];
  if (tokens.join("") !== src.replace(/\s+/g, "")) throw new Error("bad characters");
  let i = 0;
  const peek = () => tokens[i], take = () => tokens[i++];
  const F = { sqrt: Math.sqrt, sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan, log: Math.log10,
    ln: Math.log, abs: Math.abs, round: Math.round, floor: Math.floor, ceil: Math.ceil, exp: Math.exp };
  const C = { pi: Math.PI, e: Math.E };
  const expr_ = () => { let v = term(); while (peek() === "+" || peek() === "-") v = take() === "+" ? v + term() : v - term(); return v; };
  const term = () => { let v = unary(); while (["*", "/", "%"].includes(peek())) { const o = take(); const r = unary(); v = o === "*" ? v * r : o === "/" ? v / r : v % r; } return v; };
  const unary = () => (peek() === "-" ? (take(), -unary()) : peek() === "+" ? (take(), unary()) : power());
  const power = () => { const b = post(); return peek() === "^" ? (take(), b ** unary()) : b; };
  const post = () => { let v = atom(); while (peek() === "!") { take(); let f = 1; for (let k = 2; k <= v; k++) f *= k; v = f; } return v; };
  const atom = () => {
    const t = take();
    if (t === undefined) throw new Error("ends early");
    if (t === "(") { const v = expr_(); if (take() !== ")") throw new Error("missing )"); return v; }
    if (/^[\d.]/.test(t)) return parseFloat(t);
    const name = t.toLowerCase();
    if (name in C) return C[name];
    if (name in F) { if (take() !== "(") throw new Error("missing ("); const v = expr_(); if (take() !== ")") throw new Error("missing )"); return F[name](v); }
    throw new Error(`unknown ${t}`);
  };
  const v = expr_();
  if (i < tokens.length) throw new Error("extra input");
  return v;
}

const device = [
  new Tool("get_location", "Where the user is right now (from the browser): coordinates, accuracy and the street address. The browser asks for permission the first time.", {},
    async () => {
      const p = await position();
      const place = await placeName(p.coords.latitude, p.coords.longitude);
      return `Latitude ${p.coords.latitude}, longitude ${p.coords.longitude} (±${Math.round(p.coords.accuracy)} m)${place ? `\nAddress: ${place}` : ""}`;
    }, () => "Checked where you are"),
  new Tool("get_browser_info", "The user's local date and time, time zone, language, platform and screen.", {},
    async () => `Local time: ${new Date().toString()}\nTime zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}\nLanguage: ${navigator.language}\n` +
      `Platform: ${navigator.userAgentData?.platform || navigator.platform}\nScreen: ${screen.width}×${screen.height}`, () => "Checked your browser"),
  new Tool("calculate", 'Evaluate a math expression exactly, e.g. "(1200*0.15)+sqrt(16)" or "2^10". Supports + - * / ^ % ! sqrt sin cos tan log ln abs round, pi, e.',
    { expression: str("The expression") },
    async (a) => {
      const e = s(a, "expression");
      let v;
      try { v = calc(e); } catch { throw new ToolError(`Could not evaluate "${e}".`); }
      if (!Number.isFinite(v)) throw new ToolError(`"${e}" has no finite value.`);
      return `${e} = ${Number.isInteger(v) ? v : +v.toPrecision(15)}`;
    }, (a) => `Calculated ${cut(s(a, "expression"), 40)}`, ["expression"]),
  new Tool("read_clipboard", "Read the text the user last copied (the browser may ask them first).", {},
    async () => {
      try { return (await navigator.clipboard.readText()) || "(the clipboard is empty)"; } catch { throw new ToolError("The browser didn't allow reading the clipboard."); }
    }, () => "Read your clipboard"),
  new Tool("copy_to_clipboard", "Put text on the clipboard so the user can paste it anywhere.", { text: str("The text to copy") },
    async (a, _env, step) => {
      try { await navigator.clipboard.writeText(s(a, "text")); return "Copied."; } catch {
        step.copy = s(a, "text");
        return "The browser blocked copying; the user has a Copy button under the reply.";
      }
    }, () => "Copied text to your clipboard", ["text"]),
];

// ---- links, email and calendar ----------------------------------------------------------------------

const icsDate = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
const icsText = (t) => String(t || "").replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/[,;]/g, (m) => "\\" + m);
function ics({ title, start, end, location, notes, allDay, alarm }) {
  const day = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AFH//Web chat//EN", "BEGIN:VEVENT",
    `UID:${Date.now()}-${Math.random().toString(36).slice(2)}@agentflowharness.com`, `DTSTAMP:${icsDate(new Date())}`,
    allDay ? `DTSTART;VALUE=DATE:${day(start)}` : `DTSTART:${icsDate(start)}`, allDay ? `DTEND;VALUE=DATE:${day(new Date(start.getTime() + 86400000))}` : `DTEND:${icsDate(end)}`,
    `SUMMARY:${icsText(title)}`, location ? `LOCATION:${icsText(location)}` : "", notes ? `DESCRIPTION:${icsText(notes)}` : "",
    alarm ? `BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:${icsText(title)}\r\nTRIGGER:PT0M\r\nEND:VALARM` : "",
    "END:VEVENT", "END:VCALENDAR"].filter(Boolean);
  return URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/calendar" }));
}
const parseLocal = (v) => { const d = v ? new Date(v) : null; return d && !isNaN(d) ? d : null; };
const fileName = (t) => (t.replace(/[^\w\- ]+/g, "").trim().slice(0, 40) || "event") + ".ics";

const apps = [
  new Tool("open_link", "Show a web link for the user to open (as a button under the reply).", { url: str("The URL"), title: str("What the link is") },
    async (a, _env, step) => {
      const url = s(a, "url");
      if (!/^https?:\/\//i.test(url)) throw new ToolError("Only http(s) links can be shown.");
      Object.assign(step, { link: url, linkLabel: s(a, "title") || "Open link" });
      return "Shown to the user as a link.";
    }, (a) => { try { return `Linked ${new URL(s(a, "url")).host}`; } catch { return "Shared a link"; } }, ["url"]),
  new Tool("open_maps", "Show a place, or directions to it, on Google Maps (a button under the reply).",
    { query: str("An address or place name"), directions: bool("true for directions from where the user is") },
    async (a, _env, step) => {
      const q = s(a, "query");
      step.link = a.directions ? `https://www.google.com/maps/dir/?${new URLSearchParams({ api: "1", destination: q })}` : `https://www.google.com/maps/search/?${new URLSearchParams({ api: "1", query: q })}`;
      step.linkLabel = a.directions ? "Get directions" : "Open in Maps";
      return "Shown to the user as a maps link.";
    }, (a) => (a.directions ? `Directions to ${s(a, "query")}` : `${s(a, "query")} on the map`), ["query"]),
  new Tool("draft_email", "Prepare an email for the user's mail app (they open it with a button, check it and send it).",
    { to: str("Email address(es), comma-separated; can be empty"), subject: str("Subject"), body: str("The email text") },
    async (a, _env, step) => {
      step.link = `mailto:${s(a, "to")}?subject=${encodeURIComponent(s(a, "subject"))}&body=${encodeURIComponent(s(a, "body"))}`;
      step.linkLabel = "Open in your mail app";
      return "The draft is ready for the user to open and send.";
    }, (a) => `Drafted an email${s(a, "to") ? ` to ${s(a, "to")}` : ""}`, ["body"]),
  new Tool("add_calendar_event", "Make a calendar event the user adds with one click (a file their calendar app opens).",
    { title: str("Event title"), start: str('Local start "YYYY-MM-DDTHH:MM"'), end: str('Local end "YYYY-MM-DDTHH:MM" (default: one hour later)'),
      location: str("Where"), notes: str("Notes"), all_day: bool("An all-day event") },
    async (a, _env, step) => {
      const start = parseLocal(s(a, "start"));
      if (!start) throw new ToolError('Give "start" as YYYY-MM-DDTHH:MM.');
      const end = parseLocal(s(a, "end")) || new Date(start.getTime() + 3600000);
      Object.assign(step, { link: ics({ title: s(a, "title"), start, end, location: s(a, "location"), notes: s(a, "notes"), allDay: a.all_day === true }),
        linkLabel: "Add to calendar", download: fileName(s(a, "title")) });
      return `"${s(a, "title")}" on ${s(a, "start")} is ready; the user adds it with the button.`;
    }, (a) => `Made "${cut(s(a, "title"), 40)}" for your calendar`, ["title", "start"]),
  new Tool("set_reminder", "Set a reminder: a calendar alert the user adds with one click, plus a notification in this tab if it is still open then.",
    { message: str("What to remind the user about"), at: str('When, as local date-time "YYYY-MM-DDTHH:MM" (use this or in_minutes)'), in_minutes: num("Or: in how many minutes from now") },
    async (a, _env, step) => {
      const when = a.in_minutes != null ? new Date(Date.now() + a.in_minutes * 60000) : parseLocal(s(a, "at"));
      if (!when) throw new ToolError('Give "at" as YYYY-MM-DDTHH:MM or "in_minutes".');
      if (when < new Date()) throw new ToolError("That time has already passed.");
      const msg = s(a, "message");
      Object.assign(step, { link: ics({ title: msg, start: when, end: new Date(when.getTime() + 900000), alarm: true }), linkLabel: "Add reminder to calendar", download: fileName(msg) });
      if (when - Date.now() < 2 ** 31 - 1) setTimeout(() => {
        if ("Notification" in window && Notification.permission === "granted") new Notification("AFH reminder", { body: msg, icon: "/assets/mark.svg" });
      }, when - Date.now());
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
      return `Reminder for ${when.toLocaleString()} is ready; the user adds it to their calendar with the button (and gets a browser notification if this tab stays open).`;
    }, (a) => `Reminder: ${cut(s(a, "message"), 50)}`, ["message"]),
];

// ---- memory -------------------------------------------------------------------------------------

const memory = [
  new Tool("remember", "Remember a fact about the user or their preferences for all future chats (name, city, how they like answers…). Only when they ask or it is clearly useful.",
    { fact: str("The fact, as one short sentence") },
    async (a) => {
      const f = s(a, "fact");
      if (!f) throw new ToolError("Give the fact.");
      const m = settings.memory.includes(f) ? settings.memory : [...settings.memory, f];
      save({ memory: m.slice(-50) });
      return "Remembered.";
    }, (a) => `Remembered: ${cut(s(a, "fact"), 50)}`, ["fact"]),
  new Tool("forget", "Forget something you were asked to remember.", { fact: str("The remembered fact (or words from it)") },
    async (a) => {
      const q = s(a, "fact").toLowerCase();
      const m = settings.memory.filter((x) => !(x.toLowerCase().includes(q) || q.includes(x.toLowerCase())));
      const gone = m.length !== settings.memory.length;
      save({ memory: m });
      return gone ? "Forgotten." : "Nothing like that was remembered.";
    }, (a) => `Forgot: ${cut(s(a, "fact"), 50)}`, ["fact"]),
];

// ---- AFH on the user's computers ------------------------------------------------------------------

async function pc(cid, method, path, body) {
  const res = await fetch(`/r/${encodeURIComponent(cid)}${path}`, {
    method, credentials: "same-origin", headers: body ? { "content-type": "application/json", accept: "application/json" } : { accept: "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new ToolError(data?.error || (res.status === 503 ? "That computer is offline." : `The computer answered ${res.status}.`));
  return data;
}
async function refreshMe() {
  try { const r = await fetch("/relay/api/me", { credentials: "same-origin" }); if (r.ok) window.afhMe = await r.json(); } catch { /* keep the old list */ }
  return window.afhMe?.computers || [];
}
function pick(list, name) {
  const online = list.filter((c) => c.online);
  if (!online.length) throw new ToolError("None of the user's computers is online. They need to open AFH on one.");
  if (!name) return online[0];
  const n = name.toLowerCase();
  return online.find((c) => c.name.toLowerCase() === n) || online.find((c) => c.name.toLowerCase().includes(n)) || (() => { throw new ToolError(`No online computer is called "${name}".`); })();
}
const baseName = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || String(p || "");
function assistantText(msgs) {
  for (const m of [...(msgs || [])].reverse()) {
    if (m?.type !== "assistant") continue;
    const t = (m.content || []).filter((c) => c?.type === "text").map((c) => c.text || "").join("\n").trim();
    if (t) return t;
  }
  return "";
}

const computers = [
  new Tool("list_computers", "The user's computers with AFH (online or not) and, for online ones, their projects (folders AFH works in).", {},
    async () => {
      const list = await refreshMe();
      if (!list.length) return "No computers are linked to the user's AFH account.";
      const out = [];
      for (const c of list) {
        let line = `${c.name}: ${c.online ? "online" : "offline"}`;
        if (c.online) {
          try { const st = await pc(c.id, "GET", "/api/settings"); if (st?.projects?.length) line += `\n  projects: ${st.projects.slice(0, 15).join(", ")}`; } catch { /* skip */ }
        }
        out.push(line);
      }
      return out.join("\n");
    }, () => "Checked your computers"),
  new Tool("run_on_computer",
    "Hand a task to AFH, the coding agent on the user's computer: it can read and change files, run commands, build and test code, browse, and anything else the computer can do. Waits up to a few minutes for its answer. The user confirms first.",
    { task: str("What AFH on the computer should do, fully explained"), project: str("The project folder to work in (from list_computers); empty for the most recent one"),
      computer: str("Which computer (empty for the first online one)") },
    async (a, env, step) => {
      const c = pick(await refreshMe(), s(a, "computer"));
      const st = await pc(c.id, "GET", "/api/settings");
      const projects = (st?.projects || []).map(String);
      const want = s(a, "project");
      const dir = want ? projects.find((p) => p === want || baseName(p).toLowerCase() === want.toLowerCase()) || want : projects[0];
      const task = s(a, "task");
      if (!(await env.confirm(`Run this on ${c.name}?`, `${dir ? `In ${baseName(dir)}:\n\n` : ""}${task}`, "Run it"))) throw new ToolError("The user said no.");
      const ses = await pc(c.id, "POST", "/api/sessions", dir ? { directory: dir } : {});
      await pc(c.id, "POST", `/api/sessions/${ses.id}/prompt`, { text: task });
      step.link = `/computers#/c/${encodeURIComponent(c.id)}/t/${encodeURIComponent(ses.id)}`;
      step.linkLabel = "Follow it live";
      const until = Date.now() + 4 * 60000;
      while (Date.now() < until) {
        await new Promise((r) => setTimeout(r, 5000));
        const now = await pc(c.id, "GET", `/api/sessions/${ses.id}`);
        if (now && now.running !== true) {
          const text = assistantText(await pc(c.id, "GET", `/api/sessions/${ses.id}/messages`));
          return `AFH on ${c.name} finished (thread ${ses.id}).\n\n${text ? cut(text, 12000) : "(no text reply)"}`;
        }
        const perms = await pc(c.id, "GET", `/api/sessions/${ses.id}/permissions`).catch(() => []);
        if (Array.isArray(perms) && perms.length) return `AFH on ${c.name} is waiting for the user to approve a step (thread ${ses.id}). They can approve it with the "Follow it live" button.`;
      }
      return `AFH on ${c.name} is still working on it (thread ${ses.id}). The user can follow it live; check back with read_computer_thread.`;
    }, (a) => `Asked AFH on ${s(a, "computer") || "your computer"}: ${cut(s(a, "task"), 50)}`, ["task"]),
  new Tool("read_computer_thread", "Check on a thread started with run_on_computer: whether it is still running and its latest answer.",
    { thread: str("The thread id"), computer: str("Which computer (empty for the first online one)") },
    async (a) => {
      const c = pick(await refreshMe(), s(a, "computer"));
      const sid = s(a, "thread");
      const st = await pc(c.id, "GET", `/api/sessions/${sid}`);
      const text = assistantText(await pc(c.id, "GET", `/api/sessions/${sid}/messages`));
      return `${st?.running ? "Still running." : "Finished."}\n\n${text ? cut(text, 12000) : "(no text yet)"}`;
    }, () => "Checked the thread on your computer", ["thread"]),
];
