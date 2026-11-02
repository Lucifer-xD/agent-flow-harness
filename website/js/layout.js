// Every page's header, phone menu and footer, written once here. Pages hold <header data-nav>
// and <footer data-footer> placeholders and set <body data-page="…"> to mark their nav link.
// It also runs the entrances ([data-reveal]), section menus (.subnav) and card glows, and
// fills in the current release from downloads/latest.yml (the file the app's updater
// reads), so the version, size, date and checksum shown anywhere are always the real ones.
(() => {
  const page = document.body.dataset.page || "";
  const LINKS = [["features", "Features"], ["models", "Models"], ["docs", "Docs"], ["api", "API"], ["changelog", "Changelog"]];
  const link = ([id, label]) => `<a href="/${id}"${page === id ? ' class="active" aria-current="page"' : ""}>${label}</a>`;
  const MARK = '<img src="/assets/mark.svg" alt="" width="34" height="20">';

  const nav = document.querySelector("[data-nav]");
  if (nav) {
    nav.className = "nav";
    nav.innerHTML = `
      <a class="brand" href="/">${MARK}<span>Agent Flow Harness</span></a>
      <nav class="nav-links" aria-label="Main">${LINKS.map(link).join("")}</nav>
      <span class="nav-auth" data-auth>
        <a class="nav-signin" href="/account">Sign in</a>
        <a class="btn btn-small btn-ghost nav-signup" href="/account?signup">Sign up</a>
      </span>
      <a class="btn btn-small nav-cta${page === "download" ? " active" : ""}" href="/download">Download</a>
      <button class="burger" type="button" aria-label="Menu" aria-expanded="false" aria-controls="menu"><i></i><i></i></button>`;
    const menu = document.createElement("div");
    menu.className = "menu";
    menu.id = "menu";
    menu.innerHTML = `<nav aria-label="Menu">${[["", "Home"], ...LINKS, ["download", "Download"]].map(([id, label], i) =>
      `<a href="/${id}" style="--i:${i}"${page === (id || "home") ? ' class="active"' : ""}>${label}</a>`).join("")}</nav>
      <div class="menu-auth" data-auth-menu><a class="btn btn-ghost" href="/account">Sign in</a><a class="btn btn-primary" href="/account?signup">Create account</a></div>
      <p class="menu-foot">AFH <span data-version>1.12.0</span> · Windows 10/11</p>`;
    nav.after(menu);
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
          <p>A desktop coding agent that plans, delegates and writes code with the models you choose.</p>
          <a class="footer-release" href="/changelog"><span class="dot"></span>Version <span data-version>1.12.0</span> · <span data-date>Nov 2, 2026</span></a>
        </div>
        <nav class="footer-cols" aria-label="Footer">
          <div><h4>Product</h4><a href="/features">Features</a><a href="/models">Models</a><a href="/download">Download</a><a href="/changelog">Changelog</a><a href="/chat">Chat</a><a href="/computers">Computers</a><a href="/account?signup">Create account</a></div>
          <div><h4>Learn</h4><a href="/docs">Getting started</a><a href="/docs#providers">Add a provider</a><a href="/docs#shortcuts">Shortcuts</a><a href="/docs#faq">FAQ</a></div>
          <div><h4>Developers</h4><a href="/api">API reference</a><a href="/sdk/afh_sdk.py" download>Python SDK</a><a href="/sdk/afh.mjs" download>JavaScript SDK</a><a href="/api#events">Live events</a></div>
        </nav>
      </div>
      <div class="footer-bottom">
        <p>© 2026 Agent Flow Harness</p>
        <p>Runs on your PC · no account needed · no telemetry</p>
      </div>`;
  }

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
    const card = e.target.closest?.(".fcard");
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
