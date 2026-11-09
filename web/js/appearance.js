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
  aurora: { name: "Aurora", accent: "#5eead4", ...dark("#0a0f12", "#0c1317", "#10181d", "#152027", "#1c2a32", "#1d2b33", "#2b3e48", "#e5f3f2", "#a2bcbd", "#6a8486", "#070b0d") },
  nebula: { name: "Nebula", accent: "#b38cff", ...dark("#0e0b14", "#120e19", "#17121f", "#1d1727", "#272033", "#272035", "#382e4a", "#efe9f8", "#b6aac8", "#7e7391", "#0a080f") },
  ember: { name: "Ember", accent: "#ff5544", ...dark("#110b0a", "#150d0c", "#1a1110", "#221615", "#2d1e1c", "#2e1f1d", "#42302d", "#f6ebe8", "#c0aaa5", "#88736e", "#0c0807") },
  graphite: { name: "Graphite", accent: "#b6f35c", ...dark("#0d0e0f", "#111213", "#16171a", "#1c1e21", "#25282c", "#26292d", "#363a40", "#ebedef", "#a9adb3", "#73787f", "#0a0a0b") },
  slate: { name: "Slate", accent: "#5aa9ff", ...dark("#0f1318", "#12171d", "#171d24", "#1d242d", "#262f3a", "#28313c", "#38434f", "#e8edf3", "#a9b4c0", "#717d8a", "#0b0e12") },
  abyss: { name: "Abyss", accent: "#46c8ff", ...dark("#070a10", "#090d15", "#0d121c", "#121926", "#1a2333", "#1b2434", "#2a3648", "#e4ecf8", "#9fb0c8", "#66778f", "#05070b") },
  velvet: { name: "Velvet", accent: "#ff4f8b", ...dark("#100a10", "#140c14", "#1a111a", "#211622", "#2c1e2d", "#2d1f2e", "#412e43", "#f6eaf4", "#c1a9bd", "#8a7286", "#0b070b") },
  copper: { name: "Copper", accent: "#f2994a", ...dark("#100d0a", "#14100c", "#1a1510", "#221b15", "#2d241c", "#2e251d", "#43372b", "#f5ede4", "#c2b19f", "#8b7a68", "#0b0907") },
  matrix: { name: "Terminal", accent: "#39e58c", ...dark("#060908", "#08100c", "#0b1410", "#0f1b15", "#16261d", "#17271e", "#22382b", "#d9f5e4", "#93b8a2", "#5c8069", "#040705") },
  mono: { name: "Mono", accent: "#ffffff", ...dark("#0c0c0d", "#101011", "#151517", "#1b1b1e", "#242428", "#252529", "#343438", "#ededf0", "#a9a9b2", "#737380", "#09090a") },
  paper: { name: "Paper", accent: "#e85a1a", ...light("#f6f3ef", "#efebe6", "#fffdfb", "#f3efea", "#e9e3dc", "#e4ddd5", "#d3cabf", "#1b1715", "#5a534d", "#8c847c", "#f1ede8") },
  snow: { name: "Snow", accent: "#3b6cff", ...light("#f4f6fa", "#eceff5", "#ffffff", "#f1f3f8", "#e6e9f0", "#e1e5ec", "#cdd3dd", "#141821", "#525968", "#8a909c", "#eef1f6") },
  sand: { name: "Sand", accent: "#c26a1b", ...light("#f7f2ea", "#efe8dd", "#fffcf7", "#f3ece2", "#e8dfd2", "#e2d8ca", "#d0c3b2", "#211a12", "#5e5446", "#928775", "#f2ebe1") },
  lilac: { name: "Lilac", accent: "#7a4dff", ...light("#f6f4fb", "#eeebf6", "#ffffff", "#f2eff9", "#e6e1f1", "#e2ddee", "#cec7e0", "#1a1625", "#575068", "#8c859d", "#efecf6") },
  dawn: { name: "Dawn", accent: "#e8436b", ...light("#fbf4f3", "#f4eae9", "#fffbfb", "#f7eeed", "#eddfde", "#e9dad9", "#d8c4c3", "#241517", "#62494c", "#977d80", "#f5ebea") },
  peach: { name: "Peach", accent: "#f2643a", ...light("#fdf5f1", "#f7ebe5", "#fffcfa", "#faefe9", "#f1e1d9", "#eedcd3", "#dfc6ba", "#2a1912", "#6b5248", "#9d857a", "#f9eee8") },
  arctic: { name: "Arctic", accent: "#0b8fd6", ...light("#f2f7fb", "#e8f0f6", "#ffffff", "#eef4f9", "#e0eaf2", "#dbe6ef", "#c3d3e0", "#0f1b26", "#4a5d6e", "#8193a3", "#ebf2f8") },
  matcha: { name: "Matcha", accent: "#4d8a2a", ...light("#f5f7ef", "#ecf0e3", "#fdfef9", "#f1f4ea", "#e5eadb", "#e1e7d5", "#ccd5bd", "#1b2213", "#56604a", "#8a947d", "#eef2e6") },
  ivory: { name: "Ivory", accent: "#9b5de5", ...light("#faf8f3", "#f2efe7", "#fffefb", "#f5f2ea", "#ebe7dc", "#e7e2d6", "#d6cfbf", "#1f1c16", "#5b564b", "#8f8a7e", "#f4f1e9") },
  mint: { name: "Mint", accent: "#1f9d5f", ...light("#f3f9f5", "#eaf3ed", "#ffffff", "#eff6f1", "#e2ece6", "#dde8e1", "#c7d6cc", "#13201a", "#4f5f56", "#86958c", "#ecf3ee") },
  // Editor classics, tuned for AFH's surfaces.
  catppuccin: { name: "Catppuccin Mocha", accent: "#cba6f7", ...dark("#1e1e2e", "#181825", "#232336", "#2a2a3d", "#313244", "#313244", "#45475a", "#cdd6f4", "#a6adc8", "#7f849c", "#11111b") },
  dracula: { name: "Dracula", accent: "#bd93f9", ...dark("#282a36", "#21222c", "#2d2f3d", "#343746", "#3c3f52", "#383a4a", "#4a4d63", "#f8f8f2", "#c4c6d4", "#7d84a8", "#1e1f29") },
  nord: { name: "Nord", accent: "#88c0d0", ...dark("#2e3440", "#292e39", "#333a47", "#3b4252", "#434c5e", "#3b4252", "#4c566a", "#eceff4", "#d8dee9", "#8e98ab", "#272c36") },
  tokyonight: { name: "Tokyo Night", accent: "#7aa2f7", ...dark("#1a1b26", "#16161e", "#1f2030", "#24283b", "#2c3048", "#292e42", "#3b4261", "#c0caf5", "#a9b1d6", "#737aa2", "#13141c") },
  gruvbox: { name: "Gruvbox", accent: "#fe8019", ...dark("#282828", "#1d2021", "#2e2c2b", "#32302f", "#3c3836", "#3c3836", "#504945", "#ebdbb2", "#bdae93", "#928374", "#1d2021") },
  rosepine: { name: "Rosé Pine", accent: "#ebbcba", ...dark("#191724", "#16141f", "#1f1d2e", "#26233a", "#2e2a45", "#26233a", "#403d52", "#e0def4", "#c4c0dc", "#908caa", "#13111c") },
  solarized: { name: "Solarized", accent: "#268bd2", ...dark("#002b36", "#00252f", "#073642", "#0a3d4a", "#0f4654", "#0d4250", "#1b5664", "#eee8d5", "#b3bdbd", "#6f8789", "#00212b") },
  githubdark: { name: "GitHub Dark", accent: "#2f81f7", ...dark("#0d1117", "#010409", "#161b22", "#1c2128", "#262c36", "#21262d", "#30363d", "#e6edf3", "#9da7b3", "#6e7681", "#090c10") },
  onedark: { name: "One Dark", accent: "#61afef", ...dark("#282c34", "#21252b", "#2c313a", "#323842", "#3a404b", "#333842", "#454b57", "#dcdfe4", "#abb2bf", "#7f848e", "#1e2227") },
  monokai: { name: "Monokai", accent: "#a6e22e", ...dark("#272822", "#1f201b", "#2d2e27", "#34352d", "#3e3f37", "#3a3b33", "#4f5045", "#f8f8f2", "#cfcfc2", "#8f908a", "#1b1c17") },
  everforest: { name: "Everforest", accent: "#a7c080", ...dark("#2d353b", "#272e33", "#323c41", "#374247", "#404c51", "#3d484d", "#4f5b58", "#d3c6aa", "#b4ab95", "#859289", "#232a2e") },
  kanagawa: { name: "Kanagawa", accent: "#7e9cd8", ...dark("#1f1f28", "#16161d", "#252530", "#2a2a37", "#363646", "#2a2a37", "#54546d", "#dcd7ba", "#c8c093", "#727169", "#16161d") },
  synthwave: { name: "Synthwave", accent: "#ff7edb", ...dark("#1e1631", "#191229", "#241b3a", "#2b2145", "#352a54", "#33284f", "#4a3b70", "#f4eefe", "#c6b8e3", "#8e7fb0", "#150f24") },
  contrast: { name: "High Contrast", accent: "#ffd400", ...dark("#000000", "#000000", "#0a0a0a", "#121212", "#1e1e1e", "#5a5a5a", "#8a8a8a", "#ffffff", "#e6e6e6", "#bdbdbd", "#000000") },
  latte: { name: "Catppuccin Latte", accent: "#8839ef", ...light("#eff1f5", "#e6e9ef", "#f7f8fb", "#e9ecf2", "#dfe3ea", "#dce0e8", "#bcc0cc", "#4c4f69", "#5c5f77", "#8c8fa1", "#e6e9ef") },
  githublight: { name: "GitHub Light", accent: "#0969da", ...light("#ffffff", "#f6f8fa", "#ffffff", "#f6f8fa", "#eaeef2", "#d0d7de", "#afb8c1", "#1f2328", "#59636e", "#818b98", "#f6f8fa") },
  solarizedlight: { name: "Solarized Light", accent: "#268bd2", ...light("#fdf6e3", "#f5efdc", "#fffbef", "#f3ecd7", "#eae2ca", "#e6dec6", "#d3cbb2", "#073642", "#586e75", "#8a9a9a", "#f2ebd5") },
  rosepinedawn: { name: "Rosé Pine Dawn", accent: "#d7827e", ...light("#faf4ed", "#f2e9e1", "#fffaf3", "#f4ede8", "#ebe2da", "#e4dcd4", "#cecacd", "#575279", "#797593", "#9893a5", "#f2e9e1") },
  gruvboxlight: { name: "Gruvbox Light", accent: "#d65d0e", ...light("#fbf1c7", "#f2e5bc", "#fdf6d8", "#f2e5bc", "#ebdbb2", "#e5d5ad", "#d5c4a1", "#3c3836", "#665c54", "#928374", "#f2e5bc") },
  nordlight: { name: "Nord Light", accent: "#5e81ac", ...light("#eceff4", "#e5e9f0", "#f8f9fb", "#e9edf2", "#dfe4ec", "#d8dee9", "#c2cad8", "#2e3440", "#4c566a", "#7b869a", "#e5e9f0") },
  contrastlight: { name: "High Contrast Light", accent: "#0047ff", ...light("#ffffff", "#ffffff", "#ffffff", "#f2f2f2", "#e6e6e6", "#6b6b6b", "#3d3d3d", "#000000", "#1a1a1a", "#404040", "#f2f2f2") },
  // Focus's own themes: quiet neutrals, the accent used sparingly
  focus: { name: "Graphite", accent: "#8fb4ff", ...dark("#1a1a1c", "#141415", "#212124", "#29292d", "#333338", "#303035", "#42424a", "#ececee", "#b4b4bb", "#7e7e87", "#131314") },
  "focus-umber": { name: "Umber", accent: "#e8a56a", ...dark("#1b1917", "#151311", "#23201d", "#2b2723", "#36312c", "#332e29", "#47403a", "#efebe6", "#b9b1a8", "#847c73", "#141210") },
  "focus-chalk": { name: "Chalk", accent: "#2f6feb", ...light("#ffffff", "#f6f6f7", "#ffffff", "#f2f2f4", "#e8e8eb", "#e5e5e9", "#d2d2d8", "#18181b", "#55555e", "#8b8b95", "#f5f5f7") },
  "focus-sage": { name: "Sage", accent: "#2f7d5b", ...light("#fbfbf8", "#f3f3ee", "#ffffff", "#f1f1ec", "#e6e6df", "#e2e2da", "#cfcfc5", "#1a1c18", "#555a50", "#8a8f84", "#f3f3ee") },
  // Compact's own themes: deep, even surfaces for long working sessions
  compact: { name: "Indigo", accent: "#7b8cff", ...dark("#0f1115", "#0b0d10", "#151820", "#1b1f29", "#242935", "#232834", "#333a4a", "#e6e9f0", "#a5acbb", "#6f7687", "#0a0c0f") },
  "compact-carbon": { name: "Carbon", accent: "#f5a524", ...dark("#121212", "#0d0d0d", "#191919", "#202020", "#2a2a2a", "#292929", "#3b3b3b", "#ebebeb", "#adadad", "#787878", "#0b0b0b") },
  "compact-tide": { name: "Tide", accent: "#2dd4bf", ...dark("#0d1213", "#0a0e0f", "#131a1b", "#192223", "#212d2e", "#202c2d", "#2f4042", "#e3eeee", "#a2b5b6", "#6c8082", "#080c0d") },
  "compact-day": { name: "Daylight", accent: "#4f5bd5", ...light("#fafbfc", "#f0f2f5", "#ffffff", "#f3f5f8", "#e8ebf0", "#e3e6ec", "#cfd4dd", "#14171d", "#515866", "#878e9c", "#f1f3f6") },
  // Canvas's own themes: the second color is the frame around the sheet
  canvas: { name: "Porcelain", accent: "#5b5bd6", ...light("#ffffff", "#eceef3", "#ffffff", "#f4f5f9", "#e9ebf1", "#e4e6ed", "#cfd3de", "#171923", "#535869", "#8a8fa0", "#f3f4f8") },
  "canvas-sand": { name: "Sandstone", accent: "#c2571a", ...light("#fffdfa", "#efeae2", "#fffdfa", "#f6f1ea", "#ece5db", "#e7dfd3", "#d4cabb", "#1e1a15", "#5a5348", "#90877a", "#f5f0e8") },
  "canvas-night": { name: "Nightfall", accent: "#8b8cf8", ...dark("#16181d", "#0c0d10", "#1b1e24", "#22252d", "#2b2f39", "#2a2e37", "#3a3f4b", "#e9ebf1", "#a8adba", "#727786", "#101216") },
  "canvas-pine": { name: "Pine", accent: "#4ade80", ...dark("#141a17", "#0b0f0d", "#19201c", "#1f2823", "#28332d", "#27322c", "#38463e", "#e6efe9", "#a6b5ab", "#6f8076", "#0e1310") },
};

/** How the screen changes when the theme does. */
export const THEME_TRANSITIONS = [["circle", "Circle"], ["diamond", "Diamond"], ["wipe", "Wipe"], ["fade", "Fade"], ["blur", "Blur"], ["none", "None"]];
/** How new messages arrive. */
export const MESSAGE_ANIMS = [["rise", "Rise"], ["fade", "Fade"], ["slide", "Slide"], ["pop", "Pop"], ["blur", "Focus"], ["none", "None"]];

/** Run `apply` (which changes the colors) with the chosen screen effect, spreading from `origin`. */
export function themeTransition(ui, apply, origin) {
  const style = ui.themeTransition || "circle";
  if (!document.startViewTransition || ui.animations === false || style === "none" || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    apply();
    return;
  }
  const root = document.documentElement;
  const r = origin?.getBoundingClientRect?.();
  const x = r ? r.left + r.width / 2 : innerWidth / 2, y = r ? r.top + r.height / 2 : innerHeight / 2;
  const reach = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  root.style.setProperty("--vt-x", `${x}px`);
  root.style.setProperty("--vt-y", `${y}px`);
  root.style.setProperty("--vt-r", `${reach}px`);
  root.style.setProperty("--vt-d", `${reach * 1.45}px`);
  root.dataset.vt = style;
  root.dataset.vtDir = x > innerWidth / 2 ? "rtl" : "ltr";
  const t = document.startViewTransition(apply);
  t.finished.finally(() => { delete root.dataset.vt; delete root.dataset.vtDir; });
}

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
  if (p.dark !== wantDark) {
    // The other mode uses your favourite theme of that mode (remembered when you pick one).
    const fav = PRESETS[wantDark ? ui.darkPreset : ui.lightPreset];
    const own = INTERFACE_LOOKS[ui.interface] || INTERFACE_LOOKS.studio;
    p = fav && fav.dark === wantDark ? fav : PRESETS[wantDark ? own.dark : own.light];
  }
  return { ...p, accent: ui.accentOverride && ui.accent ? ui.accent : p.accent };
}

let styleTag = null;

/** Interfaces: the layout and treatment of the whole app. Each one has its own themes and starts in
 *  its own look (light or dark); the classic themes, custom colors, light and dark work with all of them. */
export const INTERFACES = [
  { id: "studio", name: "Studio", sub: "The classic AFH layout: a sidebar of threads, a reading column and a floating composer." },
  { id: "focus", name: "Focus", sub: "Just the conversation: a calm centered column, your messages as soft pills, steps as quiet single lines and a large rounded message box." },
  { id: "compact", name: "Compact", sub: "Built for long working sessions: turns read like a thread with names and avatars, steps stack into one tidy list, and the message box is docked along the bottom." },
  { id: "canvas", name: "Canvas", sub: "The thread sits on its own sheet inside a tinted frame: your request reads as a headline, steps flow as small chips, and the answer follows." },
];

/** Each interface's look: the mode it starts in, its dark and light themes, and the themes made for it
 *  (shown first in Settings; other interfaces don't list them). */
export const INTERFACE_LOOKS = {
  studio: { mode: "dark", dark: "sunset", light: "paper", own: [], show: ["sunset", "midnight", "forest", "paper"] },
  focus: { mode: "dark", dark: "focus", light: "focus-chalk", own: ["focus", "focus-umber", "focus-chalk", "focus-sage"] },
  compact: { mode: "dark", dark: "compact", light: "compact-day", own: ["compact", "compact-carbon", "compact-tide", "compact-day"] },
  canvas: { mode: "light", dark: "canvas-night", light: "canvas", own: ["canvas", "canvas-sand", "canvas-night", "canvas-pine"] },
};
const OWN = new Set(Object.values(INTERFACE_LOOKS).flatMap((l) => l.own));
/** The themes to offer in this interface: its own, then the classic ones. */
export function themesFor(iface) {
  const own = (INTERFACE_LOOKS[iface] || INTERFACE_LOOKS.studio).own;
  return { own, classic: Object.keys(PRESETS).filter((id) => !OWN.has(id)) };
}
const LOOK_KEYS = ["theme", "preset", "darkPreset", "lightPreset", "accent", "accentOverride", "bg", "text"];
/** The look an interface starts with the first time you pick it. */
export function defaultLook(iface) {
  const l = INTERFACE_LOOKS[iface] || INTERFACE_LOOKS.studio;
  const preset = l.mode === "dark" ? l.dark : l.light, p = PRESETS[preset];
  return { theme: l.mode, preset, darkPreset: l.dark, lightPreset: l.light, accentOverride: false, accent: p.accent, bg: p.bg, text: p.text };
}
/** The settings patch that switches to another interface: the current look is kept for this interface,
 *  and the other one comes back the way you left it (or in its own default look). */
export function interfacePatch(ui, iface) {
  const from = ui.interface || "studio";
  const looks = { ...(ui.looks || {}) };
  looks[from] = Object.fromEntries(LOOK_KEYS.map((k) => [k, ui[k]]));
  const saved = looks[iface];
  const next = saved && (saved.preset === "custom" || PRESETS[saved.preset]) ? saved : defaultLook(iface);
  return { interface: iface, looks, ...next };
}

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
  root.dataset.msgAnim = ui.msgAnim || "rise";
  root.dataset.meta = ui.showMeta ? "on" : "off";
  const iface = INTERFACES.some((x) => x.id === ui.interface) ? ui.interface : "studio";
  if (root.dataset.ui !== iface) {
    const from = root.dataset.ui || null;
    root.dataset.ui = iface;
    dispatchEvent(new CustomEvent("afh-interface", { detail: { id: iface, from } }));
  }
  document.body.classList.toggle("no-anim", ui.animations === false);
  document.body.classList.toggle("no-logo-anim", ui.logoAnim === false);
  document.body.classList.toggle("glass", ui.glass !== false);
  if (!styleTag) {
    styleTag = document.createElement("style");
    styleTag.id = "custom-css";
    document.head.append(styleTag);
  }
  styleTag.textContent = ui.customCss || "";
  return t;
}
