// Home: the computers on this account, live. Tap one to see its threads.
import { account } from "../api.js";
import { ago, h, icon, fill } from "../ui.js";
import { nav } from "../nav.js";

customElements.define("afh-computers", class extends HTMLElement {
  connectedCallback() {
    if (this.built) return;
    this.built = true;
    this.list = h("div.pc-list", h("div.skeleton-card"), h("div.skeleton-card"));
    const refresher = h("ion-refresher", { slot: "fixed", on: { ionRefresh: async (e) => { await this.load(); e.target.complete(); } } }, h("ion-refresher-content"));
    this.append(
      h("ion-header", { translucent: true },
        h("ion-toolbar",
          h("ion-title", "Computers"),
          h("ion-buttons", { slot: "end" },
            h("ion-button", { "aria-label": "Account", on: { click: () => nav().push("afh-account") } }, icon("person-circle-outline", { slot: "icon-only" }))))),
      h("ion-content", { fullscreen: true },
        h("ion-header", { collapse: "condense" }, h("ion-toolbar", h("ion-title", { size: "large" }, "Computers"))),
        refresher,
        this.list));
    this.addEventListener("ionViewDidEnter", () => { this.load(); this.timer = setInterval(() => !document.hidden && this.load(), 8000); });
    this.addEventListener("ionViewWillLeave", () => clearInterval(this.timer));
    this.load();
  }

  async load() {
    let me;
    try {
      me = await account.me();
    } catch (x) {
      if (x.status === 401) return;
      if (!this.computers) fill(this.list, h("div.empty", icon("cloud-offline-outline", { class: "empty-icon" }), h("h2", "Can't reach AFH"), h("p", x.message),
        h("ion-button", { fill: "outline", shape: "round", on: { click: () => this.load() } }, "Try again")));
      return;
    }
    this.computers = me.computers;
    if (!me.computers.length) {
      fill(this.list, h("div.empty",
        h("div.empty-art", icon("laptop-outline")),
        h("h2", "Connect your first computer"),
        h("p", "On your computer, open AFH and go to"),
        h("p.path", "Settings → Remote control → Sign in with your browser"),
        h("p", "Sign in there with this account and approve it. It shows up here right away."),
        h("ion-button", { fill: "outline", shape: "round", on: { click: () => this.load() } }, icon("refresh", { slot: "start" }), "Check again")));
      return;
    }
    const online = me.computers.filter((c) => c.online).length;
    fill(this.list, 
      h("p.section-label", online ? `${online} of ${me.computers.length} online` : "All offline"),
      ...me.computers.map((c) => h("button.pc-card" + (c.online ? ".on" : ""), { on: { click: () => nav().push("afh-threads", { computer: c }) } },
        h("div.pc-tile", icon(/mac|book|laptop/i.test(c.name) ? "laptop-outline" : "desktop-outline")),
        h("div.pc-main",
          h("b", c.name),
          h("span.pc-status", h("i.dot"), c.online ? "Online" : `Offline · ${c.lastSeen ? "seen " + ago(c.lastSeen) : "never connected"}`),
          c.version ? h("span.pc-ver", `AFH ${c.version}`) : null),
        icon("chevron-forward", { class: "chev" }))));
  }
});
