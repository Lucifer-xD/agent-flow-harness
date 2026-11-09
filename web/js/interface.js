// Interfaces (Settings → Appearance → Interface): Studio, Focus, Compact and Canvas share every feature.
// interfaces.css restyles the app per <html data-ui>, and each interface has its own themes
// (appearance.js INTERFACE_LOOKS). None of them needs extra DOM; switching only redraws what is on screen.

export const uiName = () => document.documentElement.dataset.ui || "studio";

/** `app`: redraw(). */
export function initInterface(app) {
  addEventListener("afh-interface", () => app.redraw());
}
