// Theme engine: a preset or custom colors become CSS variables; everything else derives in CSS.

export const PRESETS = {
  sunset: { name: "Sunset", bg: "#0f0d0c", text: "#f1ede9", accent: "#ff6a2a", dark: true },
  midnight: { name: "Midnight", bg: "#0b0d14", text: "#e9ecf5", accent: "#7c8cff", dark: true },
  forest: { name: "Forest", bg: "#0c120f", text: "#e8f0ea", accent: "#2fbf71", dark: true },
  ocean: { name: "Ocean", bg: "#0a1017", text: "#e6f0f6", accent: "#22b8cf", dark: true },
  rose: { name: "Rose", bg: "#130d11", text: "#f3e9ee", accent: "#ff3d71", dark: true },
  mono: { name: "Mono", bg: "#0c0c0e", text: "#ededf0", accent: "#ffffff", dark: true },
  paper: { name: "Paper", bg: "#faf7f4", text: "#1c1715", accent: "#e85a1a", dark: false },
  snow: { name: "Snow", bg: "#f7f8fb", text: "#15171f", accent: "#4f6bff", dark: false },
  mint: { name: "Mint", bg: "#f4faf6", text: "#13201a", accent: "#1f9d5f", dark: false },
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

/** Which colors are in effect for these settings (honours "follow system"). */
export function resolveTheme(ui) {
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const wantDark = ui.theme === "dark" ? true : ui.theme === "light" ? false : systemDark;
  if (ui.preset === "custom") {
    const bg = ui.bg || "#0f0d0c";
    return { bg, text: ui.text || (luminance(bg) > 0.4 ? "#1c1715" : "#f1ede9"), accent: ui.accent || "#ff6a2a", dark: luminance(bg) <= 0.4 };
  }
  let p = PRESETS[ui.preset] || PRESETS.sunset;
  if (p.dark !== wantDark) p = wantDark ? PRESETS.sunset : PRESETS.paper; // follow-system flips to a matching preset
  return { ...p, accent: ui.accent && ui.accentOverride ? ui.accent : p.accent };
}

let styleTag = null;

export function applyAppearance(ui) {
  const root = document.documentElement;
  const t = resolveTheme(ui);
  root.dataset.theme = t.dark ? "dark" : "light";
  root.dataset.custom = "";
  root.style.setProperty("--bg", t.bg);
  root.style.setProperty("--text", t.text);
  root.style.setProperty("--accent", t.accent);
  root.style.setProperty("--accent-ink", luminance(t.accent) > 0.5 ? "#111" : "#fff");
  root.style.setProperty("--accent-2", t.accent === "#ffffff" ? "#c9c9d2" : `color-mix(in srgb, ${t.accent} 70%, #ff3d71)`);
  root.style.setProperty("--fs", `${ui.fontSize || 14}px`);
  root.style.setProperty("--radius", `${ui.radius ?? 12}px`);
  root.style.setProperty("--radius-lg", `${(ui.radius ?? 12) + 6}px`);
  root.style.setProperty("--anim-speed", String(ui.animSpeed || 1));
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
  // Electron's native window buttons follow the theme.
  requestAnimationFrame(() => {
    const cs = getComputedStyle(document.body);
    const side = cs.getPropertyValue("--bg-side").trim() || t.bg;
    window.afh?.window?.setTitleBarOverlay?.({ color: toHex(side, t.bg), symbolColor: t.text });
  });
  return t;
}

// color-mix() results come back as rgb(); the overlay API wants hex.
function toHex(color, fallback) {
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (!m) return /^#/.test(color) ? color : fallback;
  const [r, g, b] = m[1].split(/[\s,]+/).map(Number);
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}
