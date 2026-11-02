// The owner's analytics (admin.html): downloads per app, apps in use, website visitors.
// Numbers come from /relay/api/admin/stats, which only answers the site owner's account.
(() => {
  const root = document.getElementById("adm");
  const PLATFORMS = [["windows", "Windows"], ["android", "Android"], ["ios", "iPhone"]];
  const NAMES = Object.fromEntries(PLATFORMS);
  const fmt = (n) => Number(n || 0).toLocaleString("en-US");
  let days = 30;
  try { days = Number(localStorage.getItem("afh-admin-days")) || 30; } catch {}

  function h(tag, attrs, ...kids) {
    const [name, ...classes] = tag.split(".");
    const n = document.createElement(name);
    if (classes.length) n.className = classes.join(" ");
    if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) kids.unshift(attrs);
    else if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "style") n.style.cssText = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) n.append(k instanceof Node ? k : String(k));
    return n;
  }
  const svg = (tag, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    return n;
  };
  const key = (color) => h("i.adm-key", { style: `background:${color}` });
  const dayLabel = (d) => new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

  async function load() {
    let res;
    try {
      res = await fetch(`/relay/api/admin/stats?days=${days}`, { credentials: "same-origin" });
    } catch {
      return message("Couldn't reach the server. Check your connection and reload.");
    }
    if (res.status === 404 || res.status === 401) {
      const me = await fetch("/relay/api/me", { credentials: "same-origin" }).catch(() => null);
      if (!me || me.status === 401) return message("Sign in with the site owner's account to see the analytics.", "/account?next=/admin", "Sign in");
      return message("This page is only for the site owner.");
    }
    if (!res.ok) return message(`The server answered ${res.status}. Try again in a minute.`);
    render(await res.json());
  }

  function message(text, href, label) {
    root.replaceChildren(h("p.adm-msg", text, href ? [" ", h("a", { href }, label)] : null));
  }

  /** A round axis step (1, 2, 5, 10, 20, 50...) that splits `max` into about four bands. */
  function niceStep(max) {
    const raw = max / 4, mag = 10 ** Math.floor(Math.log10(raw || 1));
    return Math.max(1, [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw));
  }

  /** Daily bars; `series` = [{name, color, values[]}] stacks, one series is a plain bar chart.
   *  Drawn at the box's real width (and again when it changes), so text and bars keep their shape. */
  function bars(daysList, series) {
    const box = h("div.adm-chart");
    let drawnAt = 0;
    const draw = () => {
      const W = Math.round(box.clientWidth);
      if (!W || W === drawnAt) return;
      drawnAt = W;
      box.replaceChildren(chartSvg(box, W, daysList, series));
    };
    new ResizeObserver(draw).observe(box);
    return box;
  }

  function chartSvg(box, W, daysList, series) {
    const H = 170, top = 8, bottom = 22, left = 34;
    const totals = daysList.map((_, i) => series.reduce((s, x) => s + x.values[i], 0));
    const max = Math.max(1, ...totals);
    const step = niceStep(max);
    const ceil = step * Math.ceil(max / step);
    const y = (v) => top + (H - top - bottom) * (1 - v / ceil);
    const slot = (W - left) / daysList.length;
    const bw = Math.max(2, Math.min(24, slot - Math.max(2, slot * 0.3)));
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
    for (let v = 0; v <= ceil; v += step) {
      chart.append(svg("line", { x1: left, x2: W, y1: y(v), y2: y(v), class: "grid" }));
      const t = svg("text", { x: left - 8, y: y(v) + 3.5, "text-anchor": "end", class: "axis" });
      t.textContent = fmt(v);
      chart.append(t);
    }
    const labelEvery = Math.ceil(daysList.length / Math.max(2, Math.floor((W - left) / 70)));
    daysList.forEach((d, i) => {
      const x = left + i * slot + (slot - bw) / 2;
      let base = 0;
      const parts = series.map((s) => ({ s, v: s.values[i] })).filter((p) => p.v > 0);
      parts.forEach((p, j) => {
        const y0 = y(base), y1 = y(base + p.v);
        const gap = j > 0 ? 2 : 0; // a surface gap between stacked segments
        const hgt = Math.max(0, y0 - y1 - gap);
        const r = j === parts.length - 1 ? Math.min(4, hgt, bw / 2) : 0; // only the data end is rounded
        chart.append(svg("path", { style: `fill:${p.s.color}`, d: `M${x},${y0 - gap}V${y0 - gap - hgt + r}q0,-${r} ${r},-${r}h${bw - 2 * r}q${r},0 ${r},${r}V${y0 - gap}Z` }));
        base += p.v;
      });
      if ((daysList.length - 1 - i) % labelEvery === 0) {
        const t = svg("text", { x: Math.min(W - 22, left + i * slot + slot / 2), y: H - 5, "text-anchor": "middle", class: "axis" });
        t.textContent = dayLabel(d);
        chart.append(t);
      }
      const hit = svg("rect", { x: left + i * slot, y: 0, width: slot, height: H - bottom, class: "hit" });
      hit.addEventListener("mouseenter", () => tip(box, left + (i + 0.5) * slot, d, series, i));
      hit.addEventListener("mouseleave", () => box.querySelector(".adm-tip")?.remove());
      chart.append(hit);
    });
    return chart;
  }

  function tip(box, center, d, series, i) {
    box.querySelector(".adm-tip")?.remove();
    const t = h("div.adm-tip", h("b", dayLabel(d)),
      series.map((s) => h("span", series.length > 1 ? key(s.color) : null, s.name, h("em", fmt(s.values[i])))));
    box.append(t);
    const x = Math.min(Math.max(0, center - t.offsetWidth / 2), box.clientWidth - t.offsetWidth);
    t.style.left = `${x}px`;
    t.style.top = `-${t.offsetHeight - 4}px`;
  }

  function table(rows, label = (k) => k, withBars = true) {
    if (!rows.length) return h("p.adm-empty", "Nothing yet.");
    const max = Math.max(...rows.map((r) => r.n));
    return h("table.adm-table", h("tbody", rows.map((r) => h("tr",
      h("td", label(r.key), withBars ? h("i.bar", { style: `width:${Math.max(2, (r.n / max) * 100)}%` }) : null), h("td", fmt(r.n))))));
  }

  function tile(label, value, sub, extra) {
    return h("div.adm-card", h("div.adm-tile-label", label), h("div.adm-tile-value", fmt(value)), sub ? h("div.adm-tile-sub", sub) : null, extra || null);
  }

  function render(s) {
    const dl = s.downloads, site = s.site, acc = s.accounts;
    const list = site.daily.map((d) => d.day);
    const dlRange = PLATFORMS.reduce((n, [p]) => n + (dl.range[p] || 0), 0);
    const range = h("div.adm-range", [7, 30, 90].map((n) => h(`button${n === days ? ".on" : ""}`, { type: "button", onclick: () => {
      days = n;
      try { localStorage.setItem("afh-admin-days", String(n)); } catch {}
      load();
    } }, `${n} days`)));
    const updated = new Date(s.updated * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const versionLabel = (k) => { const [p, v] = k.split(" "); return h("span", key(`var(--${p})`), " ", NAMES[p] || p, " ", h("span.mono", v)); };

    root.replaceChildren(
      h("div.adm-head", h("div", h("h1", "Analytics"), h("p", `Last ${days} days · updated ${updated}`)), range),
      h("div.adm-tiles",
        tile("Downloads", dlRange, `${fmt(PLATFORMS.reduce((n, [p]) => n + (dl.total[p] || 0), 0))} since counting began`,
          h("div.adm-split", PLATFORMS.map(([p, name]) => h("span", key(`var(--${p})`), `${name} ${fmt(dl.range[p])}`)))),
        tile("Windows apps in use", s.desktop.range, `${fmt(s.desktop.today)} today · ${fmt(s.desktop.week)} in the last 7 days`),
        tile("Phone apps in use", s.phone.range, `Signed-in phones · ${fmt(acc.phones)} signed in now`),
        tile("Website visitors", site.range, `${fmt(site.today)} today · ${fmt(site.views)} page views`)),
      h("div.adm-grid",
        h("div.adm-card.adm-wide", h("h2", "Website visitors per day"), h("p.adm-note", "People, not page loads: each browser counts once a day. Search engines and bots are left out."),
          bars(list, [{ name: "Visitors", color: "var(--one)", values: site.daily.map((d) => d.visitors) }])),
        h("div.adm-card", h("h2", "Downloads per day"),
          h("div.adm-legend", PLATFORMS.map(([p, name]) => h("span", key(`var(--${p})`), name))),
          bars(list, PLATFORMS.map(([p, name]) => ({ name, color: `var(--${p})`, values: dl.daily.map((d) => d[p]) })))),
        h("div.adm-card", h("h2", "Windows apps open per day"), h("p.adm-note", "Installed desktop apps that checked for updates that day."),
          bars(list, [{ name: "Windows apps", color: "var(--windows)", values: s.desktop.daily.map((d) => d.n) }])),
        h("div.adm-card", h("h2", "Downloads by version"), h("p.adm-note", "Since counting began."), table(dl.versions, versionLabel)),
        h("div.adm-card", h("h2", "Accounts"), table([
          { key: "Accounts", n: acc.users }, { key: "New accounts in the last 7 days", n: acc.usersWeek },
          { key: "Computers linked", n: acc.computers }, { key: "Computers online now", n: acc.online },
          { key: "Phones signed in", n: acc.phones },
          ...acc.versions.map((v) => ({ key: `Desktop ${v.key} (linked, last 7 days)`, n: v.n })),
        ], undefined, false)),
        h("div.adm-card", h("h2", "Most read pages"), table(site.pages)),
        h("div.adm-card", h("h2", "Where visitors came from"), h("p.adm-note", "Other sites that linked here. Visitors who typed the address aren't listed."), table(site.referrers))),
      h("p.adm-foot", `Read from the website's server logs every 5 minutes, counting from ${s.since ? dayLabel(s.since) : "today"}. No cookies or tracking scripts are used, and addresses are only kept as salted hashes. `,
        "Phone apps are only counted when signed in to an account; they send nothing otherwise. The website and phone apps don't report which phone platform is in use, so phone use isn't split by Android and iPhone."),
    );
  }

  load();
})();
