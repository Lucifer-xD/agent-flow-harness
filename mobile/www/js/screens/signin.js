// First screen: sign in or create the AFH account (the same one the website and AFH use).
import { account, openWeb, SERVER } from "../api.js";
import { h, icon, mark, toast } from "../ui.js";
import { nav } from "../nav.js";

customElements.define("afh-signin", class extends HTMLElement {
  connectedCallback() {
    if (this.built) return;
    this.built = true;
    let create = false;
    const email = h("ion-input", { type: "email", inputmode: "email", autocomplete: "email", label: "Email", "label-placement": "floating", fill: "solid", props: { clearInput: false } });
    const pw = h("ion-input", { type: "password", autocomplete: "current-password", label: "Password", "label-placement": "floating", fill: "solid" },
      h("ion-input-password-toggle", { slot: "end" }));
    const go = h("ion-button.grad", { expand: "block", shape: "round", size: "large" }, "Sign in");
    const err = h("p.form-error", { hidden: true });
    const title = h("h1", "Welcome back");
    const lead = h("p.lead", "Sign in to reach AFH on your computers — follow threads, answer approvals, send the next task.");
    const seg = h("ion-segment", { value: "signin", mode: "ios", on: { ionChange: (e) => setMode(e.detail.value === "signup") } },
      h("ion-segment-button", { value: "signin" }, h("ion-label", "Sign in")),
      h("ion-segment-button", { value: "signup" }, h("ion-label", "Create account")));

    const setMode = (c) => {
      create = c;
      title.textContent = c ? "Create your account" : "Welcome back";
      go.textContent = c ? "Create account" : "Sign in";
      pw.setAttribute("autocomplete", c ? "new-password" : "current-password");
      pw.helperText = c ? "8 characters or more" : "";
      err.hidden = true;
    };

    const submit = async () => {
      err.hidden = true;
      const e = String(email.value || "").trim(), p = String(pw.value || "");
      if (!e || !p) { err.textContent = "Enter your email and password."; err.hidden = false; return; }
      go.disabled = true;
      try {
        await account.signIn(e, p, create);
        await nav().setRoot("afh-computers", {}, { animated: true, direction: "forward" });
        if (create) toast("Account created. Now connect a computer from AFH on it.", "success", 4500);
      } catch (x) {
        err.textContent = x.message;
        err.hidden = false;
      } finally {
        go.disabled = false;
      }
    };
    go.addEventListener("click", submit);
    pw.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });

    this.append(h("ion-content.signin", { fullscreen: true },
      h("div.signin-wrap",
        h("div.signin-hero", mark(84), title, lead),
        seg,
        h("div.signin-form", email, pw, err, go),
        h("p.fine", "The account is only for remote access. AFH runs on your computer; the account server never sees your threads, files or keys."),
        h("ion-button.link-btn", { fill: "clear", size: "small", on: { click: () => openWeb(`${SERVER}/account`) } }, icon("open-outline", { slot: "start" }), "Your account on agentflowharness.com"))));
  }
});
