// Light or dark, set before the page paints (this loads in <head>, ahead of the stylesheets). The
// visitor's choice is kept in localStorage; until they make one, the site follows their system.
// window.afhTheme.set("dark" | "light") changes it; `afh:theme` fires on the document when it does.
(() => {
  const KEY = "afh-theme", root = document.documentElement, system = matchMedia("(prefers-color-scheme: dark)");
  const saved = () => { try { const t = localStorage.getItem(KEY); return t === "dark" || t === "light" ? t : null; } catch { return null; } };
  const apply = (theme) => {
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#120e0c" : "#f7f3ee");
    document.dispatchEvent(new CustomEvent("afh:theme", { detail: theme }));
  };
  apply(saved() || (system.matches ? "dark" : "light"));
  system.addEventListener("change", (e) => { if (!saved()) apply(e.matches ? "dark" : "light"); });
  window.afhTheme = {
    get: () => root.dataset.theme,
    set: (theme) => { try { localStorage.setItem(KEY, theme); } catch {} apply(theme); },
  };
})();
