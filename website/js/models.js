// The Models page's provider directory: every provider AFH knows (data/providers.json, written by
// scripts/website-data.py), searchable and filterable, shown a page at a time.
const grid = document.querySelector("[data-providers]");
const count = document.querySelector("[data-count-label]");
const more = document.querySelector("[data-more]");
const search = document.querySelector("[data-search]");
const sort = document.querySelector("[data-sort]");
const PAGE = 48;
const GRADS = [["#ffb11f", "#ff6a2a"], ["#ff7747", "#ff3d8a"], ["#ff3d8a", "#e0169a"], ["#ff4a68", "#ffb11f"], ["#e0169a", "#ff7747"]];
const FILTERS = {
  all: () => true,
  featured: (p) => p.featured,
  login: (p) => p.login,
  local: (p) => p.local,
  reasoning: (p) => p.reasoning > 0,
  vision: (p) => p.vision > 0,
};
let all = [];
let filter = "all";
let shown = PAGE;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
const plural = (n, w) => `${n.toLocaleString("en-US")} ${w}${n === 1 ? "" : "s"}`;

function cardHtml(p, i) {
  const [a, b] = GRADS[hash(p.id) % GRADS.length];
  const initials = p.name.replace(/\(.*?\)/g, "").trim().split(/[\s.\-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const chips = [
    p.login && '<span class="badge hot">Sign in</span>',
    p.local && '<span class="badge green">On your PC</span>',
    p.reasoning > 0 && '<span class="badge pink">Reasoning</span>',
    p.vision > 0 && '<span class="badge blue">Sees images</span>',
  ].filter(Boolean).join("");
  const models = p.local ? "Models on your PC" : p.login ? "Sign in or API key" : "API key";
  return `<article class="pcard" style="--i:${i}">
    <div class="pcard-top"><span class="pav" style="background:linear-gradient(135deg,${a},${b})">${esc(initials || "?")}</span>
      <div class="pname"><b title="${esc(p.name)}">${esc(p.name)}</b><span>${esc(models)}</span></div></div>
    ${chips ? `<div class="chips">${chips}</div>` : ""}
    ${p.docs ? `<a class="docs" href="${esc(p.docs)}" target="_blank" rel="noopener noreferrer">Docs ↗</a>` : ""}
  </article>`;
}

function render() {
  const q = search.value.trim().toLowerCase();
  let list = all.filter(FILTERS[filter]).filter((p) => !q || p.name.toLowerCase().includes(q) || p.id.includes(q));
  if (sort.value === "name") list = [...list].sort((x, y) => x.name.localeCompare(y.name));
  count.textContent = `Showing ${Math.min(shown, list.length).toLocaleString("en-US")} of ${plural(list.length, "provider")}`;
  grid.innerHTML = list.length ? list.slice(0, shown).map(cardHtml).join("") : '<p class="empty">No provider matches. Any OpenAI-compatible endpoint works as a custom provider.</p>';
  more.hidden = list.length <= shown;
}

document.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
  filter = b.dataset.filter;
  shown = PAGE;
  document.querySelectorAll("[data-filter]").forEach((x) => x.classList.toggle("on", x === b));
  render();
}));
search.addEventListener("input", () => { shown = PAGE; render(); });
sort.addEventListener("change", render);
more.addEventListener("click", () => { shown += PAGE * 2; render(); });

fetch("/data/providers.json")
  .then((r) => r.json())
  .then((d) => {
    all = d.providers;
    document.querySelectorAll("[data-total-providers]").forEach((el) => { el.textContent = all.length.toLocaleString("en-US"); });
    render();
  })
  .catch(() => { count.textContent = "The provider list couldn't be loaded."; });
