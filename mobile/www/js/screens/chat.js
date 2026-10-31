// A thread: the conversation with live replies, what the agent did, approvals and questions, and
// a composer to send the next message or stop the run.
import { computer } from "../api.js";
import { baseName, h, icon, markdown, toast, fill } from "../ui.js";

const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] != null && o[k] !== "") return o[k];
  return null;
};

const VERBS = {
  write: ["Wrote", "Writing"], edit: ["Edited", "Editing"], multiedit: ["Edited", "Editing"], patch: ["Patched", "Patching"], apply_patch: ["Patched", "Patching"],
  shell: ["Ran", "Running"], bash: ["Ran", "Running"], execute: ["Ran code", "Running code"], read: ["Read", "Reading"], glob: ["Found files", "Finding files"],
  grep: ["Searched", "Searching"], list: ["Listed", "Listing"], ls: ["Listed", "Listing"], webfetch: ["Fetched", "Fetching"], websearch: ["Searched the web", "Searching the web"],
  skill: ["Loaded skill", "Loading skill"], question: ["Asked", "Asking"], todowrite: ["Planned", "Planning"], todoread: ["Checked plan", "Checking plan"],
  memory: ["Updated memory", "Updating memory"], task: ["Delegated", "Delegating"], browser: ["Used the browser", "Using the browser"], goal: ["Set the goal", "Setting the goal"],
};

function toolLook(p) {
  const name = String(p.name || "").toLowerCase();
  const input = typeof p.state?.input === "object" && p.state.input ? p.state.input : {};
  const done = p.state?.status === "completed" || p.state?.status === "error";
  const verb = (VERBS[name] || [name.replace(/_/g, " ") || "Tool", name || "Working"])[done ? 0 : 1];
  let ico = "construct-outline";
  let target = pick(input, "path", "filePath", "file_path", "file") || "";
  if (/^(write|edit|multiedit|patch|apply_patch)$/.test(name)) ico = "create-outline";
  else if (name === "read") ico = "document-text-outline";
  else if (/^(shell|bash|exec|execute|command)$/.test(name)) { ico = "terminal-outline"; target = pick(input, "command", "cmd", "code") || ""; }
  else if (/^(grep|glob|search|find|list|ls)$/.test(name)) { ico = "search-outline"; target = pick(input, "pattern", "query", "path") || ""; }
  else if (name === "browser") { ico = "browsers-outline"; target = pick(input, "url", "action") || ""; }
  else if (/web|fetch/.test(name)) { ico = "globe-outline"; target = pick(input, "url", "query") || ""; }
  else if (/task|agent|delegate/.test(name)) { ico = "people-outline"; target = pick(input, "description", "prompt") || ""; }
  else if (name === "question") { ico = "help-circle-outline"; target = pick((input.questions || [])[0] || {}, "question") || ""; }
  else if (/todo|plan|goal/.test(name)) { ico = "list-outline"; target = pick(input, "objective", "goal") || ""; }
  else if (/memory|skill/.test(name)) ico = "bookmark-outline";
  if (target && /path|file/.test(Object.keys(input).join(" ")) && !/\s/.test(target)) target = baseName(target);
  return { ico, verb, target: String(target).split("\n")[0].slice(0, 140) };
}

function toolText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => (typeof c === "string" ? c : c?.text || (c?.type === "image" ? "[image]" : ""))).filter(Boolean).join("\n");
  return typeof content === "object" ? JSON.stringify(content, null, 2) : String(content);
}

const clip = (s, n = 4000) => (s.length > n ? s.slice(0, n) + `\n… ${s.length - n} more characters` : s);

customElements.define("afh-chat", class extends HTMLElement {
  connectedCallback() {
    if (this.built) return;
    this.built = true;
    this.pc = computer(this.computer.id);
    this.sid = this.session.id;
    this.msgs = [];
    this.perms = new Map();
    this.running = !!this.session.running;
    this.nodes = new Map();
    this.open = new Set(); // tool groups / tools the user expanded
    this.stick = true;

    this.titleEl = h("div.chat-title", this.session.title || "New thread");
    this.subEl = h("div.chat-sub", this.subtitle());
    this.list = h("div.msgs");
    this.working = h("div.working-row", h("span.typing", h("i"), h("i"), h("i")), h("span", "AFH is working"));
    this.content = h("ion-content.chat", { "scroll-events": true, on: { ionScroll: () => this.trackScroll() } },
      h("div.msgs-wrap", this.list, this.working));
    this.permBox = h("div.perm-box");
    this.input = h("ion-textarea.composer-input", { placeholder: "Message AFH…", rows: "1", "auto-grow": true, props: { maxlength: 20000 }, on: { ionInput: () => this.drawComposer() } });
    this.sendBtn = h("button.send", { "aria-label": "Send", on: { click: () => this.send() } }, icon("arrow-up"));
    this.stopBtn = h("button.stop", { "aria-label": "Stop", on: { click: () => this.stop() } }, icon("stop"));
    this.liveBadge = h("span.live-badge");
    this.append(
      h("ion-header", { translucent: true },
        h("ion-toolbar",
          h("ion-buttons", { slot: "start" }, h("ion-back-button", { "default-href": "#", text: "" })),
          h("div.chat-head", this.titleEl, this.subEl),
          h("ion-buttons", { slot: "end" }, this.liveBadge))),
      this.content,
      h("ion-footer.composer-foot",
        this.permBox,
        h("div.composer", this.input, this.stopBtn, this.sendBtn)));

    this.addEventListener("ionViewDidEnter", () => {
      this.load(true);
      this.live = this.pc.events((ev) => this.onEvent(ev), (st) => { this.liveBadge.className = "live-badge " + st; if (st === "live" && this.loaded) this.load(); });
    });
    this.addEventListener("ionViewWillLeave", () => { this.live?.stop(); this.input.getInputElement?.().then((el) => el.blur()); });
    this.drawComposer();
  }

  subtitle() {
    const s = this.session;
    const proj = s.project || s.location?.directory;
    const model = s.model?.id || s.model?.modelID || "";
    return [this.computer.name, proj ? baseName(proj) : "", model].filter(Boolean).join(" · ");
  }

  async load(first) {
    try {
      const [session, msgs, perms] = await Promise.all([
        this.pc.get(`/api/sessions/${this.sid}`),
        this.pc.get(`/api/sessions/${this.sid}/messages`),
        this.pc.get(`/api/sessions/${this.sid}/permissions`).catch(() => []),
      ]);
      this.session = session;
      this.running = !!session.running;
      this.msgs = msgs || [];
      this.perms = new Map((perms || []).map((p) => [p.id, p]));
      this.loaded = true;
      this.titleEl.textContent = session.title || "New thread";
      this.subEl.textContent = this.subtitle();
      this.renderAll();
      if (first) requestAnimationFrame(() => this.content.scrollToBottom(0));
    } catch (x) {
      if (!this.loaded) fill(this.list, h("div.empty.small", h("div.empty-art.muted", icon(x.status === 503 ? "moon-outline" : "alert-circle-outline")),
        h("h2", x.status === 503 ? `${this.computer.name} is offline` : "Couldn't open this thread"), h("p", x.message),
        h("ion-button", { fill: "outline", shape: "round", on: { click: () => this.load(true) } }, "Try again")));
      else toast(x.message, "danger");
    }
  }

  // ---- live events (the same stream the desktop app uses) ----

  onEvent(ev) {
    const d = ev.data || {};
    if (d.sessionID !== this.sid) return;
    const t = ev.type;
    const asst = (id, extra) => {
      let m = this.msgs.find((x) => x.id === id);
      if (!m) {
        m = { id, type: "assistant", content: [], live: true, time: { created: Date.now() }, agent: extra?.agent, model: extra?.model };
        this.msgs.push(m);
      }
      return m;
    };
    const part = (m, type, ordinal) => {
      let p = m.content.find((c) => c.type === type && c.ordinal === ordinal);
      if (!p) { p = { type, ordinal, text: "", live: true }; m.content.push(p); }
      return p;
    };
    const tool = (m, id, name) => {
      let p = m.content.find((c) => c.type === "tool" && c.id === id);
      if (!p) { p = { type: "tool", id, name, state: { status: "pending", input: "" } }; m.content.push(p); }
      return p;
    };
    switch (t) {
      case "session.execution.started":
        this.running = true;
        this.error = null;
        break;
      case "session.execution.succeeded":
      case "session.execution.interrupted":
      case "session.execution.failed":
        this.running = false;
        if (t.endsWith("failed")) this.error = d.error?.message || "The run failed";
        for (const m of this.msgs) { m.live = false; for (const p of m.content || []) p.live = false; }
        setTimeout(() => this.load(), 300);
        break;
      case "session.inbox.delivered":
      case "session.notice":
      case "session.compaction.ended":
      case "session.updated":
        clearTimeout(this.soon);
        this.soon = setTimeout(() => this.load(), 250);
        return;
      case "session.renamed":
        this.session.title = d.title;
        this.titleEl.textContent = d.title || "New thread";
        return;
      case "session.step.started":
        asst(d.assistantMessageID, d);
        break;
      case "session.step.failed": {
        const m = asst(d.assistantMessageID);
        if (!/interrupt|abort|cancel/i.test(`${d.error?.type || ""} ${d.error?.message || ""}`)) m.error = d.error?.message;
        return this.renderMsg(m);
      }
      case "session.text.started":
      case "session.reasoning.started":
        part(asst(d.assistantMessageID), t.includes("reasoning") ? "reasoning" : "text", d.ordinal);
        return this.renderMsg(asst(d.assistantMessageID));
      case "session.text.delta":
      case "session.reasoning.delta": {
        const m = asst(d.assistantMessageID);
        part(m, t.includes("reasoning") ? "reasoning" : "text", d.ordinal).text += d.delta || "";
        return this.renderSoon(m);
      }
      case "session.text.ended":
      case "session.reasoning.ended": {
        const m = asst(d.assistantMessageID);
        const p = part(m, t.includes("reasoning") ? "reasoning" : "text", d.ordinal);
        if (d.text != null) p.text = d.text;
        p.live = false;
        return this.renderMsg(m);
      }
      case "session.tool.input.started":
        tool(asst(d.assistantMessageID), d.id, d.name);
        return this.renderMsg(asst(d.assistantMessageID));
      case "session.tool.called": {
        const m = asst(d.assistantMessageID);
        const p = tool(m, d.id, d.name);
        p.name = d.name || p.name;
        p.state = { status: "running", input: d.input || {}, metadata: {} };
        return this.renderMsg(m);
      }
      case "session.tool.success":
      case "session.tool.failed": {
        const m = asst(d.assistantMessageID);
        const p = tool(m, d.id);
        const input = typeof p.state.input === "object" ? p.state.input : {};
        p.state = t.endsWith("success") ? { status: "completed", input, content: d.content, metadata: d.metadata } : { status: "error", input, error: d.error, content: d.content };
        return this.renderMsg(m);
      }
      case "permission.asked":
        this.perms.set(d.id, d);
        this.drawPerms();
        if (navigator.vibrate) navigator.vibrate(30);
        return;
      case "permission.replied":
        this.perms.delete(d.id || d.permissionID || d.requestID);
        this.drawPerms();
        return;
      default:
        return;
    }
    this.drawStatus();
  }

  renderSoon(m) {
    (this.pending ||= new Set()).add(m);
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      for (const x of this.pending) this.renderMsg(x);
      this.pending.clear();
    });
  }

  // ---- drawing ----

  renderAll() {
    this.nodes.clear();
    const shown = this.msgs.filter((m) => m.type === "user" || m.type === "assistant" || m.text || m.metadata?.label);
    fill(this.list, ...shown.map((m) => this.msgNode(m)));
    if (!shown.length) this.list.append(h("div.empty.small", h("div.empty-art", icon("sparkles-outline")), h("h2", "A fresh thread"), h("p", "Send the first message below.")));
    this.drawStatus();
    this.drawPerms();
  }

  renderMsg(m) {
    const old = this.nodes.get(m.id);
    const node = this.msgNode(m);
    if (old?.isConnected) old.replaceWith(node);
    else { this.list.querySelector(".empty")?.remove(); this.list.append(node); }
    this.drawStatus();
    this.follow();
  }

  msgNode(m) {
    let node;
    if (m.type === "user") {
      const files = (m.files || []).length;
      node = h("div.msg.user", h("div.bubble", h("div.user-text", String(m.text || "")), files ? h("div.files", icon("attach"), `${files} file${files > 1 ? "s" : ""}`) : null));
    } else if (m.type === "assistant") {
      node = h("div.msg.ai", this.partsNodes(m), m.error ? h("div.msg-error", icon("alert-circle-outline"), m.error) : null);
    } else {
      node = h("div.msg.note", String(m.text || m.metadata?.label || ""));
    }
    this.nodes.set(m.id, node);
    return node;
  }

  partsNodes(m) {
    const out = [];
    let group = [];
    const flush = () => {
      if (!group.length) return;
      out.push(this.toolGroup(m, group));
      group = [];
    };
    for (const p of m.content || []) {
      if (p.type === "tool") { group.push(p); continue; }
      flush();
      if (p.type === "text" && p.text) out.push(h("div.md" + (p.live ? ".live" : ""), { html: markdown(p.text) }));
      else if (p.type === "reasoning" && p.text?.trim()) {
        const key = `r:${m.id}:${p.ordinal}`;
        const box = h("div.thinking" + (this.open.has(key) ? ".open" : ""),
          h("button.thinking-head", { on: { click: () => { box.classList.toggle("open"); this.open[box.classList.contains("open") ? "add" : "delete"](key); } } },
            icon("bulb-outline"), h("span", p.live ? "Thinking…" : "Thought"), icon("chevron-down", { class: "chev" })),
          h("div.thinking-body", p.text));
        out.push(box);
      }
    }
    flush();
    return out;
  }

  toolGroup(m, tools) {
    const key = `g:${m.id}:${tools[0].id}`;
    const busy = tools.some((p) => p.state?.status === "running" || p.state?.status === "pending");
    const failed = tools.filter((p) => p.state?.status === "error").length;
    const collapsible = tools.length > 2;
    const expanded = !collapsible || busy || this.open.has(key);
    const rows = h("div.tool-rows", tools.map((p) => this.toolRow(p)));
    const box = h("div.tools" + (expanded ? ".open" : ""), collapsible ? h("button.tools-head", {
      on: { click: () => { box.classList.toggle("open"); this.open[box.classList.contains("open") ? "add" : "delete"](key); } },
    }, icon(busy ? "sync-outline" : "checkmark-done-outline", { class: busy ? "spin" : "" }), h("span", busy ? `Working · ${tools.length} steps` : `${tools.length} steps${failed ? ` · ${failed} failed` : ""}`), icon("chevron-down", { class: "chev" })) : null, rows);
    return box;
  }

  toolRow(p) {
    const look = toolLook(p);
    const st = p.state?.status || "pending";
    const input = typeof p.state?.input === "object" && p.state.input ? p.state.input : {};
    const key = `t:${p.id}`;
    const cmd = pick(input, "command", "cmd", "code");
    const out = p.state?.error ? toolText(p.state.error.message || p.state.error) : toolText(p.state?.content);
    const row = h(`div.tool.${st}` + (this.open.has(key) ? ".open" : ""),
      h("button.tool-head", { on: { click: () => { row.classList.toggle("open"); this.open[row.classList.contains("open") ? "add" : "delete"](key); } } },
        icon(look.ico, { class: "tool-ico" }),
        h("span.tool-verb", look.verb),
        h("span.tool-target", look.target),
        st === "running" || st === "pending" ? h("ion-spinner", { name: "crescent" }) : icon(st === "error" ? "close-circle" : "checkmark-circle", { class: "tool-st" })),
      h("div.tool-body",
        cmd ? h("pre.code", clip(String(cmd), 2000)) : Object.keys(input).length ? h("pre.code", clip(JSON.stringify(input, null, 2), 2000)) : null,
        out ? h("pre.code.out" + (st === "error" ? ".bad" : ""), clip(out)) : null));
    return row;
  }

  drawStatus() {
    const last = this.msgs[this.msgs.length - 1];
    const streaming = last?.type === "assistant" && (last.content || []).some((p) => p.live && p.type === "text" && p.text);
    this.working.hidden = !this.running || streaming;
    this.list.querySelector(".run-error")?.remove();
    if (this.error && !this.running) this.list.append(h("div.msg-error.run-error", icon("alert-circle-outline"), this.error));
    this.drawComposer();
  }

  drawComposer() {
    this.stopBtn.hidden = !this.running;
    const has = !!String(this.input.value || "").trim();
    this.sendBtn.disabled = !has;
    this.input.placeholder = this.running ? "Add to the run…" : "Message AFH…";
  }

  trackScroll() {
    clearTimeout(this.scrollT);
    this.scrollT = setTimeout(async () => {
      const el = await this.content.getScrollElement();
      this.stick = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
    }, 60);
  }

  follow() {
    if (this.stick) this.content.scrollToBottom(0);
  }

  // ---- approvals and questions ----

  drawPerms() {
    const reqs = [...this.perms.values()];
    if (!reqs.length) { fill(this.permBox); return; }
    const r = reqs[0];
    fill(this.permBox, r.action === "question" ? this.questionCard(r) : this.approvalCard(r), reqs.length > 1 ? h("p.perm-more", `+${reqs.length - 1} more waiting`) : null);
    this.follow();
  }

  async answer(r, body, btns) {
    btns.forEach((b) => { b.disabled = true; });
    try {
      await this.pc.post(`/api/sessions/${this.sid}/permissions/${r.id}`, body);
      this.perms.delete(r.id);
      this.drawPerms();
    } catch (x) {
      toast(x.message, "danger", 4000);
      btns.forEach((b) => { b.disabled = false; });
    }
  }

  approvalCard(r) {
    const md = r.metadata || {};
    const files = md.files || [];
    const btns = [];
    const btn = (label, cls, decision) => { const b = h(`button.perm-btn.${cls}`, label); btns.push(b); b.addEventListener("click", () => this.answer(r, { decision }, btns)); return b; };
    return h("div.perm-card",
      h("div.perm-head", h("div.perm-ico", icon("shield-checkmark-outline")), h("div", h("b", "Approval needed"), h("span", md.title || r.action || "The agent wants to continue"))),
      md.command ? h("pre.code", clip(String(md.command), 1500)) : null,
      files.length ? h("div.perm-files", files.slice(0, 6).map((f) => h("details.perm-file", h("summary", h("span.fstat." + (f.status || "modified"), (f.status || "modified")[0].toUpperCase()), baseName(f.file)),
        f.patch ? h("pre.code.diff", clip(String(f.patch), 3000)) : null)), files.length > 6 ? h("p.muted", `+${files.length - 6} more files`) : null) : null,
      !md.command && !files.length && (r.resources || []).length ? h("pre.code", (r.resources || []).slice(0, 8).join("\n")) : null,
      h("div.perm-actions", btn("Reject", "no", "reject"), btn("Always", "ghost", "always"), btn("Allow", "yes", "once")));
  }

  questionCard(r) {
    const qs = r.metadata?.questions || [];
    const picks = qs.map(() => new Set());
    const others = qs.map(() => "");
    const btns = [];
    const send = h("button.perm-btn.yes", "Send answer");
    const skip = h("button.perm-btn.ghost", "Skip");
    btns.push(send, skip);
    send.addEventListener("click", () => this.answer(r, { decision: "answer", answers: qs.map((_, i) => ({ selected: [...picks[i]], other: others[i] })) }, btns));
    skip.addEventListener("click", () => this.answer(r, { decision: "dismiss" }, btns));
    return h("div.perm-card.question",
      h("div.perm-head", h("div.perm-ico", icon("help-circle-outline")), h("div", h("b", "AFH has a question"), h("span", qs.length > 1 ? `${qs.length} questions` : "Pick an answer"))),
      qs.map((q, i) => h("div.q",
        q.header ? h("p.q-head", q.header) : null,
        h("p.q-text", q.question || ""),
        h("div.q-opts", (q.options || []).map((o) => {
          const b = h("button.q-opt", h("b", o.label), o.description ? h("span", o.description) : null);
          b.addEventListener("click", () => {
            if (!q.multiple) { picks[i].clear(); b.parentElement.querySelectorAll(".q-opt").forEach((x) => x.classList.remove("on")); }
            if (picks[i].has(o.label)) { picks[i].delete(o.label); b.classList.remove("on"); } else { picks[i].add(o.label); b.classList.add("on"); }
          });
          return b;
        })),
        h("input.q-other", { placeholder: "Or type your own answer", on: { input: (e) => { others[i] = e.target.value; } } }))),
      h("div.perm-actions", skip, send));
  }

  // ---- sending ----

  async send() {
    const text = String(this.input.value || "").trim();
    if (!text) return;
    this.sendBtn.disabled = true;
    try {
      await this.pc.post(`/api/sessions/${this.sid}/prompt`, { text });
      this.input.value = "";
      this.stick = true;
      this.msgs.push({ id: "local-" + Date.now(), type: "user", text, time: { created: Date.now() } });
      this.running = true;
      this.error = null;
      this.renderAll();
      this.follow();
      setTimeout(() => this.load(), 900);
    } catch (x) {
      toast(x.message, "danger", 4000);
    }
    this.drawComposer();
  }

  async stop() {
    this.stopBtn.disabled = true;
    try { await this.pc.post(`/api/sessions/${this.sid}/interrupt`); } catch (x) { toast(x.message, "danger"); }
    this.stopBtn.disabled = false;
  }
});
