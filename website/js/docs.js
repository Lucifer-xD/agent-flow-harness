// The API reference page: code tabs, copy buttons, light syntax colouring, the table of
// contents following the scroll, and a soft entrance for the header.
(() => {
  // tabs (Python / JavaScript / curl)
  for (const tabs of document.querySelectorAll(".tabs")) {
    const buttons = tabs.querySelectorAll(".tab-bar button");
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((x) => x.classList.toggle("on", x === b));
      tabs.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== b.dataset.tab; });
    }));
  }

  // syntax colouring: comments, strings, numbers and a few keywords — enough to read at a glance
  const KEYWORDS = /\b(from|import|await|async|const|let|for|of|in|if|elif|else|while|print|return|def|class|True|False|None|null|true|false|new|break|process)\b/g;
  const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const TOKEN = /(#![^\n]*|#[^\n{]*$|\/\/[^\n]*|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|\b\d+(?:\.\d+)?\b)/gm;
  for (const code of document.querySelectorAll(".code pre code")) {
    const lang = code.closest(".code").dataset.lang || "";
    if (/^(response|~\/)/.test(lang) || code.textContent.startsWith("{")) {
      code.innerHTML = escape(code.textContent).replace(/(&quot;|")((?:[^"\\]|\\.)*)"(\s*:)/g, '<span class="tok-k">"$2"</span>$3');
      continue;
    }
    const src = code.textContent;
    let out = "";
    let last = 0;
    for (const m of src.matchAll(TOKEN)) {
      out += escape(src.slice(last, m.index)).replace(KEYWORDS, '<span class="tok-k">$1</span>');
      const t = m[0];
      const cls = t.startsWith("#") || t.startsWith("//") ? "tok-c" : /^\d/.test(t) ? "tok-n" : "tok-s";
      out += `<span class="${cls}">${escape(t)}</span>`;
      last = m.index + t.length;
    }
    code.innerHTML = out + escape(src.slice(last)).replace(KEYWORDS, '<span class="tok-k">$1</span>');
  }

  // copy buttons
  for (const block of document.querySelectorAll(".code")) {
    const btn = document.createElement("button");
    btn.className = "copy";
    btn.type = "button";
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(block.querySelector("code").textContent);
        btn.textContent = "Copied";
      } catch {
        btn.textContent = "Select and copy";
      }
      setTimeout(() => { btn.textContent = "Copy"; }, 1400);
    });
    block.append(btn);
  }

  // table of contents follows the section in view
  const links = new Map([...document.querySelectorAll(".toc a")].map((a) => [a.getAttribute("href").slice(1), a]));
  const spy = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      links.forEach((a, id) => a.classList.toggle("on", id === e.target.id));
    }
  }, { rootMargin: "-30% 0px -60% 0px" });
  document.querySelectorAll(".doc section[id]").forEach((s) => spy.observe(s));

  // header entrance and nav shadow
  const hero = document.querySelectorAll(".docs-hero > *");
  hero.forEach((el, i) => {
    el.classList.add("reveal");
    setTimeout(() => el.classList.add("in"), 80 + i * 110);
  });
})();
