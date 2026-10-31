// Settings → Remote control: use AFH from your phone or another computer.

import { api } from "./api.js";
import { copyText, el, ico, toast, toggle } from "./ui.js";

export async function remotePane(pane, ctx) {
  pane.append(el("h2", "Remote control"), el("p.lead", "Open AFH from your phone, tablet or another computer: same threads, same approvals, live. Everything stays on this PC; the other device only shows the screen."));
  const account = el("div");
  pane.append(account);
  accountCard(account);
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

// The AFH account: sign in once and this PC shows up in the AFH app on your phone, from anywhere.
async function accountCard(box) {
  let st;
  try { st = await api.get("/api/cloud"); } catch (e) { box.replaceChildren(el("div.note", e.message)); return; }
  let mode = "signin";
  let timer = 0;

  const refreshSoon = () => {
    clearTimeout(timer);
    if (!box.isConnected) return;
    timer = setTimeout(async () => { try { const next = await api.get("/api/cloud"); if (next.state !== st.state || next.error !== st.error) { st = next; draw(); } else refreshSoon(); } catch {} }, 2500);
  };

  const stateText = () => ({ online: "Connected — open the AFH app on your phone", connecting: "Connecting…", retrying: "Reconnecting…", off: "Off" })[st.state] || st.state;

  const draw = () => {
    if (!st.signedIn) {
      const email = el("input.inp", { type: "email", placeholder: "Email", autocomplete: "email", value: st.email || "" });
      const pw = el("input.inp", { type: "password", placeholder: mode === "signup" ? "Choose a password (8+ characters)" : "Password", autocomplete: mode === "signup" ? "new-password" : "current-password" });
      const go = el("button.btn.primary.sm", mode === "signup" ? "Create account" : "Sign in");
      const submit = async () => {
        go.disabled = true;
        try { st = await api.post("/api/cloud/signin", { email: email.value, password: pw.value, create: mode === "signup" }); toast("This PC is now in your AFH account", "ok"); draw(); refreshSoon(); }
        catch (e) { toast(e.message, "err", 6000); go.disabled = false; }
      };
      go.addEventListener("click", submit);
      pw.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
      const other = el("button.btn.ghost.sm", { on: { click: () => { mode = mode === "signup" ? "signin" : "signup"; draw(); } } }, mode === "signup" ? "I have an account" : "Create an account");
      box.replaceChildren(el("div.card",
        el("div.card-head", el("div", el("h3", "AFH account — from anywhere"), el("p", "Sign in and this PC appears in the AFH app on your Android phone or iPhone. Watch and steer your threads while you're away; nothing to open on your router."))),
        el("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", padding: "4px 16px 14px" } }, email, pw, go, other),
        st.error ? el("div.note", { style: { margin: "0 16px 12px", color: "var(--bad)" } }, st.error) : null,
        el("div.note", { style: { margin: "0 16px 14px" } }, "The account is only for remote access. Get the app at agentflowharness.com/download, or open ", el("b", st.phoneUrl), " in your phone's browser.")));
      return;
    }
    const enable = toggle(st.enabled, async (on) => {
      try { st = await api.put("/api/cloud", { enabled: on }); } catch (e) { toast(e.message, "err", 6000); st = await api.get("/api/cloud"); }
      draw(); refreshSoon();
    });
    const dot = el("span", { style: { display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", marginInlineEnd: "6px", background: st.state === "online" ? "var(--good, #3fb950)" : st.state === "off" ? "var(--text-3)" : "var(--warn, #d29922)" } });
    box.replaceChildren(el("div.card",
      el("div.card-head", el("div", el("h3", "AFH account — from anywhere"), el("p", "Open the AFH app on your phone and sign in with the same account to reach this PC.")),
        el("button.btn.ghost.sm", { on: { click: async () => { try { st = await api.post("/api/cloud/signout"); toast("Signed out — this PC was removed from your account", "ok"); draw(); } catch (e) { toast(e.message, "err"); } } } }, "Sign out")),
      el("div.row", el("div.rl", el("b", "Reachable from your phone"), el("span", dot, st.enabled ? stateText() : "Off — your phone can't reach this PC")), enable),
      el("div.row", el("div.rl", el("b", "Account"), el("span", `${st.email} · this PC is “${st.computer?.name || "My computer"}”`))),
      st.error ? el("div.row", el("div.rl", el("span", { style: { color: "var(--bad)" } }, st.error))) : null,
      el("div.note", { style: { margin: "4px 16px 14px" } }, "Anyone signed in to this account can use AFH here like you — including running commands. Traffic goes over HTTPS through agentflowharness.com, which passes it on without keeping it.")));
    if (st.enabled && st.state !== "online") refreshSoon();
  };
  draw();
}
