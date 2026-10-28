// Capture README screenshots of the AFH web UI with Electron.
//
//   desktop\node_modules\.bin\electron.cmd desktop\scripts\shots.js [URL]
//
// Read-only: it only clicks around the UI (new thread, open thread, Watch,
// Changes, Settings tabs, context editor). It never types into the composer,
// never submits, and never saves settings. The light theme is applied via
// `document.documentElement.dataset.theme` for the page only.
//
// Requires a running backend. URL defaults to the one below (the token is
// consumed from the hash into sessionStorage by the page itself).

const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const URL = process.argv[2] || "http://127.0.0.1:50590/#token=EGPVUbVnpFfMJCKzcd0u36qJRtg_MRWw";
const OUT = path.resolve(__dirname, "..", "..", "docs", "screenshots");
const SCALE = Number(process.env.AFH_SHOT_SCALE || 2);
// Offscreen rendering is not clamped to the physical display (a hidden 1440x900
// window gets shrunk to the work area on Windows); set AFH_SHOT_OFFSCREEN=0 to
// use a regular hidden window instead.
const OFFSCREEN = process.env.AFH_SHOT_OFFSCREEN !== "0";

app.commandLine.appendSwitch("force-device-scale-factor", String(SCALE));
app.commandLine.appendSwitch("high-dpi-support", "1");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Each step is JS evaluated in the page (sync or returning a Promise), then
// we wait `wait` ms before capturing.
const SCENES = [
  {
    name: "home",
    wait: 800,
    js: `document.getElementById('btn-new').click();`,
  },
  {
    name: "logo-working",
    wait: 600,
    js: `document.querySelectorAll('.afh-logo').forEach(n => n.classList.add('working'));`,
    after: `document.querySelectorAll('.afh-logo').forEach(n => n.classList.remove('working'));`,
  },
  {
    name: "thread-delegation",
    wait: 600,
    js: `(async () => {
      const t = document.querySelectorAll('.th-item')[0];
      if (!t) throw new Error('no .th-item in thread list');
      t.click();
      await new Promise(r => setTimeout(r, 2500));
      const d = document.querySelector('.deleg');
      if (!d) throw new Error('no .deleg card in first thread');
      d.scrollIntoView({ block: 'start' });
    })()`,
  },
  {
    name: "watch-pane",
    wait: 3000,
    js: `(() => {
      const b = [...document.querySelectorAll('.deleg button')].find(b => b.innerText.includes('Watch'));
      if (!b) throw new Error('no Watch button inside .deleg');
      b.click();
    })()`,
  },
  {
    name: "changes",
    wait: 1500,
    js: `(async () => {
      document.getElementById('btn-drawer-close')?.click();
      await new Promise(r => setTimeout(r, 400));
      document.getElementById('btn-changes').click();
    })()`,
  },
  {
    name: "settings-delegation",
    wait: 1500,
    js: `(async () => {
      document.getElementById('btn-drawer-close')?.click();
      await new Promise(r => setTimeout(r, 300));
      document.getElementById('btn-settings').click();
      await new Promise(r => setTimeout(r, 500));
      pickTab('Delegation');
    })()`,
  },
  {
    name: "settings-models",
    wait: 500,
    js: `(async () => {
      pickTab('Models');
      await new Promise(r => setTimeout(r, 3500));
      document.querySelector('.provider')?.setAttribute('open', '');
    })()`,
  },
  { name: "settings-skills", wait: 9000, js: `pickTab('Skills')` },
  { name: "settings-prompts", wait: 5000, js: `pickTab('Prompts')` },
  { name: "settings-remote", wait: 1500, js: `pickTab('Remote')` },
  {
    name: "context-editor",
    wait: 3000,
    js: `(async () => {
      document.querySelector('.m-close')?.click();
      await new Promise(r => setTimeout(r, 400));
      document.querySelectorAll('.th-item')[0].click();
      await new Promise(r => setTimeout(r, 2000));
      const b = document.getElementById('btn-context');
      if (!b) throw new Error('no #btn-context');
      b.click();
    })()`,
  },
  {
    name: "light-home",
    wait: 800,
    js: `(async () => {
      document.querySelector('.m-close')?.click();
      await new Promise(r => setTimeout(r, 300));
      document.documentElement.dataset.theme = 'light';
      document.getElementById('btn-new').click();
    })()`,
  },
];

// Helper injected once into the page.
const HELPERS = `
  window.pickTab = (label) => {
    const b = [...document.querySelectorAll('.m-nav button')].find(b => b.innerText.includes(label));
    if (!b) throw new Error('no settings tab matching ' + JSON.stringify(label));
    b.click();
  };
  true;
`;

// A capture is "blank" if the bitmap is (almost) uniform. We sample the raw
// BGRA bitmap on a coarse grid and look at the spread of luminance.
function looksBlank(img) {
  const { width, height } = img.getSize();
  if (!width || !height) return true;
  const bmp = img.toBitmap();
  let min = 255, max = 0, n = 0;
  const step = Math.max(1, Math.floor(Math.min(width, height) / 40));
  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      const i = (y * width + x) * 4;
      const l = 0.114 * bmp[i] + 0.587 * bmp[i + 1] + 0.299 * bmp[i + 2];
      if (l < min) min = l;
      if (l > max) max = l;
      n++;
    }
  }
  return n === 0 || max - min < 8;
}

async function capture(win, file) {
  let img = await win.webContents.capturePage();
  if (looksBlank(img)) {
    // Hidden windows occasionally yield blank captures; show briefly and retry.
    console.log(`  blank capture for ${path.basename(file)}, showing window and retrying`);
    win.show();
    await sleep(700);
    img = await win.webContents.capturePage();
  }
  const png = img.toPNG();
  fs.writeFileSync(file, png);
  const { width, height } = img.getSize();
  return { bytes: png.length, width, height, blank: looksBlank(img) };
}

async function waitForApp(win, timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const ok = await win.webContents
      .executeJavaScript(`(() => { const a = document.getElementById('app'); return !!a && a.hidden === false; })()`)
      .catch(() => false);
    if (ok) return true;
    await sleep(250);
  }
  return false;
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    show: false,
    useContentSize: true,
    backgroundColor: "#000000",
    webPreferences: { offscreen: OFFSCREEN, contextIsolation: true, backgroundThrottling: false },
  });
  if (OFFSCREEN) {
    // Offscreen surfaces ignore --force-device-scale-factor, so emulate a 2x
    // display instead: a SCALE-times larger surface zoomed by SCALE renders the
    // same 1440x900 CSS layout at devicePixelRatio === SCALE.
    win.webContents.setFrameRate(30);
    win.setContentSize(1440 * SCALE, 900 * SCALE);
    win.webContents.setZoomFactor(SCALE);
  } else {
    win.webContents.setZoomFactor(1);
    win.setContentSize(1440, 900);
  }
  console.log(`window content size: ${win.getContentSize().join("x")}  scale=${SCALE}  offscreen=${OFFSCREEN}`);
  win.webContents.on("console-message", (_e, level, msg) => {
    if (level >= 2) console.log(`  [page] ${msg}`);
  });

  const loaded = new Promise((resolve) => win.webContents.once("did-finish-load", resolve));
  await win.loadURL(URL);
  await loaded;
  await sleep(4000);
  if (!(await waitForApp(win))) throw new Error("#app never became visible (bad token or backend down?)");
  await win.webContents.executeJavaScript(HELPERS);
  await sleep(500);

  const results = [];
  for (const s of SCENES) {
    const file = path.join(OUT, `${s.name}.png`);
    try {
      await win.webContents.executeJavaScript(s.js, true);
      await sleep(s.wait);
      const r = await capture(win, file);
      if (s.after) await win.webContents.executeJavaScript(s.after, true);
      results.push({ name: s.name, ...r, ok: !r.blank && r.bytes > 20 * 1024 });
      console.log(`  ${s.name}.png  ${r.width}x${r.height}  ${(r.bytes / 1024).toFixed(0)} KB${r.blank ? "  (BLANK)" : ""}`);
    } catch (e) {
      results.push({ name: s.name, ok: false, error: String((e && e.message) || e) });
      console.log(`  ${s.name}.png  FAILED: ${(e && e.message) || e}`);
    }
  }

  console.log("\nSummary:");
  for (const r of results) {
    console.log(
      `  ${r.ok ? "OK  " : "FAIL"} ${r.name}.png` +
        (r.error ? `  (${r.error})` : r.bytes ? `  ${(r.bytes / 1024).toFixed(0)} KB ${r.width}x${r.height}` : "")
    );
  }
  const failed = results.filter((r) => !r.ok).length;
  win.destroy();
  app.exit(failed ? 1 : 0);
}

app.whenReady().then(main).catch((e) => {
  console.error("shots.js failed:", e);
  app.exit(2);
});
