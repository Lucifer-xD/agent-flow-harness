// The account: who's signed in, the website for everything else, sign out.
import { account, auth, openWeb, SERVER } from "../api.js";
import { confirmSheet, h, icon, mark } from "../ui.js";
import { nav, VERSION } from "../nav.js";

customElements.define("afh-account", class extends HTMLElement {
  connectedCallback() {
    if (this.built) return;
    this.built = true;
    const row = (ico, label, sub, click, cls = "") => h("ion-item" + cls, { button: true, detail: !!click, on: click ? { click } : {} },
      icon(ico, { slot: "start" }), h("ion-label", h("h3", label), sub ? h("p", sub) : null));
    this.append(
      h("ion-header", { translucent: true },
        h("ion-toolbar",
          h("ion-buttons", { slot: "start" }, h("ion-back-button", { "default-href": "#", text: "" })),
          h("ion-title", "Account"))),
      h("ion-content", { fullscreen: true },
        h("div.account-hero", h("div.avatar", (auth.email || "?")[0].toUpperCase()), h("b", auth.email), h("span", "Signed in")),
        h("ion-list", { inset: true },
          row("globe-outline", "Manage account", "Computers, password and deleting the account", () => openWeb(`${SERVER}/account`)),
          row("laptop-outline", "Connect a computer", "In AFH: Settings → Remote control → Sign in with your browser", () => openWeb(`${SERVER}/docs#phone`))),
        h("ion-list", { inset: true },
          row("shield-checkmark-outline", "How it stays private", "Your computer connects out over HTTPS. Threads and files stay on it.", () => openWeb(`${SERVER}/download#phone`)),
          row("download-outline", "Get AFH for your computer", "agentflowharness.com/download", () => openWeb(`${SERVER}/download`))),
        h("ion-list", { inset: true },
          h("ion-item", { button: true, detail: false, on: { click: () => this.signOut() } },
            icon("log-out-outline", { slot: "start", class: "danger" }), h("ion-label.danger", "Sign out"))),
        h("div.about", mark(40), h("span", `AFH ${VERSION}`))));
  }

  async signOut() {
    if (!(await confirmSheet("Sign out of AFH on this phone?", "Sign out"))) return;
    await account.signOut();
    await nav().setRoot("afh-signin", {}, { animated: true, direction: "back" });
  }
});
