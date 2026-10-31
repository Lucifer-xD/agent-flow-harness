// The AFH account page: create an account or sign in, connect a computer that AFH sent here
// (?link=CODE), and manage your computers. Talks to the relay at /relay/api on this same site;
// the sign-in lives in an HttpOnly cookie the page itself can't read.
(() => {
  const root = document.getElementById("acct");
  const params = new URLSearchParams(location.search);
  let linkCode = (params.get("link") || "").toUpperCase();
  let mode = params.has("signup") ? "signup" : "signin";
  let me = null;
  let poll = 0;

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

  const ago = (t) => {
    if (!t) return "never connected";
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 90) return "seen just now";
    if (s < 3600) return `seen ${Math.round(s / 60)} min ago`;
    if (s < 86400) return `seen ${Math.round(s / 3600)} h ago`;
    return `seen ${Math.round(s / 86400)} days ago`;
  };

  const note = () => h("p.acct-msg", { hidden: true });
  const say = (box, text, ok) => { box.textContent = text; box.className = ok ? "acct-msg ok" : "acct-msg bad"; box.hidden = false; };

  // ---- signed out ----------------------------------------------------------------------------

  async function authView(link) {
    const msg = note();
    const email = h("input", { type: "email", autocomplete: "email", required: true, placeholder: "you@example.com" });
    const pw = h("input", { type: "password", required: true, minlength: "8", autocomplete: mode === "signup" ? "new-password" : "current-password",
      placeholder: mode === "signup" ? "8 characters or more" : "Your password" });
    const go = h("button.btn.btn-primary.acct-submit", { type: "submit" }, mode === "signup" ? "Create account" : "Sign in");
    const form = h("form.acct-form", {
      async onsubmit(e) {
        e.preventDefault();
        go.disabled = true;
        try {
          await call("POST", mode, { email: email.value, password: pw.value });
          await load();
        } catch (x) { say(msg, x.message); go.disabled = false; }
      },
    },
      h("label", {}, h("span", {}, "Email"), email),
      h("label", {}, h("span", {}, "Password"), pw),
      msg, go);
    const tab = (m, label) => h("button", { type: "button", class: mode === m ? "on" : "", onclick: () => { mode = m; authView(link); } }, label);
    show(
      h("section.acct-hero", {},
        h("p.kicker", {}, "AFH account"),
        h("h1.acct-title", {}, link ? h("span", {}, "Connect ", h("span.grad-text", {}, link.name)) : mode === "signup" ? "Create your account." : "Welcome back."),
        h("p.sub", {}, link
          ? "Sign in, or create an account, and this computer shows up in the AFH app on your phone."
          : "One account for the AFH app on your phone and every computer you connect. AFH itself never needs it.")),
      h("section.panel.acct-card", {},
        h("div.acct-tabs", {}, tab("signin", "Sign in"), tab("signup", "Create account")),
        form),
      h("p.acct-fine", {}, "The account is only for remote access. The server keeps your email, a hash of your password and your list of computers — never threads, files or keys."));
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
          h("p.sub", {}, "Go back to AFH — it finishes by itself in a few seconds. Then open the AFH app on your phone and sign in with ", h("b", {}, me.user.email), "."),
          h("div.cta-row", {}, h("a.btn.btn-primary", { href: "/account" }, "Your computers"), h("a.btn.btn-ghost", { href: "/download#phone" }, "Get the phone app"))));
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
        h("p.sub", {}, "AFH on this computer asked to join your account. Once it's in, you can open it from the AFH app on your phone.")),
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
      h("div.cta-row", {}, h("a.btn.btn-ghost", { href: "/account" }, "Your account"))));
  }

  // ---- signed in -------------------------------------------------------------------------------

  function computerRow(c) {
    const msg = note();
    let confirming = false;
    const remove = h("button.btn.btn-ghost.btn-small.acct-danger", { type: "button" }, "Remove");
    remove.addEventListener("click", async () => {
      if (!confirming) { confirming = true; remove.textContent = "Click again to remove"; return; }
      try { await call("DELETE", `computers/${c.id}`); load(); } catch (x) { say(msg, x.message); }
    });
    const rename = h("button.btn.btn-ghost.btn-small", { type: "button" }, "Rename");
    const row = h("div.acct-pc" + (c.online ? ".on" : ""), {},
      h("span.acct-dot", {}),
      h("div.acct-pc-main", {}, h("b", {}, c.name), h("span", {}, c.online ? "Online" : `Offline · ${ago(c.lastSeen)}`, c.version ? ` · AFH ${c.version}` : "")),
      h("div.acct-pc-actions", {},
        c.online ? h("a.btn.btn-ghost.btn-small", { href: `/r/${c.id}/`, title: "Open AFH on this computer in your browser" }, "Open") : null,
        rename, remove),
      msg);
    rename.addEventListener("click", () => {
      const input = h("input", { value: c.name, maxlength: "60" });
      const save = h("button.btn.btn-primary.btn-small", { type: "button" }, "Save");
      const done = async () => {
        try { await call("PATCH", `computers/${c.id}`, { name: input.value }); load(); } catch (x) { say(msg, x.message); }
      };
      save.addEventListener("click", done);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(); if (e.key === "Escape") load(); });
      row.querySelector(".acct-pc-main").replaceChildren(input);
      row.querySelector(".acct-pc-actions").replaceChildren(save);
      input.focus();
      clearInterval(poll);
    });
    return row;
  }

  function accountView() {
    const pwMsg = note();
    const old = h("input", { type: "password", autocomplete: "current-password", placeholder: "Current password" });
    const fresh = h("input", { type: "password", autocomplete: "new-password", minlength: "8", placeholder: "New password" });
    const delMsg = note();
    const delPw = h("input", { type: "password", autocomplete: "current-password", placeholder: "Your password" });
    const list = me.computers;
    root.replaceChildren(
      h("section.acct-hero", {},
        h("p.kicker", {}, "AFH account"),
        h("h1.acct-title", {}, "Your computers."),
        h("div.acct-who", {}, h("span", {}, "Signed in as ", h("b", {}, me.user.email)),
          h("button.btn.btn-ghost.btn-small", { type: "button", async onclick() { await call("POST", "signout").catch(() => {}); me = null; mode = "signin"; authView(); } }, "Sign out"))),
      h("section.panel.acct-card", {},
        list.length ? h("div.acct-pcs", {}, list.map(computerRow)) : h("div.acct-empty", {},
          h("b", {}, "No computers yet."),
          h("p", {}, "In AFH on your computer, open ", h("b", {}, "Settings → Remote control"), " and choose ", h("b", {}, "Sign in with your browser"), ". It brings you back here to connect it."))),
      h("section.acct-grid", {},
        h("div.panel.acct-card", {},
          h("h2", {}, "On your phone"),
          h("p", {}, "Get the AFH app for Android or iPhone and sign in with this account to reach these computers from anywhere."),
          h("div.cta-row", {}, h("a.btn.btn-primary.btn-small", { href: "/download#phone" }, "Get the app"))),
        h("form.panel.acct-card", {
          async onsubmit(e) {
            e.preventDefault();
            try { await call("POST", "password", { old: old.value, new: fresh.value }); old.value = fresh.value = ""; say(pwMsg, "Password changed. Your phones were signed out.", true); }
            catch (x) { say(pwMsg, x.message); }
          },
        },
          h("h2", {}, "Password"),
          h("div.acct-form", {}, old, fresh),
          pwMsg,
          h("div.cta-row", {}, h("button.btn.btn-ghost.btn-small", { type: "submit" }, "Change password")))),
      h("section.panel.acct-card.acct-delete", {},
        h("h2", {}, "Delete account"),
        h("p", {}, "Deletes the account and disconnects every computer. Nothing on your computers is touched."),
        h("div.acct-inline", {}, delPw, h("button.btn.btn-ghost.btn-small.acct-danger", {
          type: "button",
          async onclick() {
            try { await call("POST", "account/delete", { password: delPw.value }); me = null; authView(); }
            catch (x) { say(delMsg, x.message); }
          },
        }, "Delete my account")),
        delMsg));
  }

  async function load() {
    clearInterval(poll);
    let link = null;
    if (linkCode) {
      try { link = await call("GET", `link/${linkCode}`); } catch (x) { return expiredView(x.status === 410 ? x.message : null); }
    }
    try {
      me = await call("GET", "me");
    } catch (x) {
      if (x.status === 401) return authView(link);
      return show(h("section.acct-hero", {}, h("h1.acct-title", {}, "Can't reach the account server."), h("p.sub", {}, x.message),
        h("div.cta-row", {}, h("button.btn.btn-ghost", { type: "button", onclick: load }, "Try again"))));
    }
    if (link) return linkView(link);
    accountView();
    poll = setInterval(async () => {
      if (document.hidden || root.querySelector(".acct-pc input")) return;
      try { me = await call("GET", "me"); const pcs = root.querySelector(".acct-pcs"); if (pcs) pcs.replaceChildren(...me.computers.map(computerRow)); } catch { /* keep the list */ }
    }, 8000);
  }

  load();
})();
