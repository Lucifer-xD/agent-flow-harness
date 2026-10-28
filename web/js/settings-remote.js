// Settings → Remote control: use AFH from your phone or another computer.

import { api } from "./api.js";
import { copyText, el, ico, toast, toggle } from "./ui.js";

export async function remotePane(pane, ctx) {
  pane.append(el("h2", "Remote control"), el("p.lead", "Open AFH from your phone, tablet or another computer: same threads, same approvals, live. Everything stays on this PC; the other device only shows the screen."));
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
