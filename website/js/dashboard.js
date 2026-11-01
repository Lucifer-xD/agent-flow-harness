// Computers (/computers): the computers on your account, their threads, and live chat with AFH on them.
// Everything about a computer goes through the relay at /r/<computer>/api/… (the same API the
// desktop app and the phone app use), signed in by the account's HttpOnly cookie. Routes live in
// the hash: #/c/<computer>, #/c/<computer>/t/<thread>, #/c/<computer>/new, #/computers, #/account.
(() => {
  const root = document.getElementById("dash");
  const S = {
    me: null,
    cid: null,
    route: { view: "home" },
    projects: {},      // cid → [directory]
    sessions: {},      // cid → [session] | null (loading) | {error}
    asking: {},        // sid → true when a run waits on you
    es: null,          // live events from the chosen computer
    esCid: null,
    live: "off",
    thread: null,      // { cid, sid, session, msgs, perms, running, error, loaded }
    filter: "",
    sending: false,
  };

  // ---- tiny helpers ---------------------------------------------------------------------------

  const h = (tag, attrs, ...kids) => {
    const [name, ...classes] = tag.split(".");
    const node = document.createElement(name);
    if (classes.length) node.className = classes.join(" ");
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (k === "html") node.innerHTML = v;
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v != null) node.setAttribute(k, v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) node.append(kid);
    return node;
  };
  const base = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || String(p || "");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const ago = (ms) => {
    if (!ms) return "";
    const t = ms > 1e12 ? ms : ms * 1000;
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 45) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
    return new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };
  const seen = (t) => (t ? `seen ${ago(t)}` : "never connected");
  const md = (text) => {
    try {
      const html = window.marked ? marked.parse(String(text || ""), { breaks: true, gfm: true }) : esc(text).replace(/\n/g, "<br>");
      return window.DOMPurify ? DOMPurify.sanitize(html, { ADD_ATTR: ["target"] }) : esc(text);
    } catch { return esc(text); }
  };
  const ICON = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="2"/>',
    back: '<path d="M15 18l-6-6 6-6"/>',
    pc: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    term: '<path d="M4 6l5 5-5 5M12 18h8"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 14h.01M15 14h.01"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-2.4z"/>',
    q: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 17h.01"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  };
  const icon = (name, size = 18) => h("span.ic", { html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name] || ICON.tool}</svg>` });

  let toastTimer = 0;
  function toast(text, bad) {
    let t = document.querySelector(".dash-toast");
    if (!t) { t = h("div.dash-toast", { role: "status" }); document.body.append(t); }
    t.textContent = text;
    t.className = "dash-toast show" + (bad ? " bad" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
  }

  async function call(method, path, body) {
    const res = await fetch(path, {
      method, credentials: "same-origin",
      headers: body ? { "content-type": "application/json", accept: "application/json" } : { accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!res.ok) {
      const d = data && (data.error || data.detail);
      const message = typeof d === "string" ? d : Array.isArray(d) && d[0]?.msg ? d[0].msg : res.status === 503 ? "That computer is offline." : `Something went wrong (${res.status})`;
      if (res.status === 401 && path.startsWith("/relay/api/me")) location.replace("/account?next=" + encodeURIComponent("/computers" + location.hash));
      throw Object.assign(new Error(message), { status: res.status });
    }
    return data;
  }
  const account = (method, path, body) => call(method, "/relay/api/" + path, body);
  const pc = (cid, method, path, body) => call(method, `/r/${encodeURIComponent(cid)}${path}`, body);
  const computer = (cid) => S.me?.computers.find((c) => c.id === cid);

  // ---- routes ---------------------------------------------------------------------------------

  function parse() {
    const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    if (parts[0] === "computers") return { view: "computers" };
    if (parts[0] === "account") return { view: "account" };
    if (parts[0] === "c" && parts[1]) {
      if (parts[2] === "t" && parts[3]) return { view: "thread", cid: parts[1], sid: parts[3] };
      if (parts[2] === "new") return { view: "new", cid: parts[1] };
      return { view: "threads", cid: parts[1] };
    }
    return { view: "home" };
  }
  const go = (hash) => { if (location.hash !== hash) location.hash = hash; else route(); };

  function route() {
    const r = parse();
    if (r.view === "home") {
      const pick = S.me.computers.find((c) => c.id === S.cid) || S.me.computers.find((c) => c.online) || S.me.computers[0];
      if (pick) return go(`#/c/${encodeURIComponent(pick.id)}`);
    }
    if (r.cid && !computer(r.cid)) return go("#/");
    S.route = r;
    if (r.cid && r.cid !== S.cid) { S.cid = r.cid; S.filter = ""; }
    if (S.cid) { connect(S.cid); if (S.sessions[S.cid] === undefined) loadSessions(S.cid); }
    if (r.view === "thread" && (!S.thread || S.thread.sid !== r.sid || S.thread.cid !== r.cid)) openThread(r.cid, r.sid);
    if (r.view !== "thread") S.thread = null;
    if (r.view === "new" && !S.projects[r.cid]) loadProjects(r.cid);
    render();
  }

  // ---- data -------------------------------------------------------------------------------------

  async function loadMe() {
    S.me = await account("GET", "me");
    S.me.computers.sort((a, b) => (a.online !== b.online ? (a.online ? -1 : 1) : a.name.localeCompare(b.name)));
  }

  async function loadProjects(cid) {
    try {
      const settings = await pc(cid, "GET", "/api/settings");
      S.projects[cid] = (settings?.projects || []).filter((p) => typeof p === "string" && p);
    } catch (x) {
      S.projects[cid] = { error: x.message };
    }
    render();
  }

  let loadingFor = null;
  async function loadSessions(cid) {
    if (loadingFor === cid) return;
    loadingFor = cid;
    if (!Array.isArray(S.sessions[cid])) S.sessions[cid] = null;
    if (!computer(cid)?.online) { S.sessions[cid] = { error: `${computer(cid)?.name || "This computer"} is offline.`, offline: true }; loadingFor = null; render(); return; }
    render();
    try {
      let list;
      try {
        list = await pc(cid, "GET", "/api/sessions?limit=150");
      } catch (x) {
        if (x.status !== 422) throw x;
        // AFH before 1.9.1 lists one project at a time
        if (!Array.isArray(S.projects[cid])) await loadProjects(cid);
        const per = await Promise.all((S.projects[cid] || []).slice(0, 12).map((d) => pc(cid, "GET", "/api/sessions?directory=" + encodeURIComponent(d)).catch(() => [])));
        list = per.flat().sort((a, b) => (b.time?.updated || 0) - (a.time?.updated || 0));
      }
      S.sessions[cid] = Array.isArray(list) ? list : [];
      for (const s of S.sessions[cid]) if (!s.running) delete S.asking[s.id];
      const running = S.sessions[cid].filter((s) => s.running).slice(0, 8);
      await Promise.all(running.map((s) => pc(cid, "GET", `/api/sessions/${s.id}/permissions`)
        .then((v) => { if (Array.isArray(v) && v.length) S.asking[s.id] = true; else delete S.asking[s.id]; }).catch(() => {})));
    } catch (x) {
      S.sessions[cid] = { error: x.message, offline: x.status === 503 };
    }
    loadingFor = null;
    render();
  }

  let soon = 0;
  const reloadSoon = (cid, wait = 450) => { clearTimeout(soon); soon = setTimeout(() => loadSessions(cid), wait); };

  // live events from one computer (the desktop app's own stream); one connection at a time
  function connect(cid) {
    if (S.esCid === cid && S.es) return;
    S.es?.close();
    S.es = null;
    S.esCid = cid;
    S.live = "off";
    if (!computer(cid)?.online) return;
    const es = new EventSource(`/r/${encodeURIComponent(cid)}/api/events`, { withCredentials: true });
    S.es = es;
    es.onopen = () => { S.live = "live"; paintLive(); };
    es.onerror = () => { S.live = "reconnecting"; paintLive(); };
    es.onmessage = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev && typeof ev === "object") onEvent(cid, ev);
    };
  }

  function onEvent(cid, ev) {
    const t = ev.type || "";
    const d = ev.data || {};
    if (t === "permission.asked" && d.sessionID) S.asking[d.sessionID] = true;
    if (t.startsWith("session.execution.") || t === "session.created" || t === "session.renamed" || t.startsWith("permission.")) reloadSoon(cid);
    const th = S.thread;
    if (!th || th.cid !== cid) return;
    if (t === "permission.replied") {
      const id = String(d.id ?? d.permissionID ?? d.requestID);
      if (th.perms.some((p) => String(p.id) === id)) { th.perms = th.perms.filter((p) => String(p.id) !== id); paintThread(); }
      return;
    }
    if (d.sessionID !== th.sid) return;
    const aid = d.assistantMessageID;
    switch (t) {
      case "session.execution.started": th.running = true; th.runError = null; break;
      case "session.execution.succeeded": case "session.execution.interrupted": case "session.execution.failed":
        th.running = false;
        if (t.endsWith("failed")) th.runError = d.error?.message || "The run failed.";
        for (const m of th.msgs) { m.live = false; for (const p of m.content || []) p.live = false; }
        setTimeout(() => refreshThread(), 300);
        break;
      case "session.inbox.delivered": case "session.notice": case "session.compaction.ended": case "session.updated":
        clearTimeout(th.soon); th.soon = setTimeout(() => refreshThread(), 250); return;
      case "session.renamed": th.session.title = d.title; break;
      case "session.step.started": asst(th, aid); break;
      case "session.step.failed": {
        const err = d.error || {};
        if (!/interrupt|abort|cancel/i.test(`${err.type || ""} ${err.message || ""}`)) asst(th, aid).error = err.message;
        break;
      }
      case "session.text.started": case "session.reasoning.started":
        part(asst(th, aid), t.includes("reasoning") ? "reasoning" : "text", d.ordinal); break;
      case "session.text.delta": case "session.reasoning.delta": {
        const p = part(asst(th, aid), t.includes("reasoning") ? "reasoning" : "text", d.ordinal);
        p.text = (p.text || "") + (d.delta || "");
        break;
      }
      case "session.text.ended": case "session.reasoning.ended": {
        const p = part(asst(th, aid), t.includes("reasoning") ? "reasoning" : "text", d.ordinal);
        if (d.text != null) p.text = d.text;
        p.live = false;
        break;
      }
      case "session.tool.input.started": tool(asst(th, aid), d.id, d.name); break;
      case "session.tool.called": {
        const p = tool(asst(th, aid), d.id, d.name);
        p.name = d.name || p.name;
        p.state = { status: "running", input: d.input || {} };
        break;
      }
      case "session.tool.success": case "session.tool.failed": {
        const p = tool(asst(th, aid), d.id);
        const input = p.state?.input;
        p.state = t.endsWith("success") ? { status: "completed", input, content: d.content, metadata: d.metadata } : { status: "error", input, error: d.error, content: d.content };
        break;
      }
      case "permission.asked":
        if (!th.perms.some((p) => String(p.id) === String(d.id))) th.perms.push(d);
        break;
      default: return;
    }
    paintThread();
  }

  function asst(th, id) {
    const key = id || "live";
    let m = th.msgs.find((x) => x.id === key);
    if (!m) { m = { id: key, type: "assistant", content: [], live: true }; th.msgs.push(m); }
    m.content ||= [];
    return m;
  }
  function part(m, type, ordinal) {
    let p = m.content.find((c) => c.type === type && c.ordinal === ordinal);
    if (!p) { p = { type, ordinal, text: "", live: true }; m.content.push(p); }
    return p;
  }
  function tool(m, id, name) {
    let p = m.content.find((c) => c.type === "tool" && c.id === id);
    if (!p) { p = { type: "tool", id, name, state: { status: "pending", input: {} } }; m.content.push(p); }
    return p;
  }

  async function openThread(cid, sid) {
    S.thread = { cid, sid, session: { id: sid }, msgs: [], perms: [], running: false, loaded: false, open: new Set() };
    await refreshThread();
  }

  async function refreshThread() {
    const th = S.thread;
    if (!th) return;
    try {
      const [session, msgs, perms] = await Promise.all([
        pc(th.cid, "GET", `/api/sessions/${th.sid}`),
        pc(th.cid, "GET", `/api/sessions/${th.sid}/messages`),
        pc(th.cid, "GET", `/api/sessions/${th.sid}/permissions`).catch(() => []),
      ]);
      if (S.thread !== th) return;
      th.session = session || th.session;
      th.running = !!session?.running;
      th.msgs = Array.isArray(msgs) ? msgs : [];
      th.perms = Array.isArray(perms) ? perms : [];
      th.loaded = true;
      th.error = null;
    } catch (x) {
      if (S.thread !== th) return;
      if (!th.loaded) th.error = x.message; else toast(x.message, true);
    }
    render();
  }

  // ---- actions ------------------------------------------------------------------------------------

  async function send(text) {
    const th = S.thread;
    if (!th || !text.trim() || S.sending) return false;
    S.sending = true;
    try {
      await pc(th.cid, "POST", `/api/sessions/${th.sid}/prompt`, { text });
      th.msgs.push({ id: "local-" + Date.now(), type: "user", text, fresh: true });
      th.running = true;
      th.runError = null;
      setTimeout(refreshThread, 900);
      paintThread(true);
      return true;
    } catch (x) {
      toast(x.message, true);
      return false;
    } finally {
      S.sending = false;
    }
  }

  async function stop() {
    const th = S.thread;
    if (!th) return;
    try { await pc(th.cid, "POST", `/api/sessions/${th.sid}/interrupt`); toast("Stopping…"); } catch (x) { toast(x.message, true); }
  }

  async function answer(req, body) {
    const th = S.thread;
    try {
      await pc(th.cid, "POST", `/api/sessions/${th.sid}/permissions/${req.id}`, body);
      th.perms = th.perms.filter((p) => p.id !== req.id);
      delete S.asking[th.sid];
      paintThread();
      return true;
    } catch (x) { toast(x.message, true); return false; }
  }

  async function startThread(cid, dir, text) {
    const s = await pc(cid, "POST", "/api/sessions", { directory: dir });
    await pc(cid, "POST", `/api/sessions/${s.id}/prompt`, { text });
    (S.sessions[cid] = Array.isArray(S.sessions[cid]) ? S.sessions[cid] : []).unshift({ ...s, running: true, title: s.title || text.slice(0, 60) });
    go(`#/c/${encodeURIComponent(cid)}/t/${encodeURIComponent(s.id)}`);
  }

  // ---- views -------------------------------------------------------------------------------------

  const isWide = () => matchMedia("(min-width: 900px)").matches;

  function render() {
    const r = S.route;
    const wide = isWide();
    const side = sidebar();
    let main;
    if (r.view === "computers") main = computersView();
    else if (r.view === "account") main = accountView();
    else if (!S.me.computers.length) main = noComputers();
    else if (r.view === "thread") main = threadView();
    else if (r.view === "new" || (r.view === "threads" && wide)) main = newThreadView();
    else main = null;
    const showSide = wide || r.view === "threads";
    const keep = root.querySelector(".dash-input")?.value;
    const focused = document.activeElement?.classList.contains("dash-input");
    const sideScroll = root.querySelector(".dash-list")?.scrollTop;
    root.replaceChildren(h("div.dash-shell" + (wide ? "" : ".narrow"), {}, showSide ? side : null, main && (wide || !showSide) ? main : null));
    if (sideScroll) { const l = root.querySelector(".dash-list"); if (l) l.scrollTop = sideScroll; }
    const input = root.querySelector(".dash-input");
    if (input && keep) { input.value = keep; grow(input); }
    if (input && focused) input.focus();
    if (r.view === "thread") scrollThread(true);
  }

  function liveDot() {
    const map = { live: ["on", "Live"], reconnecting: ["warn", "Reconnecting…"], off: ["", "Offline"] };
    const [cls, label] = map[S.live] || map.off;
    return h("span.dash-live" + (cls ? "." + cls : ""), { title: label }, h("i"), label);
  }
  function paintLive() { const el = root.querySelector(".dash-live"); if (el) el.replaceWith(liveDot()); }

  function sidebar() {
    const c = computer(S.cid);
    const list = S.sessions[S.cid];
    const q = S.filter.trim().toLowerCase();
    let body;
    if (!S.me.computers.length) body = h("p.dash-muted.pad", {}, "No computers yet.");
    else if (list === null || list === undefined) body = h("div.dash-skel", {}, [1, 2, 3, 4, 5].map(() => h("i")));
    else if (!Array.isArray(list)) body = h("div.dash-state", {},
      h("b", {}, list.offline ? `${c?.name || "This computer"} is offline` : "Couldn't load threads"),
      h("p", {}, list.offline ? "Open AFH on that computer and keep it signed in (Settings → Remote control). This updates by itself." : list.error),
      h("button.btn.btn-ghost.btn-small", { type: "button", onclick: () => loadSessions(S.cid) }, "Try again"));
    else {
      const shown = list.filter((s) => !q || `${s.title || ""} ${base(s.project || s.location?.directory)}`.toLowerCase().includes(q));
      body = shown.length
        ? h("nav.dash-list", { "aria-label": "Threads" }, shown.map((s) => {
          const on = S.route.view === "thread" && S.route.sid === s.id;
          const needs = S.asking[s.id] || (Array.isArray(s.pending) ? s.pending.length : s.pending > 0);
          return h("a.dash-thread" + (on ? ".on" : ""), { href: `#/c/${encodeURIComponent(S.cid)}/t/${encodeURIComponent(s.id)}` },
            h("span.dash-thread-top", {},
              h("b", {}, s.title || "New thread"),
              s.running ? h("span.dash-run", { title: "Running" }) : null),
            h("span.dash-thread-sub", {},
              needs ? h("span.dash-needs", {}, "Needs you") : null,
              h("span", {}, base(s.project || s.location?.directory)),
              h("span", {}, ago(s.time?.updated))));
        }))
        : h("p.dash-muted.pad", {}, q ? "No thread matches." : "No threads yet — start one.");
    }
    const search = h("input.dash-search", { type: "search", placeholder: "Search threads", value: S.filter, "aria-label": "Search threads" });
    search.addEventListener("input", () => {
      S.filter = search.value;
      const pos = search.selectionStart;
      render();
      const again = root.querySelector(".dash-search");
      again?.focus();
      again?.setSelectionRange(pos, pos);
    });
    return h("aside.dash-side", {},
      S.me.computers.length ? h("div.dash-pcs", { role: "tablist", "aria-label": "Computers" }, S.me.computers.map((pc_) =>
        h("a.dash-pc" + (pc_.id === S.cid ? ".on" : "") + (pc_.online ? ".up" : ""), { href: `#/c/${encodeURIComponent(pc_.id)}`, role: "tab", "aria-selected": String(pc_.id === S.cid), title: pc_.online ? "Online" : seen(pc_.lastSeen) },
          h("i"), h("span", {}, pc_.name)))) : null,
      c ? h("div.dash-side-head", {},
        h("a.btn.btn-primary.btn-small.dash-new", { href: `#/c/${encodeURIComponent(c.id)}/new` }, icon("plus", 16), "New thread"),
        h("button.dash-iconbtn", { type: "button", title: "Refresh", "aria-label": "Refresh", onclick: () => loadSessions(S.cid) }, icon("refresh", 17))) : null,
      c ? h("label.dash-searchbox", {}, icon("search", 16), search) : null,
      body,
      h("div.dash-side-foot", {},
        h("a", { href: "/chat" }, icon("send", 17), "Chat"),
        h("a" + (S.route.view === "computers" ? ".on" : ""), { href: "#/computers" }, icon("pc", 17), "Computers"),
        h("a" + (S.route.view === "account" ? ".on" : ""), { href: "#/account" }, icon("user", 17), "Account")));
  }

  function backBar(title, sub, extra) {
    return h("div.dash-head", {},
      !isWide() ? h("a.dash-iconbtn", { href: S.cid ? `#/c/${encodeURIComponent(S.cid)}` : "#/", "aria-label": "Back" }, icon("back", 20)) : null,
      h("div.dash-head-main", {}, h("h1", {}, title), sub ? h("p", {}, sub) : null),
      extra);
  }

  function noComputers() {
    return h("section.dash-main", {},
      h("div.dash-empty", {},
        h("div.dash-empty-art", {}, icon("pc", 34)),
        h("h1", {}, "Connect your first computer"),
        h("p", {}, "Install AFH on your PC, then open ", h("b", {}, "Settings → Remote control"), " and choose ", h("b", {}, "Sign in with your browser"), ". Approve it here and it appears on this page, ready for tasks."),
        h("div.cta-row.center", {},
          h("a.btn.btn-primary", { href: "/download" }, "Download AFH"),
          h("a.btn.btn-ghost", { href: "/docs" }, "Read the guide"))));
  }

  function newThreadView() {
    const c = computer(S.cid);
    if (!c) return noComputers();
    const projects = S.projects[S.cid];
    if (projects === undefined && c.online) loadProjects(S.cid);
    const dirs = Array.isArray(projects) ? projects : [];
    const select = h("select.dash-select", { "aria-label": "Project" }, dirs.map((d) => h("option", { value: d, title: d }, base(d))));
    const input = composer({
      placeholder: c.online ? `What should AFH do on ${c.name}?` : `${c.name} is offline`,
      disabled: !c.online || !dirs.length,
      async onSend(text) {
        if (!select.value) { toast("Pick a project first.", true); return false; }
        try { await startThread(S.cid, select.value, text); return true; } catch (x) { toast(x.message, true); return false; }
      },
    });
    const suggestions = ["Explain how this project is structured", "Find and fix the failing tests", "Review the latest changes for bugs", "Add a README with setup steps"];
    return h("section.dash-main", {},
      backBar("New thread", c.online ? `on ${c.name}` : `${c.name} · offline`,
        c.online ? h("a.btn.btn-ghost.btn-small.dash-full", { href: `/r/${encodeURIComponent(c.id)}/`, target: "_blank", rel: "noopener", title: "Open the complete AFH app from this computer in a new tab" }, icon("ext", 15), "Open full AFH") : null),
      h("div.dash-new-body", {},
        h("div.dash-hello", {},
          h("p.kicker", {}, c.online ? "Online" : "Offline"),
          h("h2", {}, c.online ? h("span", {}, "What are we building on ", h("span.grad-text", {}, c.name), "?") : `${c.name} is offline`),
          h("p", {}, c.online
            ? "Pick a project and describe the task. AFH runs it on that computer — you can follow every step here, approve what it asks and chat with it as it works."
            : "Open AFH on that computer and keep it signed in under Settings → Remote control. This page notices when it's back.")),
        c.online ? h("div.dash-proj", {},
          h("span", {}, "Project"),
          projects === undefined ? h("span.dash-muted", {}, "Loading projects…")
            : !Array.isArray(projects) ? h("span.dash-muted", {}, projects.error)
              : dirs.length ? select : h("span.dash-muted", {}, "No projects yet — open a folder in AFH on the computer first.")) : null,
        c.online && dirs.length ? h("div.dash-chips", {}, suggestions.map((s) => h("button.dash-chip", { type: "button", onclick: () => { const i = root.querySelector(".dash-input"); i.value = s; grow(i); i.focus(); } }, s))) : null),
      input);
  }

  function composer({ placeholder, disabled, onSend, running, onStop }) {
    const ta = h("textarea.dash-input", { rows: "1", placeholder, disabled: !!disabled, "aria-label": "Message" });
    const btn = h("button.dash-send", { type: "submit", "aria-label": "Send", title: "Send (Enter)", disabled: !!disabled }, icon("send", 18));
    const stopBtn = running ? h("button.dash-stop", { type: "button", "aria-label": "Stop", title: "Stop the run", onclick: onStop }, icon("stop", 16)) : null;
    const form = h("form.dash-composer", {
      async onsubmit(e) {
        e.preventDefault();
        const text = ta.value.trim();
        if (!text) return;
        btn.disabled = true;
        const ok = await onSend(text);
        btn.disabled = false;
        if (ok) { ta.value = ""; grow(ta); }
      },
    }, h("div.dash-composer-box", {}, ta, h("div.dash-composer-actions", {}, stopBtn, btn)),
    h("p.dash-composer-hint", {}, "Enter to send · Shift+Enter for a new line"));
    ta.addEventListener("input", () => grow(ta));
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && matchMedia("(pointer: fine)").matches) { e.preventDefault(); form.requestSubmit(); }
    });
    return form;
  }
  function grow(ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 220) + "px"; }

  // ---- a thread ----

  function threadView() {
    const th = S.thread;
    const c = computer(S.cid);
    if (!th) return h("section.dash-main", {});
    const s = th.session || {};
    const proj = base(s.project || s.location?.directory);
    const model = s.model && typeof s.model === "object" ? (s.model.id || s.model.modelID || "") : "";
    const status = th.running ? h("span.dash-status.run", {}, h("i"), "Working") : h("span.dash-status", {}, "Idle");
    const head = backBar(s.title || "New thread", [proj, model].filter(Boolean).join(" · "),
      h("div.dash-head-actions", {}, liveDot(), status,
        c?.online ? h("a.dash-iconbtn", { href: `/r/${encodeURIComponent(c.id)}/`, target: "_blank", rel: "noopener", title: "Open in the full AFH app", "aria-label": "Open in the full AFH app" }, icon("ext", 17)) : null));
    let body;
    if (th.error) body = h("div.dash-state", {}, h("b", {}, "Couldn't open this thread"), h("p", {}, th.error), h("button.btn.btn-ghost.btn-small", { type: "button", onclick: refreshThread }, "Try again"));
    else if (!th.loaded) body = h("div.dash-skel.thread", {}, [1, 2, 3].map(() => h("i")));
    else body = h("div.dash-msgs", {}, messages(th));
    return h("section.dash-main.dash-thread-view", {},
      head,
      h("div.dash-scroll", {}, body),
      h("div.dash-bottom", {},
        th.perms.length ? permCard(th.perms[0], th.perms.length - 1) : null,
        composer({
          placeholder: th.running ? "Add to the run…" : "Message AFH…",
          disabled: !c?.online,
          running: th.running,
          onStop: stop,
          onSend: send,
        })));
  }

  // repaint only the thread (live events come many times a second)
  let frame = 0;
  function paintThread(stick) {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (S.route.view !== "thread" || !S.thread) return;
      const box = root.querySelector(".dash-msgs");
      const sc = root.querySelector(".dash-scroll");
      const near = sc ? sc.scrollHeight - sc.scrollTop - sc.clientHeight < 140 : true;
      if (box && S.thread.loaded) box.replaceChildren(...messages(S.thread));
      const bottom = root.querySelector(".dash-bottom");
      if (bottom) {
        const keep = bottom.querySelector(".dash-input")?.value || "";
        const focused = document.activeElement?.classList.contains("dash-input");
        const permsNow = bottom.querySelector(".dash-perm")?.dataset.id || "";
        const want = S.thread.perms[0] ? String(S.thread.perms[0].id) : "";
        const runNow = !!bottom.querySelector(".dash-stop");
        if (permsNow !== want || runNow !== S.thread.running) {
          const fresh = threadView().querySelector(".dash-bottom");
          bottom.replaceWith(fresh);
          const i = fresh.querySelector(".dash-input");
          if (i) { i.value = keep; grow(i); if (focused) i.focus(); }
        }
      }
      const head = root.querySelector(".dash-head .dash-status");
      if (head) head.replaceWith(S.thread.running ? h("span.dash-status.run", {}, h("i"), "Working") : h("span.dash-status", {}, "Idle"));
      const title = root.querySelector(".dash-head h1");
      if (title) title.textContent = S.thread.session?.title || "New thread";
      if (stick || near) scrollThread();
    });
  }
  function scrollThread(instant) {
    requestAnimationFrame(() => { const sc = root.querySelector(".dash-scroll"); if (sc) sc.scrollTo({ top: sc.scrollHeight, behavior: instant ? "auto" : "smooth" }); });
  }

  function messages(th) {
    const out = [];
    const shown = th.msgs.filter((m) => m.type === "user" || m.type === "assistant" || String(m.text || "").length);
    if (!shown.length && !th.running) out.push(h("p.dash-muted.center.pad", {}, "No messages yet. Say what you want AFH to do."));
    for (const m of shown) {
      if (m.type === "user") {
        const files = (m.files || []).map((f) => f.name || base(f.uri || ""));
        out.push(h("div.msg-user", {}, h("div.msg-bubble", {}, m.text || ""), files.length ? h("div.msg-files", {}, files.map((f) => h("span", {}, icon("file", 13), f))) : null));
        continue;
      }
      if (m.type !== "assistant") { out.push(h("p.msg-note", {}, m.text || m.metadata?.label || "")); continue; }
      const wrap = h("div.msg-ai" + (m.live ? ".live" : ""));
      let group = [];
      const flush = () => { if (group.length) { wrap.append(toolGroup(group, th)); group = []; } };
      for (const p of m.content || []) {
        if (p.type === "tool") { group.push(p); continue; }
        flush();
        const text = String(p.text || "");
        if (p.type === "text" && text) wrap.append(h("div.md" + (p.live ? ".live" : ""), { html: md(text) }));
        else if (p.type === "reasoning" && text.trim()) {
          const key = `r:${m.id}:${p.ordinal}`;
          const det = h("details.msg-think", { open: th.open.has(key) || (p.live && th.running) }, h("summary", {}, p.live && th.running ? "Thinking…" : "Thought"), h("div.md", { html: md(text) }));
          remember(det, key, th, p.live && th.running && !th.open.has(key));
          wrap.append(det);
        }
      }
      flush();
      if (m.error) wrap.append(h("div.msg-error", {}, String(m.error)));
      if (m.model && !m.live) wrap.append(h("div.msg-meta", {}, String(typeof m.model === "object" ? m.model.id || m.model.modelID || "" : m.model)));
      out.push(wrap);
    }
    if (th.running) {
      const last = shown[shown.length - 1];
      const streaming = last?.type === "assistant" && (last.content || []).some((p) => p.live && p.type === "text" && p.text);
      if (!streaming) out.push(h("div.msg-typing", { "aria-label": "Working" }, h("i"), h("i"), h("i")));
    }
    if (th.runError) out.push(h("div.msg-error", {}, th.runError));
    return out;
  }

  // keep what the user opened open across repaints (a section opened only while it is live doesn't count)
  function remember(det, key, th, auto) {
    let skip = !!auto;  // opening it ourselves fires one toggle too
    det.addEventListener("toggle", () => {
      if (skip) { skip = false; return; }
      det.open ? th.open.add(key) : th.open.delete(key);
    });
  }

  const VERBS = {
    read: ["Read", "Reading"], write: ["Wrote", "Writing"], edit: ["Edited", "Editing"], multiedit: ["Edited", "Editing"], patch: ["Patched", "Patching"], apply_patch: ["Patched", "Patching"],
    shell: ["Ran", "Running"], bash: ["Ran", "Running"], grep: ["Searched", "Searching"], glob: ["Found files", "Finding files"], list: ["Listed", "Listing"], ls: ["Listed", "Listing"],
    webfetch: ["Fetched", "Fetching"], websearch: ["Searched the web", "Searching the web"], browser: ["Used the browser", "Using the browser"], task: ["Delegated", "Delegating"],
    todowrite: ["Updated the plan", "Planning"], question: ["Asked", "Asking"], memory: ["Remembered", "Remembering"],
  };
  const pick = (o, keys) => { for (const k of keys) if (o && typeof o[k] === "string" && o[k]) return o[k]; return ""; };

  function toolLook(p) {
    const name = String(p.name || "").toLowerCase();
    const st = p.state || {};
    const input = st.input && typeof st.input === "object" ? st.input : {};
    const done = st.status === "completed" || st.status === "error";
    const v = VERBS[name] || [name.replace(/_/g, " ") || "Tool", name.replace(/_/g, " ") || "Working"];
    let ic = "tool", target = pick(input, ["path", "filePath", "file_path", "file"]), isPath = !!target, mono = true;
    if (/^(write|edit|multiedit|patch|apply_patch)$/.test(name)) ic = "edit";
    else if (name === "read") ic = "file";
    else if (/^(shell|bash|exec|execute|command)$/.test(name)) { ic = "term"; target = pick(input, ["command", "cmd", "code"]); isPath = false; }
    else if (/^(grep|glob|search|find|list|ls)$/.test(name)) { ic = "search"; target = pick(input, ["pattern", "query", "path"]); }
    else if (name === "browser") { ic = "globe"; target = pick(input, ["url", "action"]); isPath = false; }
    else if (/web|fetch/.test(name)) { ic = "globe"; target = pick(input, ["url", "query"]); isPath = false; mono = target.startsWith("http"); }
    else if (/task|agent|delegate/.test(name)) { ic = "bot"; target = pick(input, ["description", "prompt"]); isPath = false; mono = false; }
    else if (name === "question") { ic = "q"; target = (input.questions?.[0]?.question) || ""; isPath = false; mono = false; }
    else if (/todo|plan|goal/.test(name)) { ic = "list"; target = pick(input, ["objective", "goal"]); isPath = false; mono = false; }
    if (isPath && !target.includes(" ")) target = base(target);
    target = target.split("\n")[0].slice(0, 140);
    return { ic, verb: done ? v[0] : v[1], target, mono, status: st.status || "pending" };
  }

  const toolText = (c) => {
    if (c == null) return "";
    if (typeof c === "string") return c;
    if (Array.isArray(c)) return c.map((x) => (typeof x === "string" ? x : x?.text || (x?.type === "image" ? "[image]" : ""))).filter(Boolean).join("\n");
    if (typeof c === "object") return JSON.stringify(c, null, 2);
    return String(c);
  };
  const clip = (s, n = 4000) => (s.length > n ? s.slice(0, n) + `\n… ${s.length - n} more characters` : s);

  function toolGroup(tools, th) {
    const rows = tools.map((p) => {
      const L = toolLook(p);
      const st = p.state || {};
      const key = "t:" + p.id;
      const input = st.input && typeof st.input === "object" ? st.input : {};
      const cmd = pick(input, ["command", "cmd"]);
      const out = clip(toolText(st.error?.message || st.error || st.content || st.output || ""));
      const det = h("details.tool" + (L.status === "error" ? ".bad" : ["running", "pending"].includes(L.status) ? ".busy" : ""), { open: th.open.has(key) },
        h("summary", {}, icon(L.ic, 15), h("span.tool-verb", {}, L.verb), L.target ? h("span.tool-target" + (L.mono ? ".mono" : ""), {}, L.target) : null,
          ["running", "pending"].includes(L.status) ? h("span.tool-spin") : null),
        h("div.tool-body", {},
          cmd ? h("pre", {}, "$ " + cmd) : Object.keys(input).length ? h("pre", {}, clip(JSON.stringify(input, null, 2), 1500)) : null,
          out ? h("pre.tool-out", {}, out) : null));
      remember(det, key, th);
      return det;
    });
    if (tools.length <= 2) return h("div.tools", {}, rows);
    const key = "g:" + tools[0].id;
    const busy = tools.some((p) => ["running", "pending"].includes(p.state?.status));
    const failed = tools.filter((p) => p.state?.status === "error").length;
    const det = h("details.tools.group", { open: th.open.has(key) || busy },
      h("summary", {}, icon("list", 15), h("span.tool-verb", {}, `${tools.length} steps`), failed ? h("span.tool-target", {}, `${failed} failed`) : null, busy ? h("span.tool-spin") : null),
      rows);
    remember(det, key, th, busy && !th.open.has(key));
    return det;
  }

  function permCard(req, more) {
    const mdata = req.metadata || {};
    const moreNote = more > 0 ? h("p.perm-more", {}, `+${more} more waiting`) : null;
    if (req.action === "question") {
      const qs = (mdata.questions || []).filter((q) => q && typeof q === "object");
      const picks = qs.map(() => new Set());
      const others = qs.map(() => h("input.perm-other", { placeholder: "Or type your own answer" }));
      const card = h("div.dash-perm.q", { "data-id": String(req.id) },
        h("div.perm-head", {}, icon("q", 18), h("b", {}, "AFH has a question")),
        h("div.perm-qs", {}, qs.map((q, i) => h("div.perm-q", {},
          q.header ? h("p.perm-label", {}, q.header) : null,
          h("p.perm-text", {}, q.question || ""),
          h("div.perm-opts", {}, (q.options || []).map((o) => {
            const b = h("button.perm-opt", { type: "button" }, h("b", {}, o.label), o.description ? h("span", {}, o.description) : null);
            b.addEventListener("click", () => {
              if (!q.multiple) { const had = picks[i].has(o.label); picks[i].clear(); card.querySelectorAll(`.perm-q:nth-child(${i + 1}) .perm-opt`).forEach((x) => x.classList.remove("on")); if (!had) { picks[i].add(o.label); b.classList.add("on"); } }
              else { picks[i].has(o.label) ? picks[i].delete(o.label) : picks[i].add(o.label); b.classList.toggle("on"); }
            });
            return b;
          })),
          others[i]))),
        h("div.perm-actions", {},
          h("button.btn.btn-primary.btn-small", { type: "button", async onclick(e) { e.target.disabled = true; if (!(await answer(req, { decision: "answer", answers: qs.map((_, i) => ({ selected: [...picks[i]], other: others[i].value })) }))) e.target.disabled = false; } }, "Send answer"),
          h("button.btn.btn-ghost.btn-small", { type: "button", onclick: () => answer(req, { decision: "dismiss" }) }, "Skip")),
        moreNote);
      return card;
    }
    const files = (mdata.files || []).filter((f) => f && typeof f === "object");
    const resources = (req.resources || []).map(String);
    const cmd = mdata.command != null ? String(mdata.command) : "";
    const btn = (label, decision, cls) => h(`button.btn.btn-small.${cls}`, {
      type: "button",
      async onclick(e) { const all = e.target.closest(".perm-actions").querySelectorAll("button"); all.forEach((b) => (b.disabled = true)); if (!(await answer(req, { decision }))) all.forEach((b) => (b.disabled = false)); },
    }, label);
    return h("div.dash-perm", { "data-id": String(req.id) },
      h("div.perm-head", {}, icon("tool", 18), h("b", {}, mdata.title || req.action || "AFH wants to continue")),
      cmd ? h("pre.perm-code", {}, cmd) : null,
      files.length ? h("ul.perm-files", {}, files.slice(0, 8).map((f) => h("li", {}, h("span.perm-fs", {}, f.status || "modified"), h("span.mono", {}, f.path || f.file || "")))) : null,
      !cmd && !files.length && resources.length ? h("pre.perm-code", {}, resources.slice(0, 8).join("\n")) : null,
      h("div.perm-actions", {}, btn("Allow", "once", "btn-primary"), btn("Always allow", "always", "btn-ghost"), btn("Deny", "reject", "btn-ghost.perm-deny")),
      moreNote);
  }

  // ---- computers and account ----

  function computersView() {
    const list = S.me.computers;
    const rows = list.map((c) => {
      const msg = h("p.dash-msg", { hidden: true });
      let confirming = false;
      const rename = h("button.btn.btn-ghost.btn-small", { type: "button" }, "Rename");
      const remove = h("button.btn.btn-ghost.btn-small.perm-deny", { type: "button" }, "Remove");
      const row = h("div.dash-pcrow" + (c.online ? ".up" : ""), {},
        h("i.dot"),
        h("div.dash-pcrow-main", {}, h("b", {}, c.name), h("span", {}, c.online ? "Online" : `Offline · ${seen(c.lastSeen)}`, c.version ? ` · AFH ${c.version}` : "")),
        h("div.dash-pcrow-actions", {},
          c.online ? h("a.btn.btn-primary.btn-small", { href: `#/c/${encodeURIComponent(c.id)}` }, "Chat") : null,
          c.online ? h("a.btn.btn-ghost.btn-small", { href: `/r/${encodeURIComponent(c.id)}/`, target: "_blank", rel: "noopener" }, "Open full AFH") : null,
          rename, remove),
        msg);
      remove.addEventListener("click", async () => {
        if (!confirming) { confirming = true; remove.textContent = "Click again to remove"; return; }
        try { await account("DELETE", `computers/${c.id}`); await loadMe(); toast(`${c.name} removed`); if (S.cid === c.id) S.cid = null; render(); }
        catch (x) { msg.textContent = x.message; msg.hidden = false; }
      });
      rename.addEventListener("click", () => {
        const input = h("input.dash-field", { value: c.name, maxlength: "60", "aria-label": "Computer name" });
        const save = async () => {
          try { await account("PATCH", `computers/${c.id}`, { name: input.value }); await loadMe(); render(); }
          catch (x) { msg.textContent = x.message; msg.hidden = false; }
        };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); if (e.key === "Escape") render(); });
        row.querySelector(".dash-pcrow-main").replaceChildren(input);
        row.querySelector(".dash-pcrow-actions").replaceChildren(h("button.btn.btn-primary.btn-small", { type: "button", onclick: save }, "Save"), h("button.btn.btn-ghost.btn-small", { type: "button", onclick: render }, "Cancel"));
        input.focus();
        input.select();
      });
      return row;
    });
    return h("section.dash-main.dash-page", {},
      backBar("Computers", `${list.filter((c) => c.online).length} of ${list.length} online`),
      h("div.dash-pagebody", {},
        list.length ? h("div.dash-card", {}, rows) : null,
        h("div.dash-card", {},
          h("h2", {}, "Add a computer"),
          h("ol.dash-steps", {},
            h("li", {}, h("a", { href: "/download" }, "Download AFH"), " for Windows and open it."),
            h("li", {}, "Go to ", h("b", {}, "Settings → Remote control"), " and choose ", h("b", {}, "Sign in with your browser"), "."),
            h("li", {}, "Approve it on the page that opens — it shows up here in a few seconds."))),
        h("div.dash-card", {},
          h("h2", {}, "On your phone"),
          h("p", {}, "The AFH app for Android and iPhone signs in with this account too — chat with any model and reach these computers from anywhere."),
          h("div.cta-row", {}, h("a.btn.btn-primary.btn-small", { href: "/download#phone" }, "Get the app")))));
  }

  function accountView() {
    const say = (box, text, ok) => { box.textContent = text; box.className = "dash-msg " + (ok ? "ok" : "bad"); box.hidden = false; };
    const pwMsg = h("p.dash-msg", { hidden: true });
    const old = h("input.dash-field", { type: "password", autocomplete: "current-password", placeholder: "Current password" });
    const fresh = h("input.dash-field", { type: "password", autocomplete: "new-password", minlength: "8", placeholder: "New password (8+ characters)" });
    const delMsg = h("p.dash-msg", { hidden: true });
    const delPw = h("input.dash-field", { type: "password", autocomplete: "current-password", placeholder: "Your password" });
    let armed = false;
    return h("section.dash-main.dash-page", {},
      backBar("Account", S.me.user.email),
      h("div.dash-pagebody", {},
        h("div.dash-card.dash-who", {},
          h("span.nav-avatar.big", {}, (S.me.user.email[0] || "A").toUpperCase()),
          h("div", {}, h("b", {}, S.me.user.email), h("span", {}, `${S.me.computers.length} computer${S.me.computers.length === 1 ? "" : "s"} on this account`)),
          h("button.btn.btn-ghost.btn-small", { type: "button", async onclick() { await account("POST", "signout").catch(() => {}); location.href = "/account"; } }, "Sign out")),
        h("form.dash-card", {
          async onsubmit(e) {
            e.preventDefault();
            if (fresh.value.length < 8) return say(pwMsg, "Use a new password of at least 8 characters.");
            try { await account("POST", "password", { old: old.value, new: fresh.value }); old.value = fresh.value = ""; say(pwMsg, "Password changed. Your other sign-ins (phones, other browsers) were signed out.", true); }
            catch (x) { say(pwMsg, x.message); }
          },
        },
          h("h2", {}, "Change password"),
          h("div.dash-form", {}, old, fresh),
          pwMsg,
          h("div.cta-row", {}, h("button.btn.btn-ghost.btn-small", { type: "submit" }, "Change password"))),
        h("div.dash-card.dash-danger", {},
          h("h2", {}, "Delete account"),
          h("p", {}, "Deletes the account and disconnects every computer. Nothing on your computers is touched."),
          h("div.dash-form.inline", {}, delPw, h("button.btn.btn-ghost.btn-small.perm-deny", {
            type: "button",
            async onclick(e) {
              if (!armed) { armed = true; e.target.textContent = "Click again to delete for good"; return; }
              try { await account("POST", "account/delete", { password: delPw.value }); location.href = "/"; }
              catch (x) { say(delMsg, x.message); }
            },
          }, "Delete my account")),
          delMsg)));
  }

  // ---- start ------------------------------------------------------------------------------------

  async function start() {
    try {
      await loadMe();
    } catch (x) {
      if (x.status === 401) return;  // call() already sent us to sign in
      root.replaceChildren(h("div.dash-state.full", {}, h("b", {}, "Can't reach the account server"), h("p", {}, x.message),
        h("button.btn.btn-ghost.btn-small", { type: "button", onclick: () => location.reload() }, "Try again")));
      return;
    }
    addEventListener("hashchange", route);
    let wasWide = isWide();
    addEventListener("resize", () => { if (isWide() !== wasWide) { wasWide = isWide(); render(); } });
    route();
    // who's online changes: check now and then, and reconnect a computer that came back
    setInterval(async () => {
      if (document.hidden) return;
      const before = new Map(S.me.computers.map((c) => [c.id, c.online]));
      try { await loadMe(); } catch { return; }
      const changed = S.me.computers.some((c) => before.get(c.id) !== c.online) || before.size !== S.me.computers.length;
      if (!changed) return;
      if (S.cid && computer(S.cid)?.online && !before.get(S.cid)) { S.esCid = null; connect(S.cid); loadSessions(S.cid); }
      if (S.cid && !computer(S.cid)?.online) { S.es?.close(); S.es = null; S.live = "off"; }
      if (S.route.view !== "thread" || !root.querySelector(".dash-input:focus")) render();
    }, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && S.cid && S.route.view !== "thread") loadSessions(S.cid); });
  }

  start();
})();
