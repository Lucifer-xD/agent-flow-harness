// The AFH account page: create an account or sign in (?signup opens that tab, ?next=/path is where
// to go after), and connect a computer that AFH sent here (?link=CODE). Computers, chat and account
// the chat (/chat) and computers (/computers) take over from there. Talks to the relay at /relay/api on this same site;
// the sign-in lives in an HttpOnly cookie the page itself can't read.
(() => {
  const root = document.getElementById("acct");
  const params = new URLSearchParams(location.search);
  let linkCode = (params.get("link") || "").toUpperCase();
  let mode = params.has("signup") ? "signup" : "signin";
  let me = null;

  const h = (tag, attrs, ...kids) => {
    const [name, ...classes] = tag.split(".");
    const node = document.createElement(name);
    if (classes.length) node.className = classes.join(" ");
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v !== false && v != null) node.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
    return node;
  };
  const show = (...nodes) => { root.replaceChildren(...nodes.filter(Boolean)); root.querySelector("input")?.focus({ preventScroll: true }); };

  async function call(method, path, body) {
    const res = await fetch("/relay/api/" + path, {
      method, credentials: "same-origin",
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (!res.ok) throw Object.assign(new Error(data.error || `Something went wrong (${res.status})`), { status: res.status });
    return data;
  }

  const note = () => h("p.acct-msg", { hidden: true });
  const say = (box, text, ok) => { box.textContent = text; box.className = ok ? "acct-msg ok" : "acct-msg bad"; box.hidden = false; };

  // ---- signed out ----------------------------------------------------------------------------

  const next = (() => {  // where to go after signing in: only paths on this site
    const n = params.get("next") || "";
    return /^\/(?!\/)[\w\-/.?=&#%]*$/.test(n) ? n : "/chat";
  })();

  function pwField(attrs) {
    const input = h("input", { type: "password", required: true, ...attrs });
    const eye = h("button.acct-eye", { type: "button", "aria-label": "Show password", title: "Show password" }, "Show");
    eye.addEventListener("click", () => {
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      eye.textContent = showing ? "Show" : "Hide";
      eye.setAttribute("aria-label", showing ? "Show password" : "Hide password");
      input.focus();
    });
    return [input, h("div.acct-pw", {}, input, eye)];
  }

  async function authView(link) {
    const signup = mode === "signup";
    const msg = note();
    const email = h("input", { type: "email", autocomplete: "email", required: true, placeholder: "you@example.com", inputmode: "email" });
    const [pw, pwBox] = pwField({ minlength: "8", autocomplete: signup ? "new-password" : "current-password", placeholder: signup ? "8 characters or more" : "Your password" });
    const [pw2, pw2Box] = pwField({ minlength: "8", autocomplete: "new-password", placeholder: "Type it again" });
    const strength = h("p.acct-hint", {}, "");
    if (signup) pw.addEventListener("input", () => {
      const v = pw.value;
      strength.textContent = !v ? "" : v.length < 8 ? `${8 - v.length} more character${v.length === 7 ? "" : "s"}` : v.length < 12 ? "Good" : "Strong";
      strength.className = "acct-hint" + (v.length >= 8 ? " ok" : "");
    });
    const go = h("button.btn.btn-primary.acct-submit", { type: "submit" }, signup ? "Create account" : "Sign in");
    const form = h("form.acct-form", {
      novalidate: true,
      async onsubmit(e) {
        e.preventDefault();
        msg.hidden = true;
        const mail = email.value.trim();
        if (!/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(mail)) return say(msg, "Enter a valid email address."), email.focus();
        if (pw.value.length < (signup ? 8 : 1)) return say(msg, signup ? "Use a password of at least 8 characters." : "Enter your password."), pw.focus();
        if (signup && pw.value !== pw2.value) return say(msg, "The two passwords don't match."), pw2.focus();
        go.disabled = true;
        go.textContent = signup ? "Creating your account…" : "Signing in…";
        try {
          await call("POST", mode, { email: mail, password: pw.value });
          if (linkCode) return load();
          location.href = next;
        } catch (x) {
          say(msg, x.message);
          go.disabled = false;
          go.textContent = signup ? "Create account" : "Sign in";
        }
      },
    },
      h("label", {}, h("span", {}, "Email"), email),
      h("label", {}, h("span", {}, "Password"), pwBox, signup ? strength : null),
      signup ? h("label", {}, h("span", {}, "Confirm password"), pw2Box) : null,
      msg, go,
      h("p.acct-switch", {}, signup ? "Already have an account? " : "New to AFH? ",
        h("button", { type: "button", onclick: () => switchTo(signup ? "signin" : "signup", link) }, signup ? "Sign in" : "Create a free account")));
    const tab = (m, label) => h("button", { type: "button", role: "tab", "aria-selected": String(mode === m), class: mode === m ? "on" : "", onclick: () => switchTo(m, link) }, label);
    show(
      h("section.acct-hero", {},
        h("p.kicker", {}, link ? "Connect a computer" : signup ? "Create your AFH account" : "AFH account"),
        h("h1.acct-title", {}, link ? h("span", {}, "Connect ", h("span.grad-text", {}, link.name)) : signup ? h("span", {}, "Your AFH, ", h("span.grad-text", {}, "everywhere.")) : "Welcome back."),
        h("p.sub", {}, link
          ? "Sign in, or create an account, and this computer shows up under Computers here and in the AFH app on your phone."
          : signup
            ? "Free. Chat with any model right here in your browser — 228 providers, with web search and more — and reach every computer running AFH from here or your phone."
            : "Sign in to chat with any model, and to reach AFH on your computers.")),
      h("section.acct-split", {},
        h("div.panel.acct-card", {},
          h("div.acct-tabs", { role: "tablist" }, tab("signin", "Sign in"), tab("signup", "Create account")),
          form),
        h("ul.acct-perks", {},
          h("li", {}, h("b", {}, "Chat with any model"), h("span", {}, "Sign in with ChatGPT, Copilot or OpenRouter, or use your own keys. It can search the web and more.")),
          h("li", {}, h("b", {}, "Your computers"), h("span", {}, "Follow AFH on your PCs live, approve steps and start new tasks.")),
          h("li", {}, h("b", {}, "Phone app too"), h("span", {}, "The same account signs in to AFH on Android and iPhone.")),
          h("li", {}, h("b", {}, "Private"), h("span", {}, "The server keeps your email and computer list. Chats and keys stay in your browser.")))));
  }

  function switchTo(m, link) {
    mode = m;
    const q = new URLSearchParams(location.search);
    q.delete("signup");
    if (m === "signup") q.set("signup", "");
    history.replaceState(null, "", "/account" + (q.toString() ? "?" + q.toString().replace(/=(&|$)/g, "$1") : ""));
    authView(link);
  }

  // ---- connecting a computer --------------------------------------------------------------------

  function linkView(link) {
    const msg = note();
    const yes = h("button.btn.btn-primary", { type: "button" }, "Connect this computer");
    const no = h("button.btn.btn-ghost", { type: "button" }, "Cancel");
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true;
      try {
        await call("POST", `link/${linkCode}/approve`);
        linkCode = "";
        history.replaceState(null, "", "/account");
        show(h("section.acct-hero.acct-done", {},
          h("p.kicker", {}, "Connected"),
          h("h1.acct-title", {}, h("span.grad-text", {}, link.name), " is in."),
          h("p.sub", {}, "Go back to AFH — it finishes by itself in a few seconds. It then shows up under Computers here, and in the AFH app on your phone when you sign in with ", h("b", {}, me.user.email), "."),
          h("div.cta-row", {}, h("a.btn.btn-primary", { href: "/computers" }, "Open Computers"), h("a.btn.btn-ghost", { href: "/download#phone" }, "Get the phone app"))));
      } catch (x) { say(msg, x.message); yes.disabled = no.disabled = false; }
    });
    no.addEventListener("click", async () => {
      await call("POST", `link/${linkCode}/deny`).catch(() => {});
      linkCode = "";
      history.replaceState(null, "", "/account");
      load();
    });
    show(
      h("section.acct-hero", {},
        h("p.kicker", {}, "Connect a computer"),
        h("h1.acct-title", {}, "Add ", h("span.grad-text", {}, link.name), "?"),
        h("p.sub", {}, "AFH on this computer asked to join your account. Once it's in, you can follow it and send it tasks from Computers here or the AFH app on your phone.")),
      h("section.panel.acct-card", {},
        h("div.acct-row", {}, h("span", {}, "Account"), h("b", {}, me.user.email)),
        h("div.acct-row", {}, h("span", {}, "Code"), h("b.mono", {}, linkCode)),
        h("p.acct-fine", { style: "margin:4px 0 18px" }, "Check that AFH on your computer shows the same code. If you didn't start this, cancel."),
        msg,
        h("div.cta-row", {}, yes, no)));
  }

  function expiredView(text) {
    show(h("section.acct-hero", {},
      h("p.kicker", {}, "Connect a computer"),
      h("h1.acct-title", {}, "This link has expired."),
      h("p.sub", {}, text || "Start again from AFH on your computer: Settings → Remote control → Sign in with your browser."),
      h("div.cta-row", {}, h("a.btn.btn-ghost", { href: "/chat" }, "Open chat"))));
  }

  async function load() {
    let link = null;
    if (linkCode) {
      try { link = await call("GET", `link/${linkCode}`); } catch (x) { return expiredView(x.status === 410 ? x.message : null); }
    }
    try {
      me = await call("GET", "me");
      if (!me?.user) throw Object.assign(new Error("The account server sent an unexpected answer."), { status: 0 });
    } catch (x) {
      if (x.status === 401) return authView(link);
      return show(h("section.acct-hero", {}, h("h1.acct-title", {}, "Can't reach the account server."), h("p.sub", {}, x.message),
        h("div.cta-row", {}, h("button.btn.btn-ghost", { type: "button", onclick: load }, "Try again"))));
    }
    if (link) return linkView(link);
    location.replace(next);  // signed in already: computers, chat and settings live on the dashboard
  }

  load();
})();
