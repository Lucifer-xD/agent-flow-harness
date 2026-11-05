// Every page's header, phone menu and footer, written once here. Pages hold <header data-nav>
// and <footer data-footer> placeholders and set <body data-page="…"> to mark their nav link.
// It also runs the entrances ([data-reveal]), section menus (.subnav) and card glows, and
// fills in the current release from downloads/latest.yml (the file the app's updater
// reads), so the version, size, date and checksum shown anywhere are always the real ones.
(() => {
  const page = document.body.dataset.page || "";
  const LINKS = [["features", "Product"], ["cli", "Terminal"], ["models", "Models"], ["docs", "Docs"], ["api", "API"], ["changelog", "Changelog"]];
  const link = ([id, label]) => `<a href="/${id}"${page === id ? ' class="active" aria-current="page"' : ""}>${label}</a>`;
  const MARK = '<img src="/assets/mark.svg" alt="" width="34" height="20">';

  if (!document.querySelector(".wash")) {
    const wash = document.createElement("div");
    wash.className = "wash";
    wash.setAttribute("aria-hidden", "true");
    document.body.prepend(wash);
  }

  const nav = document.querySelector("[data-nav]");
  if (nav) {
    nav.className = "nav";
    nav.innerHTML = `
      <a class="brand" href="/">${MARK}<span>Agent Flow Harness</span></a>
      <nav class="nav-links" aria-label="Main">${LINKS.map(link).join("")}</nav>
      <span class="nav-auth" data-auth>
        <a class="nav-signin" href="/account">Sign in</a>
      </span>
      <button class="theme-btn" type="button" aria-label="Switch between light and dark">
        <svg class="moon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.6 14.4A8.6 8.6 0 0 1 9.6 3.4a.6.6 0 0 0-.8-.7 9.8 9.8 0 1 0 12.5 12.5.6.6 0 0 0-.7-.8Z"/></svg>
        <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2" fill="currentColor" stroke="none"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>
      </button>
      <a class="btn btn-small nav-cta${page === "download" ? " active" : ""}" href="/download">Download</a>
      <button class="burger" type="button" aria-label="Menu" aria-expanded="false" aria-controls="menu"><i></i><i></i></button>`;
    const menu = document.createElement("div");
    menu.className = "menu";
    menu.id = "menu";
    menu.innerHTML = `<nav aria-label="Menu">${[["", "Home"], ...LINKS, ["download", "Download"]].map(([id, label], i) =>
      `<a href="/${id}" style="--i:${i}"${page === (id || "home") ? ' class="active"' : ""}>${label}</a>`).join("")}</nav>
      <div class="menu-auth" data-auth-menu><a class="btn btn-ghost" href="/account">Sign in</a><a class="btn btn-primary" href="/account?signup">Create account</a></div>
      <p class="menu-foot">AFH <span data-version>1.21.0</span> · Windows, Mac and terminal</p>`;
    nav.after(menu);
    nav.querySelector(".theme-btn").addEventListener("click", () => window.afhTheme.set(window.afhTheme.get() === "dark" ? "light" : "dark"));
    const burger = nav.querySelector(".burger");
    const toggle = (open) => {
      document.documentElement.classList.toggle("menu-open", open);
      burger.setAttribute("aria-expanded", String(open));
    };
    burger.addEventListener("click", () => toggle(!document.documentElement.classList.contains("menu-open")));
    menu.addEventListener("click", (e) => { if (e.target.closest("a")) toggle(false); });
    addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
    // signed in to the AFH account (an HttpOnly cookie this page can't read): ask the relay
    if (!document.body.hasAttribute("data-no-auth")) {
      fetch("/relay/api/me", { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : null))
        .then((me) => {
          if (!me?.user) return;
          window.afhMe = me;
          const email = me.user.email || "";
          const initial = (email[0] || "A").toUpperCase();
          const online = (me.computers || []).filter((c) => c.online).length;
          nav.querySelector("[data-auth]").innerHTML = `
            <a class="nav-me${page === "chat" ? " active" : ""}" href="/chat" title="${email.replace(/"/g, "&quot;")}">
              <span class="nav-avatar">${initial}</span><span class="nav-me-label">Open chat</span>${online ? `<span class="nav-online" title="${online} online"></span>` : ""}
            </a>`;
          menu.querySelector("[data-auth-menu]").innerHTML = `<a class="btn btn-primary" href="/chat">Open chat</a>`;
          document.documentElement.classList.add("signed-in");
          document.dispatchEvent(new CustomEvent("afh:me", { detail: me }));
        })
        .catch(() => {});
    }
    const onScroll = () => nav.classList.toggle("scrolled", scrollY > 40);
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  const footer = document.querySelector("[data-footer]");
  if (footer) {
    footer.className = "footer";
    footer.innerHTML = `
      <div class="footer-top">
        <div class="footer-brand">
          <a class="brand" href="/">${MARK}<span>Agent Flow Harness</span></a>
          <p>A coding agent that plans, delegates and writes code on your own computer, with the models you choose. As an app or in your terminal.</p>
          <a class="footer-release" href="/changelog"><span class="dot"></span>Version <span data-version>1.21.0</span> · <span data-date>Nov 3, 2026</span></a>
        </div>
        <nav class="footer-cols" aria-label="Footer">
          <div><h4>Product</h4><a href="/features">Features</a><a href="/features#modes">Modes</a><a href="/cli">Terminal</a><a href="/models">Models</a><a href="/download">Download</a><a href="/changelog">Changelog</a></div>
          <div><h4>Use it</h4><a href="/docs">Getting started</a><a href="/docs#providers">Add a provider</a><a href="/chat">Web chat</a><a href="/computers">Your computers</a><a href="/account?signup">Create account</a></div>
          <div><h4>Developers</h4><a href="/api">API reference</a><a href="/sdk/afh_sdk.py" download>Python SDK</a><a href="/sdk/afh.mjs" download>JavaScript SDK</a><a href="/api#events">Live events</a><a href="/docs#faq">FAQ</a></div>
        </nav>
      </div>
      <div class="footer-bottom">
        <p>© 2026 Agent Flow Harness</p>
        <p>Runs on your computer · no account needed · no tracking scripts</p>
      </div>`;
  }

  // the download button speaks to the system you're on: <a data-os-cta>, words in data-os-label
  const RELEASES = "https://github.com/Lucifer-xD/agent-flow-harness/releases/latest/download";
  const ICONS = {
    windows: "M3 5.5 10.5 4.4v7.1H3zm0 13 7.5 1.1v-7H3zm8.4 1.2L21 21v-8.5h-9.6zm0-15.4v7.2H21V3z",
    mac: "M16.4 12.6c0-2.2 1.8-3.3 1.9-3.3-1-1.5-2.6-1.7-3.2-1.7-1.3-.1-2.6.8-3.3.8-.7 0-1.7-.8-2.8-.8-1.4 0-2.8.8-3.5 2.1-1.5 2.6-.4 6.5 1.1 8.6.7 1 1.6 2.2 2.7 2.1 1.1 0 1.5-.7 2.8-.7s1.7.7 2.8.7c1.2 0 1.9-1 2.6-2.1.8-1.2 1.2-2.4 1.2-2.4s-2.3-.9-2.3-3.3ZM14.300 6.100c.6-.7 1-1.700.9-2.700-.9 0-1.900.6-2.600 1.300-.5.700-1 1.700-.9 2.600 1 .1 2-.5 2.600-1.200Z",
    terminal: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm2.300 3.300L5 9.600 7.400 12 5 14.400l1.300 1.300L10 12 6.300 8.300ZM11 15v1.800h6V15h-6Z",
    phone: "M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm0 3v13h8V5H8Zm4 14.200a.9.9 0 1 0 0 1.800.9.9 0 0 0 0-1.800Z",
  };
  const ua = navigator.userAgent;
  const system = /Android|iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? "phone" : /Mac OS X|Macintosh/.test(ua) ? "mac" : /Windows/.test(ua) ? "windows" : /Linux|X11|CrOS/.test(ua) ? "linux" : "other";
  const dress = (a, icon, label, href) => {
    a.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="${ICONS[icon]}"/></svg>${label}`;
    a.href = href;
  };
  const buttons = document.querySelectorAll("[data-os-cta]");
  buttons.forEach((a) => {
    if (system === "windows") dress(a, "windows", "Download for Windows", "/download");
    else if (system === "mac") dress(a, "mac", "Download for Mac", "/download#desktop");
    else if (system === "linux") dress(a, "terminal", "Install in your terminal", "/cli");
    else if (system === "phone") dress(a, "phone", "Get the app", "/download#phone");
  });
  document.documentElement.dataset.os = system;
  if (system === "mac" && navigator.userAgentData?.getHighEntropyValues) {
    navigator.userAgentData.getHighEntropyValues(["architecture"]).then(({ architecture }) => {
      const chip = architecture === "arm" ? "arm64" : architecture === "x86" ? "x64" : "";
      if (chip) buttons.forEach((a) => { a.href = `${RELEASES}/AFH-mac-${chip}.dmg`; });
    }).catch(() => {});
  }

  // the one-line install, with a tab per system: <div data-install></div>
  const INSTALL = [
    ["windows", "Windows", "irm https://agentflowharness.com/install.ps1 | iex", "PowerShell"],
    ["cmd", "CMD", "curl -fsSL https://agentflowharness.com/install.cmd -o install.cmd && .\\install.cmd && del install.cmd", "Command Prompt"],
    ["mac", "macOS", "curl -fsSL https://agentflowharness.com/install.sh | bash", "Terminal"],
    ["linux", "Linux", "curl -fsSL https://agentflowharness.com/install.sh | bash", "Terminal"],
  ];
  document.querySelectorAll("[data-install]").forEach((box) => {
    box.className = "install";
    box.innerHTML = `<div class="install-tabs" role="tablist" aria-label="Your system">${INSTALL.map(([id, label]) => `<button type="button" role="tab" data-tab="${id}">${label}</button>`).join("")}</div>
      <div class="install-line"><span class="install-prompt" aria-hidden="true">&gt;</span><code></code><button class="install-copy" type="button">Copy</button></div>`;
    const code = box.querySelector("code");
    const show = (id) => {
      const row = INSTALL.find((x) => x[0] === id) || INSTALL[0];
      code.textContent = row[2];
      box.querySelectorAll("[data-tab]").forEach((b) => { const on = b.dataset.tab === row[0]; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    };
    show(system);
    box.addEventListener("click", (e) => {
      const tab = e.target.closest("[data-tab]");
      if (tab) show(tab.dataset.tab);
      const copy = e.target.closest(".install-copy");
      if (copy) navigator.clipboard.writeText(code.textContent).then(() => { copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy"; }, 1400); }, () => { copy.textContent = "Select it"; });
    });
  });

  // pictures of the app match the theme: <img src="light" data-dark="dark">
  const themed = () => document.querySelectorAll("img[data-dark]").forEach((img) => {
    img.dataset.light ||= img.getAttribute("src");
    const src = window.afhTheme.get() === "dark" ? img.dataset.dark : img.dataset.light;
    if (img.getAttribute("src") !== src) img.src = src;
  });
  themed();
  document.addEventListener("afh:theme", themed);

  // entrances
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { rootMargin: "0px 0px -8% 0px" });
  document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));

  // a section menu (.subnav) marks the section you're reading
  const sub = document.querySelector(".subnav");
  if (sub) {
    const items = new Map([...sub.querySelectorAll("a")].map((a) => [a.getAttribute("href").slice(1), a]));
    const spy = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) items.forEach((a, id) => {
        a.classList.toggle("on", id === e.target.id);
        if (id === e.target.id) sub.scrollTo({ left: a.offsetLeft - sub.clientWidth / 2 + a.clientWidth / 2, behavior: "smooth" });
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    items.forEach((_, id) => { const s = document.getElementById(id); if (s) spy.observe(s); });
  }

  // cards light up under the pointer
  document.addEventListener("pointermove", (e) => {
    const card = e.target.closest?.(".fcard, .tile");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, { passive: true });

  // ---- the current release, from the updater's own feed ----
  const fmtSize = (b) => `${Math.round(b / 1048576)} MB`;
  const fmtDate = (d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  fetch("/downloads/latest.yml", { cache: "no-cache" })
    .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
    .then((yml) => {
      const get = (k) => (yml.match(new RegExp(`^${k}:\\s*'?([^'\\n]+)'?`, "m")) || [])[1];
      const size = Number((yml.match(/^\s+size:\s*(\d+)/m) || [])[1]);
      const rel = { version: get("version"), file: get("path"), sha: get("sha512"), date: get("releaseDate") };
      if (!rel.version || !rel.file) return;
      const set = (sel, text) => document.querySelectorAll(sel).forEach((el) => { el.textContent = text; });
      set("[data-version]", rel.version);
      set("[data-file]", rel.file);
      if (size) set("[data-size]", fmtSize(size));
      if (rel.date) set("[data-date]", fmtDate(rel.date));
      if (rel.sha) set("[data-sha]", rel.sha);
      document.querySelectorAll("[data-download]").forEach((a) => { a.href = `/downloads/${rel.file}`; });
      window.afhRelease = { ...rel, size }; // for scripts that load later
      document.dispatchEvent(new CustomEvent("afh:release", { detail: window.afhRelease }));
    })
    .catch(() => {});
})();
