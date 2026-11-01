// Settings → Remote control: use AFH from your phone or another computer.

import { api, native } from "./api.js";
import { copyText, el, ico, modal, toast, toggle } from "./ui.js";

export async function remotePane(pane, ctx) {
  pane.append(el("h2", "Remote control"), el("p.lead", "Open AFH from a phone, tablet or another computer on your own network: same threads, same approvals, live. To reach this PC from anywhere with the AFH phone app, use the account button at the bottom of the sidebar."));
  pane.append(el("h3.sub-h", "On your own network"));
  const box = el("div");
  pane.append(box);
  let st = await api.get("/api/remote");

  const draw = () => {
    box.replaceChildren();
    const pw = el("input.inp", { type: "password", placeholder: st.passwordSet ? "Change password" : "Choose a password (6+ characters)", autocomplete: "new-password", style: { maxWidth: "320px" } });
    const setPw = async () => {
      if (!pw.value) return;
      try { st = await api.put("/api/remote", { password: pw.value }); toast("Password saved", "ok"); draw(); } catch (e) { toast(e.message, "err", 6000); }
    };
    pw.addEventListener("keydown", (e) => { if (e.key === "Enter") setPw(); });
    const enable = toggle(st.enabled, async (on) => {
      try { st = await api.put("/api/remote", { enabled: on }); toast(on ? "Remote control is on" : "Remote control is off", "ok"); } catch (e) { toast(e.message, "err", 6000); st = await api.get("/api/remote"); }
      draw();
    });
    const tunnel = toggle(st.tunnel === "cloudflare", async (on) => {
      try { st = await api.put("/api/remote", { tunnel: on ? "cloudflare" : "none" }); if (on) { toast("Starting tunnel…", "info"); setTimeout(async () => { st = await api.get("/api/remote"); draw(); }, 4000); } } catch (e) { toast(e.message, "err", 6000); }
      draw();
    });
    const urlRow = (u, label) => el("div.list-item", ico("globe"), el("div.li-main", el("div.li-title", u), el("div.li-sub", { style: { fontFamily: "var(--font)" } }, label)),
      el("button.btn.sm", { on: { click: async () => { await copyText(u); toast("Copied", "ok", 1200); } } }, ico("copy"), "Copy"));
    box.append(
      el("div.card",
        el("div.row", el("div.rl", el("b", "Remote control"), el("span", st.running ? `Listening on port ${st.port}` : "Off")), enable),
        el("div.row", el("div.rl", el("b", "Password"), el("span", "Required on every other device. Anyone with it can use AFH exactly like you — including running commands.")),
          el("div", { style: { display: "flex", gap: "8px" } }, pw, el("button.btn.sm", { on: { click: setPw } }, st.passwordSet ? "Change" : "Set"))),
        el("div.row", el("div.rl", el("b", "Reachable from outside your network"), el("span", st.cloudflared ? "Uses a free Cloudflare quick tunnel (a random *.trycloudflare.com address; changes each time it starts)" : "Needs cloudflared installed on this PC — see developers.cloudflare.com/cloudflare-one")), tunnel),
        st.tunnelError ? el("div.row", el("div.rl", el("span", { style: { color: "var(--bad)" } }, st.tunnelError))) : null),
      st.running ? el("div.card", el("div.card-head", el("div", el("h3", "Connect a device"), el("p", "Same Wi-Fi: open one of these addresses. Scan the code with your phone's camera.")),
        el("button.btn.ghost.sm", { on: { click: async () => { await api.post("/api/remote/disconnect-all"); toast("All devices signed out", "ok"); } } }, "Sign out all devices")),
        el("div", { style: { display: "flex", gap: "18px", alignItems: "flex-start", padding: "14px 16px", flexWrap: "wrap" } },
          st.qr ? el("div.qr", { html: st.qr }) : null,
          el("div", { style: { flex: 1, minWidth: "260px" } },
            st.tunnelUrl ? urlRow(st.tunnelUrl, "From anywhere (tunnel)") : st.tunnel === "cloudflare" ? el("div.empty-row", el("span.spinner"), " Starting the tunnel…") : null,
            ...st.lanUrls.map((u, i) => urlRow(u, i === 0 ? "Same network" : "Same network (alternate)")),
            !st.lanUrls.length ? el("div.empty-row", "No network address found.") : null,
            el("div.note", { style: { marginTop: "10px" } }, el("b", "On the phone: "), "open the address, enter the password, and you get the full app. Add it to your home screen for an app-like experience. Windows Firewall may ask once to allow Python on private networks — allow it."))))
        : el("div.note", "Turn remote control on to see the addresses and QR code."));
  };
  draw();
}

// The AFH account (the sidebar's account button): sign in once and this PC shows up in the AFH app
// on your phone, from anywhere.
export function openAccount() {
  const box = el("div.account-modal");
  modal(el("div.m-body", { style: { padding: "22px 24px 26px" } },
    el("h2", "AFH account"),
    el("p.lead", "Reach this PC from the AFH app on your phone — follow threads, approve steps and send tasks from anywhere."),
    box), { small: true, onClose: () => refreshAccountButton() });
  accountCard(box).then(() => refreshAccountButton());
}

/** Keeps the sidebar's account button showing who's signed in and whether the phone can reach this PC. */
export async function refreshAccountButton() {
  const btn = document.getElementById("btn-account");
  if (!btn) return;
  let st;
  try { st = await api.get("/api/cloud"); } catch { return; }
  const label = btn.querySelector(".acct-text b"), sub = btn.querySelector(".acct-text small");
  btn.classList.toggle("signed-in", !!st.signedIn);
  btn.dataset.state = st.signedIn ? (st.enabled ? st.state : "off") : "out";
  if (!st.signedIn) {
    label.textContent = st.link ? "Finish in your browser…" : "Sign in";
    sub.textContent = "Use AFH from your phone";
  } else {
    label.textContent = st.email;
    sub.textContent = !st.enabled ? "Phone access off" : st.state === "online" ? "Reachable from your phone" : st.state === "connecting" ? "Connecting…" : "Reconnecting…";
  }
}

async function accountCard(box) {
  let st;
  try { st = await api.get("/api/cloud"); } catch (e) { box.replaceChildren(el("div.note", e.message)); return; }
  let timer = 0;

  const refreshSoon = () => {
    clearTimeout(timer);
    if (!box.isConnected) return;
    timer = setTimeout(async () => {
      try {
        const next = await api.get("/api/cloud");
        const changed = next.state !== st.state || next.error !== st.error || next.signedIn !== st.signedIn || !!next.link !== !!st.link || next.linkError !== st.linkError;
        if (next.signedIn && !st.signedIn) toast("This PC is now in your AFH account", "ok");
        st = next;
        refreshAccountButton();
        if (changed) draw(); else refreshSoon();
      } catch { refreshSoon(); }
    }, 2000);
  };

  const stateText = () => ({ online: "Connected — open the AFH app on your phone", connecting: "Connecting…", retrying: "Reconnecting…", off: "Off" })[st.state] || st.state;

  const draw = () => {
    if (!st.signedIn) {
      // the account lives on the website: AFH opens it there and waits for the user to approve this PC
      const head = el("div.card-head", el("div", el("h3", "Not signed in"), el("p", "Sign in and this PC appears in the AFH app on your Android phone or iPhone. Nothing to open on your router.")));
      const fine = el("div.note", { style: { margin: "0 16px 14px" } }, "You sign in or create the account on agentflowharness.com — AFH never sees your password. The account is only for remote access.");
      if (st.link) {
        const reopen = el("button.btn.sm", { on: { click: () => native.openExternal(st.link.url) } }, ico("globe"), "Open the page again");
        const cancel = el("button.btn.ghost.sm", { on: { click: async () => { st = await api.post("/api/cloud/link/cancel"); draw(); } } }, "Cancel");
        box.replaceChildren(el("div.card", head,
          el("div.row", el("div.rl", el("b", el("span.spinner", { style: { marginInlineEnd: "8px" } }), "Waiting for you in your browser…"),
            el("span", "Sign in or create your account there and approve this PC. The page shows the code ", el("b", { style: { fontFamily: "var(--mono)", color: "var(--text)" } }, st.link.code), ".")),
          el("div", { style: { display: "flex", gap: "8px" } }, reopen, cancel)),
          fine));
        refreshSoon();
        return;
      }
      const go = el("button.btn.primary.sm", ico("globe"), "Sign in with your browser");
      go.addEventListener("click", async () => {
        go.disabled = true;
        try { st = await api.post("/api/cloud/link", {}); native.openExternal(st.link.url); draw(); }
        catch (e) { toast(e.message, "err", 6000); go.disabled = false; }
      });
      box.replaceChildren(el("div.card", head,
        el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", padding: "4px 16px 14px" } }, go,
          el("button.btn.ghost.sm", { on: { click: () => native.openExternal(st.accountUrl + "?signup") } }, "Create an account")),
        st.linkError ? el("div.note", { style: { margin: "0 16px 12px", color: "var(--bad)" } }, st.linkError) : null,
        st.error ? el("div.note", { style: { margin: "0 16px 12px", color: "var(--bad)" } }, st.error) : null,
        fine));
      return;
    }
    const enable = toggle(st.enabled, async (on) => {
      try { st = await api.put("/api/cloud", { enabled: on }); } catch (e) { toast(e.message, "err", 6000); st = await api.get("/api/cloud"); }
      draw(); refreshSoon();
    });
    const dot = el("span", { style: { display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", marginInlineEnd: "6px", background: st.state === "online" ? "var(--good, #3fb950)" : st.state === "off" ? "var(--text-3)" : "var(--warn, #d29922)" } });
    box.replaceChildren(el("div.card",
      el("div.card-head", el("div", el("h3", "Signed in"), el("p", "Open the AFH app on your phone and sign in with the same account to reach this PC.")),
        el("div", { style: { display: "flex", gap: "8px" } },
          el("button.btn.ghost.sm", { on: { click: () => native.openExternal(st.accountUrl) } }, "Manage account"),
          el("button.btn.ghost.sm", { on: { click: async () => { try { st = await api.post("/api/cloud/signout"); toast("Signed out — this PC was removed from your account", "ok"); draw(); } catch (e) { toast(e.message, "err"); } } } }, "Sign out"))),
      el("div.row", el("div.rl", el("b", "Reachable from your phone"), el("span", dot, st.enabled ? stateText() : "Off — your phone can't reach this PC")), enable),
      el("div.row", el("div.rl", el("b", "Account"), el("span", `${st.email} · this PC is “${st.computer?.name || "My computer"}”`))),
      st.error ? el("div.row", el("div.rl", el("span", { style: { color: "var(--bad)" } }, st.error))) : null,
      el("div.note", { style: { margin: "4px 16px 14px" } }, "Anyone signed in to this account can use AFH here like you — including running commands. Traffic goes over HTTPS through agentflowharness.com, which passes it on without keeping it.")));
    if (st.enabled && st.state !== "online") refreshSoon();
  };
  draw();
}
