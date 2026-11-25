const $ = (id) => document.getElementById(id);

const TEXT = {
  connected: ["Connected to AFH", "The agent can work in this browser when a task needs it. Its tabs sit in a group named AFH and glow while it works; stop it from the page, from AFH, or with Pause below."],
  waiting: ["AFH isn't open", "Open the Agent Flow Harness app on this computer; this browser connects by itself."],
  starting: ["Connecting…", "Looking for the AFH app."],
  missing: ["AFH isn't set up here yet", "Open the Agent Flow Harness app once (update it if it's older than this extension). It sets up the link this extension uses, then this connects by itself."],
  paused: ["Paused", "AFH can't use this browser until you resume it."],
};

async function refresh() {
  const s = await chrome.runtime.sendMessage({ q: "status" });
  const [label, detail] = TEXT[s.state] || TEXT.starting;
  $("label").textContent = label;
  $("detail").textContent = detail + (s.state === "connected" && s.tabs ? ` Working in ${s.tabs} tab${s.tabs === 1 ? "" : "s"} now.` : "");
  $("state").className = "state " + (s.state === "connected" ? "ok" : s.state === "missing" ? "bad" : "");
  const btn = $("pause");
  btn.textContent = s.state === "paused" ? "Resume" : "Pause AFH in this browser";
  btn.className = s.state === "paused" ? "main" : "";
  btn.onclick = async () => {
    await chrome.runtime.sendMessage({ q: "pause", paused: s.state !== "paused" });
    setTimeout(refresh, 300);
  };
}

refresh();
setInterval(refresh, 1500);
