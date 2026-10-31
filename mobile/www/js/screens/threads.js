// One computer: its recent threads across projects, live. Tap a thread to open it, + to start one.
import { computer } from "../api.js";
import { ago, baseName, h, icon, toast, fill } from "../ui.js";
import { nav } from "../nav.js";

customElements.define("afh-threads", class extends HTMLElement {
  connectedCallback() {
    if (this.built) return;
    this.built = true;
    this.pc = computer(this.computer.id);
    this.filter = "";
    this.query = "";
    this.sessions = null;
    this.projects = [];
    this.body = h("div.threads", h("div.skeleton-row"), h("div.skeleton-row"), h("div.skeleton-row"));
    this.chips = h("div.chips");
    this.fab = h("ion-fab", { slot: "fixed", vertical: "bottom", horizontal: "end" },
      h("ion-fab-button.grad-fab", { "aria-label": "New thread", on: { click: () => this.newThread() } }, icon("add")));
    this.fab.hidden = true;
    const search = h("ion-searchbar", { placeholder: "Search threads", debounce: "150", "show-cancel-button": "never", on: { ionInput: (e) => { this.query = String(e.detail.value || "").toLowerCase(); this.draw(); } } });
    this.append(
      h("ion-header", { translucent: true },
        h("ion-toolbar",
          h("ion-buttons", { slot: "start" }, h("ion-back-button", { "default-href": "#", text: "" })),
          h("ion-title", this.computer.name),
          h("ion-buttons", { slot: "end" }, h("ion-button", { "aria-label": "New thread", on: { click: () => this.newThread() } }, icon("create-outline", { slot: "icon-only" })))),
        h("ion-toolbar.sub-toolbar", search)),
      h("ion-content", { fullscreen: true },
        h("ion-refresher", { slot: "fixed", on: { ionRefresh: async (e) => { await this.load(); e.target.complete(); } } }, h("ion-refresher-content")),
        this.chips,
        this.body,
        this.fab));
    this.addEventListener("ionViewDidEnter", () => {
      this.load();
      this.live = this.pc.events((ev) => this.onEvent(ev));
    });
    this.addEventListener("ionViewWillLeave", () => { this.live?.stop(); clearTimeout(this.soon); });
  }

  onEvent(ev) {
    if (!this.sessions) return;
    const t = ev.type || "";
    if (t.startsWith("session.execution.") || t === "session.created" || t === "session.renamed" || t === "permission.asked" || t === "permission.replied") {
      clearTimeout(this.soon);
      this.soon = setTimeout(() => this.load(), 400);
    }
  }

  async load() {
    try {
      if (!this.projects.length) {
        const settings = await this.pc.get("/api/settings");
        this.projects = (settings.projects || []).filter(Boolean);
      }
      let list;
      try {
        list = await this.pc.get("/api/sessions?limit=120");
      } catch (x) {
        if (x.status !== 422) throw x;
        // AFH before 1.9.1 lists one project at a time
        const per = await Promise.all(this.projects.slice(0, 12).map((d) => this.pc.get(`/api/sessions?directory=${encodeURIComponent(d)}`).catch(() => [])));
        list = per.flat().sort((a, b) => (b.time?.updated || 0) - (a.time?.updated || 0));
      }
      this.sessions = list;
      this.error = null;
    } catch (x) {
      this.error = x;
    }
    this.draw();
  }

  projectOf(s) { return s.project || s.location?.directory || ""; }

  draw() {
    if (this.error && !this.sessions) {
      const offline = this.error.status === 503;
      this.fab.hidden = true;
      fill(this.chips);
      fill(this.body, h("div.empty",
        h("div.empty-art" + (offline ? ".muted" : ""), icon(offline ? "moon-outline" : "cloud-offline-outline")),
        h("h2", offline ? `${this.computer.name} is offline` : "Couldn't load threads"),
        h("p", offline ? "Open AFH on that computer and keep it signed in under Settings → Remote control. This screen reconnects by itself." : this.error.message),
        h("ion-button", { fill: "outline", shape: "round", on: { click: () => this.load() } }, icon("refresh", { slot: "start" }), "Try again")));
      clearTimeout(this.retry);
      if (offline) this.retry = setTimeout(() => this.isConnected && this.load(), 8000);
      return;
    }
    if (!this.sessions) return;
    this.fab.hidden = false;
    const used = [...new Set(this.sessions.map((s) => this.projectOf(s)).filter(Boolean))];
    const projects = [...new Set([...used, ...this.projects])];
    fill(this.chips, ...(projects.length > 1 ? [["", "All"], ...projects.map((p) => [p, baseName(p)])] : []).map(([p, label]) =>
      h("button.chip" + (this.filter === p ? ".on" : ""), { on: { click: () => { this.filter = p; this.draw(); } } }, label)));
    const shown = this.sessions.filter((s) => (!this.filter || this.projectOf(s) === this.filter) && (!this.query || (s.title || "").toLowerCase().includes(this.query)));
    if (!shown.length) {
      fill(this.body, h("div.empty.small",
        h("div.empty-art", icon("chatbubbles-outline")),
        h("h2", this.query ? "No matching threads" : "No threads yet"),
        h("p", this.query ? "Try another word." : "Start one with the + button — AFH works on it on your computer.")));
      return;
    }
    const running = shown.filter((s) => s.running);
    const rest = shown.filter((s) => !s.running);
    const row = (s) => h("button.thread" + (s.running ? ".running" : ""), { on: { click: () => nav().push("afh-chat", { computer: this.computer, session: s, projects: this.projects }) } },
      h("div.thread-main",
        h("b", s.title || "New thread"),
        h("span.thread-meta", this.projectOf(s) ? h("span.proj", baseName(this.projectOf(s))) : null, s.running ? h("span.working", h("i.pulse"), "Working") : ago(s.time?.updated))),
      icon("chevron-forward", { class: "chev" }));
    fill(this.body, 
      running.length ? h("p.section-label", "Working now") : null,
      ...running.map(row),
      running.length && rest.length ? h("p.section-label", "Recent") : null,
      ...rest.slice(0, 80).map(row));
  }

  async newThread() {
    const projects = this.projects.length ? this.projects : [...new Set((this.sessions || []).map((s) => this.projectOf(s)).filter(Boolean))];
    if (!projects.length) { toast("Open a project folder in AFH on your computer first.", "warning", 4000); return; }
    let dir = this.filter || projects[0];
    const text = h("ion-textarea.prompt-box", { placeholder: "What should AFH do?", "auto-grow": true, rows: "4", fill: "solid" });
    const pick = h("ion-select", { label: "Project", interface: "action-sheet", value: dir, on: { ionChange: (e) => { dir = e.detail.value; } } },
      projects.map((p) => h("ion-select-option", { value: p }, baseName(p))));
    const start = h("ion-button.grad", { expand: "block", shape: "round" }, icon("arrow-up", { slot: "start" }), "Start");
    const modal = h("ion-modal.sheet", { props: { breakpoints: [0, 0.75, 1], initialBreakpoint: 0.75, handle: true } },
      h("div.sheet-body",
        h("h2", "New thread"),
        h("p.muted", `on ${this.computer.name}`),
        h("ion-list.inset-list", { inset: true }, h("ion-item", pick)),
        text,
        start));
    start.addEventListener("click", async () => {
      const prompt = String(text.value || "").trim();
      if (!prompt) { text.setFocus?.(); return; }
      start.disabled = true;
      try {
        const s = await this.pc.post("/api/sessions", { directory: dir });
        await this.pc.post(`/api/sessions/${s.id}/prompt`, { text: prompt });
        await modal.dismiss();
        nav().push("afh-chat", { computer: this.computer, session: { ...s, running: true }, projects: this.projects });
        this.load();
      } catch (x) {
        toast(x.message, "danger", 4000);
        start.disabled = false;
      }
    });
    document.body.append(modal);
    modal.addEventListener("didDismiss", () => modal.remove());
    await modal.present();
    setTimeout(() => text.setFocus?.(), 350);
  }
});
