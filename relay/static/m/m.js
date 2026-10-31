// AFH Remote: sign in, see your computers, open one. The same page runs in the Android and iPhone apps.
"use strict";

// older Android WebViews (before Chrome 86) lack replaceChildren
for (const proto of [Element.prototype, Document.prototype, DocumentFragment.prototype]) {
  if (!proto.replaceChildren) proto.replaceChildren = function (...nodes) { while (this.lastChild) this.removeChild(this.lastChild); this.append(...nodes); };
}

// AFH's own interface needs a current web engine (2021 or later); say so instead of a blank screen
const MODERN = (() => { try { new Function("let a; a ??= 1; class X { #p = 1; static { } }"); return true; } catch { return false; } })();

const view = document.getElementById("view");
const accountBtn = document.getElementById("btn-account");
let me = null;
let poll = 0;
let openSheet = "";

const show = (...nodes) => view.replaceChildren(...nodes.filter(Boolean));

function el(tag, attrs, ...kids) {
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
}

async function call(method, path, body) {
  const res = await fetch("/relay/api/" + path, {
    method, credentials: "same-origin",
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `Something went wrong (${res.status})`), { status: res.status });
  return data;
}

function ago(t) {
  if (!t) return "never connected";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "seen just now";
  if (s < 3600) return `seen ${Math.round(s / 60)} min ago`;
  if (s < 86400) return `seen ${Math.round(s / 3600)} h ago`;
  return `seen ${Math.round(s / 86400)} days ago`;
}

// ---- signed out ------------------------------------------------------------------------------

function showAuth(mode = "signin", notice = "") {
  clearInterval(poll);
  accountBtn.classList.add("hidden");
  const err = el("div.error.hidden");
  const email = el("input", { type: "email", autocomplete: "email", inputmode: "email", autocapitalize: "off", required: true });
  const password = el("input", { type: "password", autocomplete: mode === "signup" ? "new-password" : "current-password", required: true, minlength: "8" });
  const submit = el("button.primary", { type: "submit" }, mode === "signup" ? "Create account" : "Sign in");
  const form = el("form", {
    async onsubmit(e) {
      e.preventDefault();
      err.classList.add("hidden");
      submit.disabled = true;
      try {
        await call("POST", mode, { email: email.value, password: password.value });
        await load();
      } catch (x) {
        err.textContent = x.message;
        err.classList.remove("hidden");
      } finally {
        submit.disabled = false;
      }
    },
  },
    el("label", {}, "Email"), email,
    el("label", {}, mode === "signup" ? "Password (8 characters or more)" : "Password"), password,
    err, submit);
  const tab = (m, text) => el("button", { type: "button", class: mode === m ? "on" : "", onclick: () => showAuth(m) }, text);
  show(
    el("h1", {}, "Reach your computer from anywhere"),
    el("p", {}, "Watch and steer your AFH threads while you're away from your laptop."),
    notice ? el("div.ok", {}, notice) : null,
    el("div.tabs", {}, tab("signin", "Sign in"), tab("signup", "Create account")),
    el("div.card", {}, form),
    el("p.hint", { style: "margin-top:16px" },
      "The account is only for remote access. AFH itself runs on your computer and never needs one. "
      + "Use the same account in AFH on your computer: Settings → Remote control → AFH account."));
  email.focus({ preventScroll: true });
}

// ---- signed in -------------------------------------------------------------------------------

function computerRow(c) {
  const sheet = openSheet === c.id ? computerSheet(c) : null;
  const row = el(c.online ? "a.computer.on" : "div.computer.off", c.online ? { href: `/r/${c.id}/` } : {},
    el("span.dot"),
    el("div.info", {},
      el("div.name", {}, c.name),
      el("div.sub", {}, c.online ? "Online — tap to open" : `Offline · ${ago(c.lastSeen)}`)),
    el("button.more", {
      type: "button", "aria-label": "Options",
      onclick(e) { e.preventDefault(); e.stopPropagation(); openSheet = openSheet === c.id ? "" : c.id; render(); },
    }, "⋯"));
  return el("div", {}, row, sheet);
}

function computerSheet(c) {
  const name = el("input", { value: c.name, maxlength: "60" });
  const msg = el("div.error.hidden");
  const fail = (x) => { msg.textContent = x.message; msg.classList.remove("hidden"); };
  let confirming = false;
  const remove = el("button.ghost.danger", {
    type: "button",
    async onclick() {
      if (!confirming) { confirming = true; remove.textContent = "Tap again to remove"; return; }
      try { await call("DELETE", `computers/${c.id}`); openSheet = ""; await load(); } catch (x) { fail(x); }
    },
  }, "Remove");
  return el("div.sheet", {},
    el("label", {}, "Name"), name,
    el("div.row", {},
      el("button.ghost", { type: "button", async onclick() { try { await call("PATCH", `computers/${c.id}`, { name: name.value }); openSheet = ""; await load(); } catch (x) { fail(x); } } }, "Rename"),
      remove),
    el("p.hint", { style: "margin:10px 0 0" }, "Removing signs this computer out of remote access; you can add it again from AFH on it."),
    msg);
}

function render() {
  if (!me) return;
  accountBtn.classList.remove("hidden");
  const list = me.computers;
  show(
    MODERN ? null : el("div.error", { style: "margin:0 0 16px" },
      "This phone's web engine is too old to show AFH. Update “Android System WebView” and Chrome from the Play Store (or update iOS), then open the app again."),
    el("h1", {}, "Your computers"),
    list.length ? el("p", {}, "Tap a computer that's online to open AFH on it.") : null,
    list.length
      ? el("div.computers", {}, list.map(computerRow))
      : el("div.card", {},
        el("p", {}, "No computers yet. To add one:"),
        el("ol.steps", {},
          el("li", {}, "Open ", el("b", {}, "AFH"), " on your computer (version 1.9 or later)."),
          el("li", {}, "Go to ", el("b", {}, "Settings → Remote control → AFH account"), "."),
          el("li", {}, "Sign in with ", el("b", {}, me.user.email), " and turn on remote access.")),
        el("p.hint", { style: "margin:12px 0 0" }, "It shows up here within a few seconds.")));
}

function showAccount() {
  clearInterval(poll);
  const old = el("input", { type: "password", autocomplete: "current-password" });
  const fresh = el("input", { type: "password", autocomplete: "new-password", minlength: "8" });
  const msg = el("div.hidden");
  const say = (cls, text) => { msg.className = cls; msg.textContent = text; };
  const delPw = el("input", { type: "password", autocomplete: "current-password" });
  show(
    el("button.link", { type: "button", onclick: load }, "← Your computers"),
    el("h1", { style: "margin-top:14px" }, "Account"),
    el("div.who", {}, el("span", {}, "Signed in as ", el("b", {}, me.user.email)),
      el("button.ghost", { type: "button", async onclick() { await call("POST", "signout").catch(() => {}); me = null; showAuth(); } }, "Sign out")),
    el("div.card", {},
      el("form", {
        async onsubmit(e) {
          e.preventDefault();
          try { await call("POST", "password", { old: old.value, new: fresh.value }); old.value = fresh.value = ""; say("ok", "Password changed. Other devices were signed out."); }
          catch (x) { say("error", x.message); }
        },
      },
        el("h2", { style: "margin-top:0" }, "Change password"),
        el("label", {}, "Current password"), old,
        el("label", {}, "New password"), fresh,
        el("button.primary", { type: "submit" }, "Change password")),
      msg),
    el("h2", {}, "Delete account"),
    el("div.card", {},
      el("p", {}, "Deletes the account and signs every computer out of remote access. Nothing on your computers is touched."),
      el("label", {}, "Password"), delPw,
      el("div.row", {}, el("button.ghost.danger", {
        type: "button",
        async onclick() {
          try { await call("POST", "account/delete", { password: delPw.value }); me = null; showAuth("signin", "Your account was deleted."); }
          catch (x) { say("error", x.message); }
        },
      }, "Delete my account"))),
    el("p.hint", { style: "margin-top:20px" },
      "Remote access passes through agentflowharness.com over HTTPS. The server keeps your email, a hash of your password and your list of computers — never your threads, files or keys."));
}

async function load() {
  try {
    me = await call("GET", "me");
  } catch (x) {
    me = null;
    if (x.status === 401) return showAuth();
    show(el("div.card.notice", {}, el("h1", {}, "Can't reach AFH"), el("p", {}, x.message),
      el("div.row", {}, el("button.ghost", { type: "button", onclick: load }, "Try again"))));
    return;
  }
  render();
  clearInterval(poll);
  poll = setInterval(async () => {
    if (document.hidden || openSheet) return;
    try { me = await call("GET", "me"); render(); } catch { /* keep the last list */ }
  }, 8000);
}

accountBtn.addEventListener("click", showAccount);
document.addEventListener("visibilitychange", () => { if (!document.hidden && me) load(); });
load();
