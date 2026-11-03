// AFH Chat on the web: chat with any model, the way the phone app does — pick a provider and model,
// talk, and the model can search the web and use the other tools. Chats stay in this browser; your
// computers live on /computers. Routes: #/ (a new chat) and #/c/<chat>.
import { AiError, fetchModels, Run } from "./ai.js";
import { loadProviders, providerById, providers } from "./providers.js";
import { chatgptFinish, chatgptStart, copilotSignIn, openrouterFinish, openrouterStart, signOut } from "./signin.js";
import { allChats, deleteAllChats, deleteChat, newId, onSettings, putChat, save, settings, titleFrom } from "./store.js";

// ---- helpers ------------------------------------------------------------------------------------

const h = (tag, attrs, ...kids) => {
  const [name, ...classes] = tag.split(".");
  const node = document.createElement(name);
  if (classes.length) node.className = classes.join(" ");
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "html") node.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) node.append(kid);
  return node;
};

const P = {
  panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
  pen: '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  laptop: '<path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16"/>',
  settings: '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  down: '<path d="m6 9 6 6 6-6"/>', right: '<path d="m9 18 6-6-6-6"/>', left: '<path d="m15 18-6-6 6-6"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
  up: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>', arrowDown: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  cloud: '<path d="M12 2v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="M20 12h2"/><path d="m19.07 4.93-1.41 1.41"/><path d="M15.947 12.65a4 4 0 0 0-5.925-4.128"/><path d="M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  key: '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  pin: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
  calc: '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M8 6h8"/><path d="M16 14v4"/><path d="M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01"/>',
  calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
  clipboard: '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8M16 13H8M16 17H8"/>',
  alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  sparkle: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
};
const icon = (name, size = 18, sw = 1.8) => h("span.ic", { html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || P.wrench}</svg>` });
const TOOL_ICON = { web_search: "search", read_webpage: "globe", get_weather: "cloud", get_location: "pin", get_browser_info: "eye", calculate: "calc",
  read_clipboard: "clipboard", copy_to_clipboard: "clipboard", open_link: "link", open_maps: "pin", draft_email: "mail", add_calendar_event: "calendar",
  set_reminder: "bell", remember: "bookmark", forget: "bookmark", list_computers: "laptop", run_on_computer: "laptop", read_computer_thread: "laptop" };

/** replaceChildren that skips empty slots and flattens lists, like h() does. */
const put = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const isWide = () => matchMedia("(min-width: 861px)").matches;

function toast(text, bad) {
  document.querySelector(".toast")?.remove();
  const t = h("div.toast" + (bad ? ".bad" : ""), { role: "status" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 5200 : 2600);
}
async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch { toast("Couldn't copy", true); return; }
  if (btn) { const old = btn.innerHTML; put(btn, icon("check", 16)); setTimeout(() => (btn.innerHTML = old), 1400); } else toast("Copied");
}

function md(text) {
  try {
    const html = marked.parse(String(text || ""), { breaks: true, gfm: true });
    return DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
  } catch { return esc(text).replace(/\n/g, "<br>"); }
}
function mdNode(text, done) {
  const div = h("div.md", { html: md(text) });
  div.querySelectorAll("a[href^='http']").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
  div.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    const lang = (code.className.match(/language-([\w+#-]+)/) || [])[1] || "";
    const btn = h("button", { type: "button", onclick: () => copy(code.textContent, btn) }, icon("copy", 14), "Copy");
    const box = h("div.code", {}, h("div.code-head", {}, h("span", {}, lang || "code"), btn));
    pre.replaceWith(box);
    box.append(pre);
    if (done && window.hljs) { try { hljs.highlightElement(code); } catch { /* plain is fine */ } }
  });
  return div;
}

// ---- state --------------------------------------------------------------------------------------

const S = {
  me: null,
  chats: [],
  chat: null,       // the open chat, or null for a new one
  run: null,        // the reply being streamed
  filter: "",
  attached: [],     // { kind: "image", url, name } | { kind: "file", name, text }
  rec: null,        // speech recognition while dictating
};
const app = document.getElementById("app");
let els = {};

const readyProviders = () => providers.filter((p) => p.ready);
function currentModel() {
  const m = settings.model;
  const p = m && providerById(m.provider);
  if (p?.ready && m.id) return { p, id: m.id };
  const first = readyProviders().find((x) => x.models.length);
  return first ? { p: first, id: first.models[0] } : null;
}

// ---- shell --------------------------------------------------------------------------------------

function shell() {
  els.side = h("aside.side", { "aria-label": "Chats" });
  els.top = h("header.top");
  els.scroll = h("div.scroll");
  els.dock = h("div.dock");
  els.main = h("main.main", {}, els.top, els.scroll, els.dock);
  els.scrim = h("div.scrim", { onclick: () => toggleSide(false) });
  put(app, els.side, els.scrim, els.main);
  app.classList.toggle("side-closed", !settings.sideOpen);
  buildComposer();
  els.scroll.addEventListener("scroll", () => {
    const near = els.scroll.scrollHeight - els.scroll.scrollTop - els.scroll.clientHeight < 80;
    S.stick = near;
    if (els.jump) els.jump.hidden = near || !S.chat;
  }, { passive: true });
}

function toggleSide(open) {
  if (isWide()) {
    save({ sideOpen: open ?? !settings.sideOpen });
    app.classList.toggle("side-closed", !settings.sideOpen);
    renderTop();
  } else {
    app.classList.toggle("side-open", open ?? !app.classList.contains("side-open"));
  }
}

function group(t) {
  const d = new Date(t), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff < 1) return "Today";
  if (diff < 2) return "Yesterday";
  if (diff < 7) return "Previous 7 days";
  if (diff < 30) return "Previous 30 days";
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function chatGroups() {
  const q = S.filter.trim().toLowerCase();
  const list = S.chats.filter((c) => !q || c.title.toLowerCase().includes(q) || c.msgs.some((m) => (m.shown ?? m.text ?? "").toLowerCase().includes(q)));
  const groups = [];
  for (const c of list) {
    const g = group(c.updated);
    if (groups.at(-1)?.[0] !== g) groups.push([g, []]);
    groups.at(-1)[1].push(c);
  }
  return groups;
}

function renderSide() {
  const online = (S.me?.computers || []).filter((c) => c.online).length;
  const search = h("input", { type: "search", placeholder: "Search chats", value: S.filter, "aria-label": "Search chats" });
  search.addEventListener("input", () => { S.filter = search.value; renderChatList(); });
  els.chatList = h("nav.chats", { "aria-label": "Your chats" });
  const email = S.me?.user?.email || "";
  put(els.side, h("div.side-head", {},
      h("a.brand", { href: "/", title: "agentflowharness.com" }, h("img", { src: "/assets/mark.svg", alt: "" }), "AFH"),
      h("button.icon-btn", { type: "button", title: "Close sidebar", "aria-label": "Close sidebar", onclick: () => toggleSide(false) }, icon("panel", 19))),
    h("div.side-actions", {},
      h("a.nav-item", { href: "#/", onclick: () => !isWide() && toggleSide(false) }, icon("pen", 18), "New chat"),
      h("a.nav-item", { href: "/computers" }, icon("laptop", 18), "Computers", online ? h("span.dot-on", { title: `${online} online` }) : null),
      h("button.nav-item", { type: "button", onclick: () => openSettings("providers") }, icon("key", 18), "Providers")),
    h("label.side-search", {}, icon("search", 15), search),
    els.chatList,
    h("div.side-foot", {},
      h("button.me", { type: "button", onclick: (e) => meMenu(e.currentTarget) },
        h("span.avatar", {}, (email[0] || "A").toUpperCase()),
        h("span.me-text", {}, h("b", {}, email || "Your account"), h("span", {}, "Settings and account")))));
  renderChatList();
}

function renderChatList() {
  const groups = chatGroups();
  const on = S.chat?.id;
  put(els.chatList, ...(groups.length ? groups.map(([g, chats]) => [
    h("h6", {}, g),
    chats.map((c) => h("div.chat-row" + (c.id === on ? ".on" : ""), {},
      h("a", { href: `#/c/${c.id}`, title: c.title, onclick: () => !isWide() && toggleSide(false) }, c.title),
      S.run && S.chat?.id === c.id ? h("span.running", { title: "Answering" }) : null,
      h("button.more", { type: "button", "aria-label": "Chat options", onclick: (e) => chatMenu(e.currentTarget, c) }, icon("more", 17)))),
  ]) : [h("p.empty", {}, S.filter ? "No chat matches." : "Your chats show up here. They stay in this browser.")]));
}

function renderTop() {
  const m = currentModel();
  const closed = !isWide() || !settings.sideOpen;
  els.modelBtn = h("button.model-btn", { type: "button", "aria-haspopup": "listbox", "aria-expanded": "false", onclick: () => openPicker() },
    m ? [h("span.pdot", { style: { background: m.p.color } }), h("span.name", {}, m.id), h("span.prov", {}, m.p.name)] : h("span.name", {}, "Choose a model"),
    icon("down", 16));
  put(els.top, closed ? h("button.icon-btn", { type: "button", title: "Open sidebar", "aria-label": "Open sidebar", onclick: () => toggleSide(true) }, icon("panel", 19)) : null,
    closed && isWide() ? h("a.icon-btn", { href: "#/", title: "New chat", "aria-label": "New chat" }, icon("pen", 18)) : null,
    els.modelBtn,
    h("div.grow"),
    !isWide() ? h("a.icon-btn", { href: "#/", title: "New chat", "aria-label": "New chat" }, icon("pen", 18)) : null);
}

// ---- conversation -------------------------------------------------------------------------------

function greeting() {
  const hr = new Date().getHours();
  return hr < 5 ? "Up late?" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
}
const IDEAS = [
  ["globe", "What are today's top tech headlines?"],
  ["cloud", "What's the weather like here this week?"],
  ["mail", "Write a short email asking to move tomorrow's meeting"],
  ["calc", "What's 18% tip on 2,450, split between 3 people?"],
];

function renderBody() {
  if (!S.chat || !S.chat.msgs.length) {
    const none = !readyProviders().length;
    put(els.scroll, h("div.welcome", {}, h("div.col", {},
      h("img.logo", { src: "/assets/mark.svg", alt: "" }),
      h("p.hello", {}, greeting()),
      h("h1", {}, "What are we building today?"),
      h("p.sub", {}, "Chat with any model — it can search the web, check the weather, do the math, and hand work to AFH on your computer."),
      els.composerBox,
      h("div.ideas", {},
        none ? h("button.idea.accent", { type: "button", onclick: () => openSettings("providers") }, icon("key", 18), "Add a model provider to start chatting — sign in with ChatGPT, Copilot or OpenRouter, or paste a key") : null,
        IDEAS.map(([ic, text]) => h("button.idea", { type: "button", onclick: () => (none ? openSettings("providers") : send(text)) }, icon(ic, 18), text))))));
    put(els.dock, h("div.col", {}, h("p.fine", {}, "Chats and keys stay in this browser. Models can make mistakes — check important answers.")));
    document.title = "AFH Chat";
    setTimeout(() => els.input.focus(), 0);
    return;
  }
  els.thread = h("div.thread");
  S.chat.msgs.forEach((m, i) => els.thread.append(msgNode(m, i)));
  put(els.scroll, h("div.col", {}, els.thread));
  els.jump = h("button.jump", { type: "button", hidden: true, "aria-label": "Scroll to the end", onclick: () => toEnd(true) }, icon("arrowDown", 18));
  put(els.dock, h("div.col", {}, els.jump, els.composerBox, h("p.fine", {}, "Models can make mistakes — check important answers.")));
  document.title = `${S.chat.title} · AFH`;
  toEnd(false);
}

function toEnd(smooth) {
  S.stick = true;
  if (els.jump) els.jump.hidden = true;
  requestAnimationFrame(() => els.scroll.scrollTo({ top: els.scroll.scrollHeight, behavior: smooth ? "smooth" : "auto" }));
}

function msgNode(m, i) {
  const last = i === S.chat.msgs.length - 1;
  if (m.role === "user") {
    const node = h("div.msg.user", { "data-i": i },
      m.images?.length ? h("div.user-imgs", {}, m.images.map((u) => h("img", { src: u, alt: "Attached photo", onclick: () => view(u) }))) : null,
      (m.files || []).map((f) => h("div.user-file", {}, icon("file", 16), f)),
      (m.shown ?? m.text) ? h("div.bubble", {}, m.shown ?? m.text) : null,
      h("div.msg-tools", {},
        h("button.icon-btn", { type: "button", title: "Copy", "aria-label": "Copy", onclick: (e) => copy(m.shown ?? m.text, e.currentTarget) }, icon("copy", 16)),
        !S.run ? h("button.icon-btn", { type: "button", title: "Edit", "aria-label": "Edit", onclick: () => editMsg(i, node) }, icon("pencil", 16)) : null));
    return node;
  }
  const busy = m.streaming;
  const body = [];
  if (m.reasoning) {
    const live = busy && !m.text;
    const det = h("details.think" + (live ? ".live" : ""), { open: live || undefined },
      h("summary", {}, icon("right", 14), h("span" + (live ? ".shimmer" : ""), {}, live ? "Thinking…" : "Thought")),
      h("div.think-body", {}, m.reasoning));
    body.push(det);
  }
  if (m.steps?.length) body.push(h("div.steps", {}, m.steps.map(stepNode)));
  if (m.text) {
    const node = mdNode(m.text, !busy);
    if (busy) node.classList.add("cursor");
    body.push(node);
  } else if (busy && !m.reasoning && !m.steps?.some((s) => s.state === "running")) body.push(h("div.typing", {}, h("i"), h("i"), h("i")));
  if (m.error) {
    body.push(h("div.err", {}, icon("alert", 18), h("div", {}, m.error, " ",
      /Settings|key|sign in|Sign in/i.test(m.error) ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); openSettings("providers"); } }, "Open providers") : null)));
  }
  const p = providerById(m.provider);
  if (!busy) body.push(h("div.msg-tools", {},
    m.text ? h("button.icon-btn", { type: "button", title: "Copy", "aria-label": "Copy", onclick: (e) => copy(m.text, e.currentTarget) }, icon("copy", 16)) : null,
    !S.run ? h("button.icon-btn", { type: "button", title: "Try again", "aria-label": "Try again", onclick: () => retry(i) }, icon("refresh", 16)) : null,
    m.model ? h("span.tag", { title: p?.name || "" }, m.model) : null));
  return h("div.msg.ai" + (last ? ".last" : ""), { "data-i": i }, body);
}

function stepNode(s) {
  const state = s.state === "running" ? h("span.state", {}, h("span.spinner")) : s.state === "error" ? h("span.state.bad", {}, icon("x", 15)) : h("span.state.ok", {}, icon("check", 15));
  return h("div.step" + (s.state === "error" ? ".error" : ""), {},
    icon(TOOL_ICON[s.tool] || "wrench", 16),
    h("span.what", {}, s.label, s.detail ? h("span.detail", { title: s.detail }, s.detail) : null,
      s.link ? h("a.step-link", { href: s.link, target: s.link.startsWith("/") || s.link.startsWith("mailto:") ? null : "_blank", rel: "noopener", download: s.download || null },
        icon(s.download ? "calendar" : s.link.startsWith("mailto:") ? "mail" : "external", 14), s.linkLabel || "Open") : null,
      s.copy ? h("button.step-link", { type: "button", onclick: (e) => copy(s.copy, e.currentTarget) }, icon("copy", 14), "Copy") : null),
    state);
}

let paintQueued = false;
function paintLast() {
  if (paintQueued) return;
  paintQueued = true;
  requestAnimationFrame(() => {
    paintQueued = false;
    if (!S.chat || !els.thread?.isConnected) return;
    const i = S.chat.msgs.length - 1;
    const old = els.thread.querySelector(`.msg[data-i="${i}"]`);
    const node = msgNode(S.chat.msgs[i], i);
    node.style.animation = "none";
    if (old) old.replaceWith(node); else els.thread.append(node);
    if (S.stick) els.scroll.scrollTop = els.scroll.scrollHeight;
  });
}

function view(url) {
  const v = h("div.viewer", { onclick: () => v.remove() }, h("img", { src: url, alt: "" }));
  document.body.append(v);
}

// ---- composer -----------------------------------------------------------------------------------

function buildComposer() {
  els.input = h("textarea", { rows: 1, placeholder: "Message AFH", "aria-label": "Message" });
  els.input.addEventListener("input", () => { grow(); syncSend(); });
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && matchMedia("(hover: hover)").matches) { e.preventDefault(); submit(); }
  });
  els.input.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  els.file = h("input", { type: "file", multiple: true, hidden: true, accept: "image/*,.txt,.md,.csv,.json,.js,.ts,.py,.html,.css,.xml,.yml,.yaml,.log,.java,.c,.cpp,.cs,.go,.rs,.rb,.php,.sh,.sql,.dart,.kt,.swift" });
  els.file.addEventListener("change", () => { addFiles([...els.file.files]); els.file.value = ""; });
  els.atts = h("div.attachments", { hidden: true });
  els.send = h("button.send", { type: "button", "aria-label": "Send", onclick: () => (S.run ? stop() : submit()) }, icon("up", 18, 2.2));
  els.tools = h("button.chip", { type: "button", title: "Let the model search the web and use tools", onclick: () => save({ tools: !settings.tools }) }, icon("globe", 15), "Tools");
  const speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  els.mic = speech ? h("button.icon-btn", { type: "button", title: "Dictate", "aria-label": "Dictate", onclick: dictate }, icon("mic", 18)) : null;
  els.composerBox = h("div.composer", {},
    els.atts, els.input,
    h("div.composer-row", {},
      h("button.icon-btn", { type: "button", title: "Add photos and files", "aria-label": "Add photos and files", onclick: () => els.file.click() }, icon("plus", 19)),
      els.tools, h("div.grow"), els.mic, els.send),
    els.file);
  for (const ev of ["dragenter", "dragover"]) els.composerBox.addEventListener(ev, (e) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); els.composerBox.classList.add("drop"); } });
  for (const ev of ["dragleave", "drop"]) els.composerBox.addEventListener(ev, () => els.composerBox.classList.remove("drop"));
  els.composerBox.addEventListener("drop", (e) => { e.preventDefault(); addFiles([...(e.dataTransfer?.files || [])]); });
  syncComposer();
}
function grow() { els.input.style.height = "auto"; els.input.style.height = Math.min(els.input.scrollHeight, innerHeight * 0.4) + "px"; }
function syncSend() {
  const running = !!S.run;
  els.send.classList.toggle("stop", running);
  put(els.send, icon(running ? "stop" : "up", 18, 2.2));
  els.send.setAttribute("aria-label", running ? "Stop" : "Send");
  els.send.disabled = !running && !els.input.value.trim() && !S.attached.length;
}
function syncComposer() {
  els.tools.classList.toggle("on", settings.tools);
  els.tools.setAttribute("aria-pressed", String(settings.tools));
  syncSend();
}

async function addFiles(files) {
  for (const f of files) {
    if (S.attached.length >= 6) { toast("Up to 6 attachments at a time", true); break; }
    if (f.type.startsWith("image/")) {
      try { S.attached.push({ kind: "image", name: f.name, url: await shrink(f) }); } catch { toast(`Couldn't read ${f.name}`, true); }
    } else {
      if (f.size > 400 * 1024) { toast(`${f.name} is too big (400 KB at most)`, true); continue; }
      const text = await f.text();
      if (/\u0000/.test(text.slice(0, 2000))) { toast(`${f.name} isn't a text file`, true); continue; }
      S.attached.push({ kind: "file", name: f.name, text });
    }
  }
  paintAttachments();
}
function shrink(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.86));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}
function paintAttachments() {
  els.atts.hidden = !S.attached.length;
  put(els.atts, ...S.attached.map((a, i) => h("div.att" + (a.kind === "image" ? ".img" : ""), { title: a.name },
    a.kind === "image" ? h("img", { src: a.url, alt: a.name }) : [icon("file", 18), h("span", {}, a.name)],
    h("button.x", { type: "button", "aria-label": `Remove ${a.name}`, onclick: () => { S.attached.splice(i, 1); paintAttachments(); } }, icon("x", 12, 2.4)))));
  syncSend();
}

function dictate() {
  if (S.rec) { S.rec.stop(); return; }
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new Rec();
  rec.lang = navigator.language || "en-US";
  rec.interimResults = true;
  rec.continuous = true;
  const before = els.input.value ? els.input.value.replace(/\s*$/, " ") : "";
  rec.onresult = (e) => {
    let text = "";
    for (const r of e.results) text += r[0].transcript;
    els.input.value = before + text;
    grow(); syncSend();
  };
  rec.onend = () => { S.rec = null; els.mic.classList.remove("chip", "rec"); put(els.mic, icon("mic", 18)); };
  rec.onerror = (e) => { if (e.error === "not-allowed") toast("Allow the microphone for this site to dictate", true); };
  S.rec = rec;
  put(els.mic, icon("stop", 16));
  els.mic.title = "Stop dictating";
  rec.start();
}

// ---- sending ------------------------------------------------------------------------------------

function submit() {
  const text = els.input.value.trim();
  if (!text && !S.attached.length) return;
  S.rec?.stop();
  send(text);
}

async function send(text) {
  if (S.run) return;
  const m = currentModel();
  if (!m) { openSettings("providers"); toast("Add a model provider first"); return; }
  const files = S.attached.filter((a) => a.kind === "file");
  const images = S.attached.filter((a) => a.kind === "image").map((a) => a.url);
  const full = [text, ...files.map((f) => `<file name="${f.name}">\n${f.text}\n</file>`)].filter(Boolean).join("\n\n");
  S.attached = [];
  paintAttachments();
  els.input.value = "";
  grow();
  if (!S.chat) {
    S.chat = { id: newId(), title: titleFrom(text || files[0]?.name || "Photo"), created: Date.now(), updated: Date.now(), msgs: [] };
    S.chats.unshift(S.chat);
    S.quietHash = true;
    location.hash = `#/c/${S.chat.id}`;
  }
  S.chat.msgs.push({ role: "user", text: full, shown: text, images, files: files.map((f) => f.name) });
  await reply(m);
}

async function reply(m) {
  const chat = S.chat;
  const ai = { role: "assistant", text: "", reasoning: "", steps: [], provider: m.p.id, model: m.id, streaming: true };
  chat.msgs.push(ai);
  chat.updated = Date.now();
  S.chats.sort((a, b) => b.updated - a.updated);
  renderBody();
  renderSide();
  const run = new Run(m.p, m.id, chat.msgs.slice(0, -1), { system: settings.system, env: { confirm } });
  S.run = run;
  syncSend();
  try {
    for await (const d of run.start()) {
      if (d.text) ai.text += d.text;
      if (d.reasoning) ai.reasoning += d.reasoning;
      if (d.step && !ai.steps.includes(d.step)) ai.steps.push(d.step);
      if (S.chat === chat) paintLast();
    }
  } catch (e) {
    ai.error = e instanceof AiError ? e.message : `Something went wrong: ${e.message || e}`;
  } finally {
    ai.streaming = false;
    for (const s of ai.steps) if (s.state === "running") { s.state = "error"; s.detail ||= "Stopped"; }
    if (run.cancelled && !ai.text && !ai.steps.length && !ai.error) ai.error = "Stopped.";
    S.run = null;
    chat.updated = Date.now();
    await putChat(stripRuntime(chat));
    syncSend();
    if (S.chat === chat) renderBody();
    renderSide();
  }
}
// Blob links (calendar files) don't survive a reload: keep the step, drop the dead link.
const stripRuntime = (chat) => ({ ...chat, msgs: chat.msgs.map((m) => (m.steps ? { ...m, streaming: false, steps: m.steps.map((s) => (s.link?.startsWith("blob:") ? { ...s, link: null } : s)) } : m)) });

function stop() { S.run?.cancel(); }

async function retry(i) {
  if (S.run) return;
  const m = currentModel();
  if (!m) { openSettings("providers"); return; }
  S.chat.msgs.splice(i);
  await reply(m);
}

function editMsg(i, node) {
  const m = S.chat.msgs[i];
  const ta = h("textarea", { rows: 3 });
  ta.value = m.shown ?? m.text;
  const done = async (ok) => {
    if (!ok) { renderBody(); return; }
    const text = ta.value.trim();
    if (!text) return;
    const extra = m.text.slice((m.shown ?? m.text).length);
    S.chat.msgs.splice(i + 1);
    Object.assign(m, { shown: text, text: text + extra });
    const cm = currentModel();
    if (cm) await reply(cm); else { renderBody(); openSettings("providers"); }
  };
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(true); } if (e.key === "Escape") done(false); });
  node.querySelector(".bubble")?.replaceWith(h("div.bubble.editing", {}, ta,
    h("div.edit-row", {}, h("button.btn.ghost", { type: "button", onclick: () => done(false) }, "Cancel"), h("button.btn.primary", { type: "button", onclick: () => done(true) }, "Send"))));
  node.querySelector(".msg-tools")?.remove();
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
}

// ---- small dialogs and menus -------------------------------------------------------------------

function confirm(title, text, action = "OK", danger = false) {
  return new Promise((resolve) => {
    const close = (v) => { back.remove(); resolve(v); };
    const back = h("div.modal-back", { onclick: (e) => e.target === back && close(false) },
      h("div.modal.small", { role: "dialog", "aria-modal": "true" },
        h("h2", {}, title), h("p", {}, text),
        h("div.row", {}, h("button.btn.ghost", { type: "button", onclick: () => close(false) }, "Cancel"),
          h(`button.btn.${danger ? "danger" : "primary"}`, { type: "button", onclick: () => close(true) }, action))));
    back.addEventListener("keydown", (e) => e.key === "Escape" && close(false));
    document.body.append(back);
    back.querySelector(".btn:last-child").focus();
  });
}
function prompt(title, value) {
  return new Promise((resolve) => {
    const input = h("input.input", { value });
    const close = (v) => { back.remove(); resolve(v); };
    const back = h("div.modal-back", { onclick: (e) => e.target === back && close(null) },
      h("div.modal.small", { role: "dialog", "aria-modal": "true" }, h("h2", {}, title), h("div.field", {}, input),
        h("div.row", {}, h("button.btn.ghost", { type: "button", onclick: () => close(null) }, "Cancel"), h("button.btn.primary", { type: "button", onclick: () => close(input.value) }, "Save"))));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") close(input.value); if (e.key === "Escape") close(null); });
    document.body.append(back);
    input.focus();
    input.select();
  });
}

function popover(anchor, node, { align = "start" } = {}) {
  closePop();
  const back = h("div", { style: { position: "fixed", inset: "0", zIndex: 59 }, onclick: closePop });
  const pop = h("div.pop", {}, node);
  document.body.append(back, pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth, ht = pop.offsetHeight;
  let left = align === "start" ? r.left : r.right - w;
  left = Math.max(10, Math.min(left, innerWidth - w - 10));
  let top = r.bottom + 6;
  if (top + ht > innerHeight - 10) top = Math.max(10, r.top - ht - 6);
  Object.assign(pop.style, { left: left + "px", top: top + "px" });
  S.pop = { back, pop, anchor };
  anchor.setAttribute("aria-expanded", "true");
  const onKey = (e) => e.key === "Escape" && closePop();
  addEventListener("keydown", onKey);
  S.pop.off = () => removeEventListener("keydown", onKey);
  return pop;
}
function closePop() {
  if (!S.pop) return;
  S.pop.back.remove(); S.pop.pop.remove(); S.pop.off(); S.pop.anchor.setAttribute("aria-expanded", "false");
  S.pop = null;
}

function chatMenu(anchor, c) {
  popover(anchor, h("div.menu", {},
    h("button", { type: "button", onclick: async () => {
      closePop();
      const t = await prompt("Rename chat", c.title);
      if (t?.trim()) { c.title = t.trim(); await putChat(stripRuntime(c)); renderSide(); if (S.chat?.id === c.id) document.title = `${c.title} · AFH`; }
    } }, icon("pencil", 16), "Rename"),
    h("button.bad", { type: "button", onclick: async () => {
      closePop();
      if (!(await confirm("Delete chat?", `“${c.title}” will be deleted from this browser.`, "Delete", true))) return;
      await deleteChat(c.id);
      S.chats = S.chats.filter((x) => x.id !== c.id);
      if (S.chat?.id === c.id) location.hash = "#/"; else renderSide();
    } }, icon("trash", 16), "Delete")), { align: "end" });
}

function meMenu(anchor) {
  const pop = popover(anchor, h("div.menu", { style: { minWidth: "240px" } },
    h("div.label", {}, S.me?.user?.email || ""),
    h("button", { type: "button", onclick: () => { closePop(); openSettings("general"); } }, icon("settings", 16), "Settings"),
    h("button", { type: "button", onclick: () => { closePop(); openSettings("providers"); } }, icon("key", 16), "Providers"),
    h("a", { href: "/computers" }, icon("laptop", 16), "Computers"),
    h("a", { href: "/computers#/account" }, icon("user", 16), "Account and password"),
    h("hr"),
    h("a", { href: "/" }, icon("home", 16), "agentflowharness.com"),
    h("a", { href: "/download" }, icon("arrowDown", 16), "Get the apps"),
    h("hr"),
    h("button", { type: "button", onclick: signOutAfh }, icon("logout", 16), "Sign out")));
  const r = anchor.getBoundingClientRect();
  pop.style.top = Math.max(10, r.top - pop.offsetHeight - 6) + "px";
}
async function signOutAfh() {
  closePop();
  try { await fetch("/relay/api/signout", { method: "POST", credentials: "same-origin" }); } catch { /* gone anyway */ }
  location.href = "/";
}

// ---- model picker -----------------------------------------------------------------------------------

function openPicker() {
  const ready = readyProviders();
  const search = h("input", { type: "search", placeholder: "Search models", "aria-label": "Search models" });
  const list = h("div.picker-list", { role: "listbox" });
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    const cur = currentModel();
    const kids = [];
    for (const p of ready) {
      const ms = p.models.filter((id) => !q || id.toLowerCase().includes(q) || p.name.toLowerCase().includes(q));
      if (!ms.length && q) continue;
      const refresh = h("button.icon-btn", { type: "button", title: "Refresh models", "aria-label": `Refresh ${p.name} models`, onclick: async () => {
        put(refresh, h("span.spinner"));
        try { save({ models: { ...settings.models, [p.id]: await fetchModels(p) } }); paint(); } catch (e) { toast(e.message, true); put(refresh, icon("refresh", 15)); }
      } }, icon("refresh", 15));
      kids.push(h("div.picker-group", {}, h("span.pdot", { style: { background: p.color } }), p.name, refresh));
      if (!ms.length) kids.push(h("p.picker-empty", {}, "No models yet — refresh."));
      for (const id of ms.slice(0, q ? 200 : 60)) {
        const on = cur && cur.p.id === p.id && cur.id === id;
        kids.push(h("button.picker-item" + (on ? ".on" : ""), { type: "button", role: "option", "aria-selected": String(!!on), onclick: () => {
          save({ model: { provider: p.id, id } });
          closePop();
          renderTop();
          els.input.focus();
        } }, h("span", {}, id), on ? icon("check", 16) : null));
      }
    }
    if (!ready.length) kids.push(h("div.picker-empty", {}, "No providers yet. Add one to start chatting."));
    else if (!kids.length) kids.push(h("div.picker-empty", {}, "No model matches."));
    put(list, ...kids);
  };
  search.addEventListener("input", paint);
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") list.querySelector(".picker-item")?.click(); });
  paint();
  popover(els.modelBtn, h("div.picker", {},
    h("label.picker-search", {}, icon("search", 15), search),
    list,
    h("div.picker-foot", {}, h("button", { type: "button", onclick: () => { closePop(); openSettings("providers"); } }, icon("key", 16), "Add or manage providers"))));
  search.focus();
}

// ---- settings ----------------------------------------------------------------------------------------

let modal = null;
function openSettings(tab = "general", providerId = null) {
  closePop();
  if (!isWide()) app.classList.remove("side-open");
  modal?.back.remove();
  const tabs = [["general", "settings", "General"], ["providers", "key", "Providers"], ["memory", "bookmark", "Memory"], ["data", "user", "Data and account"]];
  const body = h("div.modal-body");
  const nav = h("nav.modal-tabs", {}, h("h2", {}, "Settings"));
  const close = () => { modal?.back.remove(); modal = null; off(); renderTop(); syncComposer(); if (!S.chat) renderBody(); };
  const back = h("div.modal-back", { onclick: (e) => e.target === back && close() },
    h("div.modal", { role: "dialog", "aria-modal": "true", "aria-label": "Settings" }, nav, body));
  const onKey = (e) => e.key === "Escape" && !document.querySelector(".modal.small") && close();
  addEventListener("keydown", onKey);
  const off = () => removeEventListener("keydown", onKey);
  modal = { back, body, show: (t, pid) => {
    modal.tab = t;
    put(nav, nav.firstChild, ...tabs.map(([id, ic, label]) => h("button.nav-item" + (id === t ? ".on" : ""), { type: "button", onclick: () => modal.show(id) }, icon(ic, 17), label)));
    const close_ = h("button.icon-btn.modal-close", { type: "button", "aria-label": "Close", onclick: close }, icon("x", 18));
    const views = { general: generalView, providers: () => (pid ? providerView(providerById(pid)) : providersView()), memory: memoryView, data: dataView };
    put(body, close_, ...[views[t]()].flat());
    body.scrollTop = 0;
  } };
  document.body.append(back);
  modal.show(tab, providerId);
}

function generalView() {
  const theme = settings.theme;
  const seg = h("div.seg", {}, [["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) =>
    h("button" + (theme === v ? ".on" : ""), { type: "button", onclick: () => { save({ theme: v }); applyTheme(); modal.show("general"); } }, l)));
  const sys = h("textarea.input", { placeholder: "e.g. Answer briefly. I'm a developer in Cairo, I prefer metric units." });
  sys.value = settings.system;
  sys.addEventListener("change", () => save({ system: sys.value.trim() }));
  return [
    h("h3", {}, "General"), h("p.lead", {}, "How AFH looks and behaves in this browser."),
    h("div.group", {},
      h("div.row", {}, h("div.grow", {}, h("b", {}, "Appearance"), h("span", {}, "Follow your system, or pick one")), seg),
      h("button.row", { type: "button", onclick: () => { save({ tools: !settings.tools }); modal.show("general"); } },
        h("div.grow", {}, h("b", {}, "Tools"), h("span", {}, settings.tools ? "Web search, pages, weather, location, math, email drafts, calendar, reminders, memory, your PCs" : "Off: models only chat")),
        h("span.switch" + (settings.tools ? ".on" : ""), { role: "switch", "aria-checked": String(settings.tools) }))),
    h("p.group-label", {}, "Custom instructions"),
    h("div.field", {}, sys, h("span.hint", {}, "Sent to every model with every chat.")),
  ];
}

function providerRow(p) {
  return h("button.row", { type: "button", onclick: () => modal.show("providers", p.id) },
    h("span.pav", { style: { background: `color-mix(in srgb, ${p.color} 16%, transparent)`, color: p.color } }, p.initial),
    h("div.grow", {}, h("b", {}, p.name), h("span", {}, p.ready ? `${p.models.length} model${p.models.length === 1 ? "" : "s"}` : p.blurb)),
    p.ready ? h("span.badge.good", {}, "Connected") : p.login ? h("span.badge.accent", {}, "Sign in") : null,
    icon("right", 16));
}

function providersView() {
  const search = h("input.input", { type: "search", placeholder: `Search ${providers.length} providers` });
  const list = h("div");
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    if (q) {
      const hits = providers.filter((p) => p.name.toLowerCase().includes(q) || p.id.includes(q));
      put(list, h("p.group-label", {}, `${hits.length} found`), hits.length ? h("div.group", {}, hits.map(providerRow)) : h("p.muted", {}, "Nothing matches."));
      return;
    }
    const ready = providers.filter((p) => p.ready);
    const popular = providers.filter((p) => p.featured && !p.ready).sort((a, b) => (b.login ? 1 : 0) - (a.login ? 1 : 0));
    const rest = providers.filter((p) => !p.featured && !p.ready);
    put(list, ready.length ? [h("p.group-label", {}, "Connected"), h("div.group", {}, ready.map(providerRow))] : null,
      h("p.group-label", {}, "Popular"), h("div.group", {}, popular.map(providerRow)),
      h("p.group-label", {}, "More providers"), h("div.group", {}, rest.map(providerRow)));
  };
  search.addEventListener("input", paint);
  paint();
  setTimeout(() => search.focus(), 0);
  return [h("h3", {}, "Providers"), h("p.lead", {}, "Sign in or paste a key. Keys stay in this browser; requests pass through AFH's server to the provider without being stored."),
    h("div.field", {}, search), list];
}

function providerView(p) {
  const msg = h("p.note", { hidden: true });
  const say = (text, kind) => { msg.textContent = text; msg.className = kind ? `note ${kind}` : "note"; msg.hidden = !text; };
  const out = [h("button.back-link", { type: "button", onclick: () => modal.show("providers") }, icon("left", 15), "All providers"),
    h("div", { style: { display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" } },
      h("span.pav", { style: { width: "44px", height: "44px", fontSize: "18px", background: `color-mix(in srgb, ${p.color} 16%, transparent)`, color: p.color } }, p.initial),
      h("div", {}, h("h3", {}, p.name, " ", p.ready ? h("span.badge.good", {}, "Connected") : null), h("p.lead", { style: { margin: 0 } }, p.blurb)))];
  out.push(msg);

  const connected = async () => {
    try {
      say("Checking…");
      const models = await fetchModels(p);
      save({ models: { ...settings.models, [p.id]: models } });
      if (!currentModel() || !settings.model || !providerById(settings.model.provider)?.ready) save({ model: { provider: p.id, id: models[0] } });
      modal.show("providers", p.id);
      toast(`${p.name} is connected`);
    } catch (e) { say(e.message, "bad"); }
  };

  // sign-in
  if (p.login) {
    const auth = settings.auth[p.id];
    const box = h("div.group", { style: { padding: "16px" } });
    if (p.signedIn || (p.login === "openrouter" && settings.keys[p.id])) {
      box.append(h("div", { style: { display: "flex", alignItems: "center", gap: "12px" } },
        icon("check", 18), h("div.grow", { style: { flex: 1 } }, h("b", {}, "Signed in"), h("div.muted", {}, auth?.account || (auth?.plan ? `ChatGPT ${auth.plan}` : `${p.name} account`))),
        h("button.btn.ghost", { type: "button", onclick: () => { signOut(p.id); modal.show("providers", p.id); } }, "Sign out")));
    } else if (p.login === "openrouter") {
      box.append(h("p", { style: { margin: "0 0 12px", color: "var(--text2)" } }, "Sign in with your OpenRouter account — it makes a key for AFH, no copying needed."),
        h("button.btn.primary.wide", { type: "button", onclick: openrouterStart }, "Sign in with OpenRouter"));
    } else if (p.login === "chatgpt") {
      const paste = h("input.input.mono", { placeholder: "http://localhost:1455/auth/callback?code=…" });
      const finish = h("button.btn.primary", { type: "button", onclick: async () => {
        finish.disabled = true;
        try { const who = await chatgptFinish(paste.value); toast(`Signed in${who ? ` as ${who}` : ""}`); await connected(); } catch (e) { say(e.message, "bad"); } finally { finish.disabled = false; }
      } }, "Finish");
      box.append(h("p", { style: { margin: "0 0 10px", color: "var(--text2)" } }, "Use your ChatGPT Plus, Pro or Team plan. Three steps:"),
        h("ol.steps-list", {},
          h("li", {}, "Open the sign-in and log in to ChatGPT."),
          h("li", {}, "It ends on a page that can't load (", h("code", {}, "localhost:1455"), ") — that's expected."),
          h("li", {}, "Copy that page's full address from the address bar and paste it here.")),
        h("button.btn.ghost.wide", { type: "button", style: { marginBottom: "12px" }, onclick: chatgptStart }, icon("external", 16), "Open ChatGPT sign-in"),
        h("div.with-btn", {}, paste, finish));
    } else if (p.login === "copilot") {
      const go = h("button.btn.primary.wide", { type: "button" }, "Sign in with GitHub");
      go.onclick = async () => {
        const ctrl = new AbortController();
        go.disabled = true;
        go.textContent = "Starting…";
        try {
          await copilotSignIn((code, url) => {
            go.replaceWith(h("div.code-card", {}, h("div.muted", {}, "Enter this code on GitHub"), h("b", {}, code),
              h("button.btn.primary", { type: "button", onclick: () => { navigator.clipboard?.writeText(code).catch(() => {}); window.open(url, "_blank", "noopener"); } }, icon("copy", 16), "Copy code and open GitHub"),
              h("p.muted", { style: { margin: "12px 0 0", fontSize: "13px" } }, h("span.spinner", { style: { verticalAlign: "-2px", marginRight: "8px" } }), "Waiting for you to approve it on GitHub…"),
              h("button.btn.ghost", { type: "button", style: { marginTop: "10px" }, onclick: () => { ctrl.abort(); modal.show("providers", p.id); } }, "Cancel")));
          }, ctrl.signal);
          await connected();
        } catch (e) {
          if (e.name === "AbortError") return;
          say(e.message, "bad");
          go.disabled = false;
          go.textContent = "Try again";
        }
      };
      box.append(h("p", { style: { margin: "0 0 12px", color: "var(--text2)" } }, "Use your GitHub Copilot plan: you approve AFH on github.com with a short code."), go);
    }
    out.push(h("p.group-label", {}, "Sign in"), box);
  }

  // key, address and fields
  if (!p.loginOnly) {
    const fields = [];
    const addr = p.needsAddress ? h("input.input.mono", { value: settings.base[p.id] || "", placeholder: p.custom ? "http://localhost:11434/v1 or https://…" : (p.base || "http://localhost:…") }) : null;
    if (addr) fields.push(h("div.field", {}, h("label", {}, "Server address"), addr,
      h("span.hint", {}, "A server on this computer (http://localhost…) is called straight from your browser; anywhere else needs https.")));
    const params = p.params.map((x) => {
      const input = h("input.input", { value: settings.params[p.id]?.[x.name] || "", placeholder: x.fallback || x.label });
      fields.push(h("div.field", {}, h("label", {}, x.label), input));
      return [x.name, input];
    });
    const key = h("input.input.mono", { type: "password", value: settings.keys[p.id] || "", placeholder: p.keyHint || "Paste your API key", autocomplete: "off", spellcheck: "false" });
    const eye = h("button.btn.ghost", { type: "button", title: "Show key", onclick: () => { key.type = key.type === "password" ? "text" : "password"; } }, icon("eye", 16));
    fields.push(h("div.field", {}, h("label", {}, p.noKey ? "API key (optional)" : "API key"), h("div.with-btn", {}, key, eye),
      p.keysUrl ? h("span.hint", {}, "Get one at ", h("a", { href: p.keysUrl, target: "_blank", rel: "noopener" }, new URL(p.keysUrl).host), p.hint ? ` · ${p.hint}` : "") : p.hint ? h("span.hint", {}, p.hint) : null));
    const saveBtn = h("button.btn.primary", { type: "button", onclick: async () => {
      const keys = { ...settings.keys }, base = { ...settings.base }, prm = { ...settings.params, [p.id]: { ...(settings.params[p.id] || {}) } };
      if (key.value.trim()) keys[p.id] = key.value.trim(); else delete keys[p.id];
      if (addr) { if (addr.value.trim()) base[p.id] = addr.value.trim(); else delete base[p.id]; }
      for (const [name, input] of params) prm[p.id][name] = input.value.trim();
      save({ keys, base, params: prm });
      if (!p.ready) { say(p.needsAddress ? "Enter the server address." : "Paste a key first.", "bad"); return; }
      saveBtn.disabled = true;
      await connected();
      saveBtn.disabled = false;
    } }, p.ready ? "Save and check again" : "Connect");
    out.push(h("p.group-label", {}, p.login ? "Or use an API key" : "Connect"), ...fields, saveBtn);
  }

  if (p.ready) {
    out.push(h("p.group-label", {}, `${p.models.length} model${p.models.length === 1 ? "" : "s"}`), h("div.models-list", {}, p.models.slice(0, 120).map((m) => h("span", {}, m))));
    out.push(h("div", { style: { marginTop: "22px" } }, h("button.btn.danger", { type: "button", onclick: async () => {
      if (!(await confirm(`Remove ${p.name}?`, "Its key or sign-in is removed from this browser.", "Remove", true))) return;
      signOut(p.id);
      const keys = { ...settings.keys }, base = { ...settings.base }, models = { ...settings.models };
      delete keys[p.id]; delete base[p.id]; delete models[p.id];
      save({ keys, base, models, ...(settings.model?.provider === p.id ? { model: null } : {}) });
      modal.show("providers", p.id);
    } }, icon("trash", 16), "Remove this provider")));
  }
  return out;
}

function memoryView() {
  const add = h("input.input", { placeholder: "e.g. I live in Cairo and I'm vegetarian" });
  const doAdd = () => { const v = add.value.trim(); if (v) { save({ memory: [...settings.memory, v] }); modal.show("memory"); } };
  add.addEventListener("keydown", (e) => e.key === "Enter" && doAdd());
  return [h("h3", {}, "Memory"), h("p.lead", {}, "What AFH remembers about you. It goes along with every chat in this browser — say “remember that…” in a chat, or add it here."),
    h("div.with-btn", { style: { marginBottom: "18px" } }, add, h("button.btn.primary", { type: "button", onclick: doAdd }, "Add")),
    settings.memory.length ? h("div.group", {}, settings.memory.map((f, i) => h("div.row", {}, h("div.grow", {}, h("b", { style: { fontWeight: 400 } }, f)),
      h("button.icon-btn", { type: "button", title: "Forget", "aria-label": "Forget", onclick: () => { save({ memory: settings.memory.filter((_, j) => j !== i) }); modal.show("memory"); } }, icon("x", 16)))))
      : h("p.muted", {}, "Nothing remembered yet.")];
}

function dataView() {
  return [h("h3", {}, "Data and account"), h("p.lead", {}, "Chats, keys and sign-ins are kept in this browser only. Your AFH account holds your email and your computers."),
    h("div.group", {},
      h("div.row", {}, h("div.grow", {}, h("b", {}, "Signed in as"), h("span", {}, S.me?.user?.email || "")), h("a.btn.ghost", { href: "/computers#/account" }, "Manage")),
      h("button.row", { type: "button", onclick: async () => {
        if (!(await confirm("Delete all chats?", `${S.chats.length} chat${S.chats.length === 1 ? "" : "s"} will be deleted from this browser.`, "Delete all", true))) return;
        await deleteAllChats();
        S.chats = [];
        modal.show("data");
        location.hash = "#/";
        renderSide();
      } }, h("div.grow", {}, h("b", { style: { color: "var(--bad)" } }, "Delete all chats"), h("span", {}, `${S.chats.length} in this browser`))),
      h("button.row", { type: "button", onclick: signOutAfh }, h("div.grow", {}, h("b", {}, "Sign out"), h("span", {}, "Chats and keys stay in this browser")))),
  ];
}

function applyTheme() {
  let t = settings.theme;
  if (t !== "light" && t !== "dark") { try { t = localStorage.getItem("afh-theme"); } catch {} } // "system": the site's choice, if any
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}

// ---- routes and start ------------------------------------------------------------------------------

function route() {
  if (S.quietHash) { S.quietHash = false; renderSide(); renderTop(); renderBody(); return; }
  const id = (location.hash.match(/^#\/c\/([\w-]+)/) || [])[1];
  if (S.run && S.chat?.id !== id) { /* a reply keeps streaming into its chat in the background */ }
  S.chat = id ? S.chats.find((c) => c.id === id) || null : null;
  if (id && !S.chat) { history.replaceState(null, "", "#/"); }
  S.attached = [];
  paintAttachments();
  renderSide();
  renderTop();
  renderBody();
}

async function start() {
  let res;
  try { res = await fetch("/relay/api/me", { credentials: "same-origin" }); } catch { res = null; }
  if (res?.status === 401) { location.replace("/account?next=" + encodeURIComponent("/chat" + location.search + location.hash)); return; }
  try { S.me = res?.ok ? await res.json() : null; } catch { S.me = null; }
  if (!S.me?.user) {
    put(app, h("div.boot", {}, h("div", { style: { textAlign: "center" } }, h("h2", {}, "Can't reach AFH right now"), h("p.muted", {}, "Check your connection and try again."),
      h("button.btn.primary", { type: "button", onclick: () => location.reload() }, "Try again"))));
    return;
  }
  window.afhMe = S.me;
  applyTheme();
  await loadProviders();
  S.chats = await allChats();
  shell();
  addEventListener("hashchange", route);
  matchMedia("(min-width: 861px)").addEventListener("change", () => { app.classList.remove("side-open"); renderTop(); });
  onSettings(() => { syncComposer(); });
  addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); location.hash = "#/"; }
    if (e.key === "Escape" && S.run && !modal && !S.pop) stop();
  });
  route();
  try {
    if (await openrouterFinish()) {
      const p = providerById("openrouter");
      toast("Signed in to OpenRouter");
      openSettings("providers", "openrouter");
      try {
        const models = await fetchModels(p);
        save({ models: { ...settings.models, openrouter: models }, ...(currentModel()?.p.id === "openrouter" || !settings.model ? { model: { provider: "openrouter", id: models[0] } } : {}) });
        modal?.show("providers", "openrouter");
        renderTop();
      } catch { /* the key works; models load on refresh */ }
    }
  } catch (e) { toast(e.message, true); }
  // who's online changes now and then
  setInterval(async () => {
    if (document.hidden) return;
    try { const r = await fetch("/relay/api/me", { credentials: "same-origin" }); if (r.ok) { S.me = await r.json(); window.afhMe = S.me; if (!S.filter) renderSide(); } } catch { /* later */ }
  }, 30000);
}

start();
