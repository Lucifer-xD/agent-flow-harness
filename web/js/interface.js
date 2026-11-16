// Interfaces (Settings → Appearance → Interface): Studio, Focus, Compact and Canvas share every feature.
// interfaces.css restyles the app per <html data-ui>, and each interface has its own themes
// (appearance.js INTERFACE_LOOKS). None of them needs extra DOM; switching only redraws what is on screen.

import { hydrateIcons } from "./ui.js";

export const uiName = () => document.documentElement.dataset.ui || "studio";

/** `app`: redraw(). */
export function initInterface(app) {
  // Onyx draws its own icons, so the ones written into the page are drawn again when you switch to or from it
  addEventListener("afh-interface", () => { hydrateIcons(); app.redraw(); });
}
