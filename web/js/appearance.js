// Theme engine. Presets are full, hand-tuned palettes; "custom" derives surfaces from the
// chosen background and text colors in CSS.

const dark = (bg, side, panel, panel2, panel3, border, border2, text, text2, text3, code) => ({ bg, side, panel, panel2, panel3, border, border2, text, text2, text3, code, dark: true });
const light = (bg, side, panel, panel2, panel3, border, border2, text, text2, text3, code) => ({ bg, side, panel, panel2, panel3, border, border2, text, text2, text3, code, dark: false });

export const PRESETS = {
  sunset: { name: "Sunset", accent: "#ff6a2a", ...dark("#0e0d0d", "#121010", "#171515", "#1e1b1a", "#292524", "#2a2625", "#3a3533", "#f2efec", "#b4ada6", "#7e776f", "#0b0a0a") },
  midnight: { name: "Midnight", accent: "#7c8cff", ...dark("#0b0d14", "#0e1019", "#13161f", "#191d28", "#222735", "#242936", "#343a4b", "#e9ecf5", "#aab0c2", "#737a8e", "#080a10") },
  forest: { name: "Forest", accent: "#2fbf71", ...dark("#0b110e", "#0e1511", "#121a15", "#17211b", "#1f2c24", "#213026", "#2f4236", "#e6efe9", "#a8b8ad", "#6f8276", "#080d0a") },
  ocean: { name: "Ocean", accent: "#22b8cf", ...dark("#0a1016", "#0d141b", "#111922", "#16202a", "#1d2a36", "#1f2d3a", "#2d4050", "#e4eef5", "#a4b6c4", "#6b8090", "#070c11") },
  rose: { name: "Rose", accent: "#ff3d71", ...dark("#120d10", "#160f13", "#1b1318", "#22181e", "#2c2027", "#2d2129", "#3f2f38", "#f3e9ee", "#bdaab4", "#85737c", "#0d090b") },
  mono: { name: "Mono", accent: "#ffffff", ...dark("#0c0c0d", "#101011", "#151517", "#1b1b1e", "#242428", "#252529", "#343438", "#ededf0", "#a9a9b2", "#737380", "#09090a") },
  paper: { name: "Paper", accent: "#e85a1a", ...light("#f6f3ef", "#efebe6", "#fffdfb", "#f3efea", "#e9e3dc", "#e4ddd5", "#d3cabf", "#1b1715", "#5a534d", "#8c847c", "#f1ede8") },
  snow: { name: "Snow", accent: "#3b6cff", ...light("#f4f6fa", "#eceff5", "#ffffff", "#f1f3f8", "#e6e9f0", "#e1e5ec", "#cdd3dd", "#141821", "#525968", "#8a909c", "#eef1f6") },
  mint: { name: "Mint", accent: "#1f9d5f", ...light("#f3f9f5", "#eaf3ed", "#ffffff", "#eff6f1", "#e2ece6", "#dde8e1", "#c7d6cc", "#13201a", "#4f5f56", "#86958c", "#ecf3ee") },
};

const hex = (c) => c.replace("#", "").match(/.{2}/g).map((x) => parseInt(x, 16) / 255);
export function luminance(color) {
  try {
    const [r, g, b] = hex(color).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  } catch {
    return 0;
  }
}

/** The palette in effect for these settings (honours "follow system"). */
export function resolveTheme(ui) {
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const wantDark = ui.theme === "dark" ? true : ui.theme === "light" ? false : systemDark;
  if (ui.preset === "custom") {
    const bg = ui.bg || "#0e0d0d";
    const isDark = luminance(bg) <= 0.4;
    return { custom: true, bg, text: ui.text || (isDark ? "#f2efec" : "#1b1715"), accent: ui.accent || "#ff6a2a", dark: isDark };
  }
  let p = PRESETS[ui.preset] || PRESETS.sunset;
  if (p.dark !== wantDark) p = wantDark ? PRESETS.sunset : PRESETS.paper; // follow-system flips to a matching preset
  return { ...p, accent: ui.accentOverride && ui.accent ? ui.accent : p.accent };
}

let styleTag = null;

export function applyAppearance(ui) {
  const root = document.documentElement;
  const t = resolveTheme(ui);
  const set = (k, v) => root.style.setProperty(k, v);
  root.dataset.theme = t.dark ? "dark" : "light";
  if (t.custom) {
    root.dataset.custom = "";
    for (const k of ["--bg-side", "--panel", "--panel-2", "--panel-3", "--border", "--border-2", "--text-2", "--text-3", "--code-bg"]) root.style.removeProperty(k);
  } else {
    delete root.dataset.custom;
    set("--bg-side", t.side); set("--panel", t.panel); set("--panel-2", t.panel2); set("--panel-3", t.panel3);
    set("--border", t.border); set("--border-2", t.border2); set("--text-2", t.text2); set("--text-3", t.text3); set("--code-bg", t.code);
  }
  set("--bg", t.bg);
  set("--text", t.text);
  set("--accent", t.accent);
  set("--accent-ink", luminance(t.accent) > 0.5 ? "#111" : "#fff");
  set("--accent-2", t.accent === "#ffffff" ? "#c9c9d2" : `color-mix(in srgb, ${t.accent} 70%, #ff3d71)`);
  set("--fs", `${ui.fontSize || 14}px`);
  set("--radius", `${ui.radius ?? 12}px`);
  set("--radius-lg", `${(ui.radius ?? 12) + 6}px`);
  set("--anim-speed", String(ui.animSpeed || 1));
  root.dataset.density = ui.density || "comfortable";
  root.dataset.font = ui.font || "inter";
  root.dataset.bubbles = ui.bubbles || "bubbles";
  root.dataset.meta = ui.showMeta ? "on" : "off";
  document.body.classList.toggle("no-anim", ui.animations === false);
  document.body.classList.toggle("no-logo-anim", ui.logoAnim === false);
  document.body.classList.toggle("glass", ui.glass !== false);
  if (!styleTag) {
    styleTag = document.createElement("style");
    styleTag.id = "custom-css";
    document.head.append(styleTag);
  }
  styleTag.textContent = ui.customCss || "";
  requestAnimationFrame(() => {
    const cs = getComputedStyle(document.body);
    const side = cs.getPropertyValue("--bg-side").trim() || t.bg;
    window.afh?.window?.setTitleBarOverlay?.({ color: toHex(side, t.bg), symbolColor: t.text });
  });
  return t;
}

function toHex(color, fallback) {
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (!m) return /^#/.test(color) ? color : fallback;
  const [r, g, b] = m[1].split(/[\s,]+/).map(Number);
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}
