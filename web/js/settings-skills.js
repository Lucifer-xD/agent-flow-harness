// Settings → Skills: browse skills.sh, install with one click, manage what's installed.

import { api } from "./api.js";
import { basename, confirmDialog, el, ico, icon, markdown, popover, toast } from "./ui.js";

const fmtInstalls = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0));

export async function skillsPane(pane, ctx) {
  const project = ctx.project();
  pane.append(el("h2", "Skills"), el("p.lead", "Skills are reusable instruction packs the agent loads on demand — from skills.sh, the open skill registry used by Claude Code, Codex and Cursor. One click installs; the agent uses it on the next message."));

  // ---- installed
  const installedBox = el("div");
  const drawInstalled = async () => {
    installedBox.replaceChildren(el("div.empty-row", el("span.spinner")));
    let list = [];
    try { list = await api.get(api.q("/api/skills/installed", { directory: project })); } catch (e) { installedBox.replaceChildren(el("div.empty-row", e.message)); return; }
    installedBox.replaceChildren();
    if (!list.length) installedBox.append(el("div.empty-row", "Nothing installed yet."));
    for (const s of list) {
      installedBox.append(el("div.list-item", ico("book"),
        el("div.li-main", el("div.li-title", s.name || s.slug, el("span.pill-tag", s.scope), s.managed ? null : el("span.pill-tag", "manual"), s.updateAvailable ? el("span.pill-tag.accent", "update") : null),
          el("div.li-sub", { style: { fontFamily: "var(--font)", whiteSpace: "normal" } }, s.description || s.source || s.path || "")),
        s.scope !== "external" ? el("button.btn.ghost.sm.danger", { title: "Remove", on: { click: async () => {
          if (!(await confirmDialog({ title: `Remove ${s.name || s.slug}?`, body: "The skill's folder is deleted. You can reinstall it from the store.", confirm: "Remove", danger: true }))) return;
          try { await api.del("/api/skills", { slug: s.slug, scope: s.scope, directory: project }); toast("Removed", "ok"); drawInstalled(); drawResults(); } catch (e) { toast(e.message, "err"); }
        } } }, ico("trash")) : null));
    }
    installedSlugs = new Set(list.map((s) => s.slug));
  };
  let installedSlugs = new Set();
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Installed"), el("p", "Global skills live in ~/.afh/skills; project skills in .afh/skills (Claude/Agents/OpenCode skill folders are read too)")),
    el("button.btn.sm", { on: { click: async () => { try { const u = await api.post("/api/skills/check-updates", { directory: project }); toast(u.length ? `${u.length} update${u.length > 1 ? "s" : ""} available` : "Everything is up to date", "ok"); drawInstalled(); } catch (e) { toast(e.message, "err"); } } } }, ico("refresh"), "Check updates")), installedBox));

  // ---- store
  let view = "trending";
  let query = "";
  const search = el("input.inp", { placeholder: "Search thousands of skills — e.g. react, playwright, pdf, security review…", on: { input: () => { query = search.value.trim(); clearTimeout(search._t); search._t = setTimeout(drawResults, 350); } } });
  const tabs = el("div.seg");
  for (const [v, label] of [["trending", "Trending"], ["hot", "Hot"], ["all-time", "Most installed"], ["curated", "Official"]]) {
    tabs.append(el(`button${v === view ? ".on" : ""}`, { type: "button", on: { click: (e) => { view = v; tabs.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); drawResults(); } } }, label));
  }
  const results = el("div.skill-grid");
  const detailBox = el("div");
  const drawResults = async () => {
    results.replaceChildren(el("div.empty-row", el("span.spinner")));
    try {
      let items = [];
      if (query.length >= 2) items = (await api.get(api.q("/api/skills/search", { q: query, limit: 40 }))).data || [];
      else if (view === "curated") items = ((await api.get("/api/skills/curated")).data || []).flatMap((o) => (o.skills || []).map((s) => ({ ...s, source: s.source || `${o.owner}/${o.featuredRepo || ""}`, official: true })));
      else items = (await api.get(api.q("/api/skills/browse", { view, page: 0 }))).data || [];
      results.replaceChildren();
      if (!items.length) results.append(el("div.empty-row", "No skills found."));
      for (const s of items.slice(0, 60)) results.append(skillCard(s));
    } catch (e) {
      results.replaceChildren(el("div.empty-row", `Couldn't reach skills.sh: ${e.message}`));
    }
  };
  const skillCard = (s) => {
    const slug = s.slug || s.skillId || s.id?.split("/").pop();
    const installed = installedSlugs.has(slug);
    const card = el("div.skill",
      el("div.skill-head", el("div.skill-name", s.name || slug, s.official || s.isOfficial ? el("span.pill-tag.accent", "official") : null), el("span.skill-installs", ico("arrow-down"), fmtInstalls(s.installs))),
      el("div.skill-src", s.source || ""),
      el("div.skill-actions",
        el("button.btn.ghost.sm", { on: { click: () => showDetail(s, slug) } }, "Details"),
        installed ? el("span.pill-tag", ico("check"), " installed") : el("button.btn.primary.sm", { on: { click: (e) => installMenu(e.currentTarget, s, slug) } }, ico("plus"), "Install")));
    return card;
  };
  const installMenu = (anchor, s, slug) => popover(anchor, [
    { title: "Install for all projects", sub: "~/.afh/skills", icon: "globe", onSelect: () => install(s, slug, "global") },
    project ? { title: `Install for ${basename(project)} only`, sub: ".afh/skills in this project", icon: "folder", onSelect: () => install(s, slug, "project") } : null,
  ].filter(Boolean), { width: 300 });
  const install = async (s, slug, scope) => {
    toast(`Installing ${s.name || slug}…`, "info", 1500);
    try {
      await api.post("/api/skills/install", { source: s.source, slug, scope, directory: project });
      toast(`${s.name || slug} installed — mention @${slug} or just ask; the agent will use it`, "ok", 4000);
      await drawInstalled();
      drawResults();
    } catch (e) {
      toast(e.message, "err", 6000);
    }
  };
  const showDetail = async (s, slug) => {
    detailBox.replaceChildren(el("div.inline-form", el("div.empty-row", el("span.spinner"))));
    try {
      const { detail, audit } = await api.get(api.q("/api/skills/detail", { source: s.source, slug }));
      const skillMd = (detail.files || []).find((f) => /(^|\/)SKILL\.md$/i.test(f.path));
      const worst = (audit?.audits || []).map((a) => a.status).includes("fail") ? "fail" : (audit?.audits || []).map((a) => a.status).includes("warn") ? "warn" : audit?.audits?.length ? "pass" : null;
      detailBox.replaceChildren(el("div.inline-form",
        el("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" } },
          el("b", s.name || slug), el("span.pill-tag", s.source), el("span.pill-tag", `${fmtInstalls(detail.installs ?? s.installs)} installs`),
          worst ? el(`span.pill-tag${worst === "pass" ? ".accent" : ""}`, { title: (audit.audits || []).map((a) => `${a.provider}: ${a.summary || a.status}`).join("\n") }, ico(worst === "pass" ? "shield-check" : "alert"), ` security audit: ${worst}`) : el("span.pill-tag", "no audit yet"),
          el("span", { style: { flex: 1 } }),
          installedSlugs.has(slug) ? el("span.pill-tag", "installed") : el("button.btn.primary.sm", { on: { click: (e) => installMenu(e.currentTarget, s, slug) } }, ico("plus"), "Install"),
          el("button.icon-btn", { html: icon("x"), on: { click: () => detailBox.replaceChildren() } })),
        el("div.tool-section-label", `${(detail.files || []).length} files: ${(detail.files || []).map((f) => f.path).slice(0, 8).join(", ")}${(detail.files || []).length > 8 ? "…" : ""}`),
        el("div.skill-md.md", { html: markdown(skillMd?.contents || "_No SKILL.md in this skill._") })));
      detailBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      detailBox.replaceChildren(el("div.inline-form", el("div.empty-row", e.message)));
    }
  };
  pane.append(el("div.card", el("div.card-head", el("div", el("h3", "Skill store"), el("p", "Powered by skills.sh")), tabs), el("div.card-body", search, results), detailBox));
  await drawInstalled();
  drawResults();
}
