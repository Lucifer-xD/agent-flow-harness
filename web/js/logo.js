// The AFH mark: three flow strands (orange → coral → magenta). Each leaves its dot, runs flat,
// weaves through a wide middle zone and returns to its own height. `working` adds pulses that
// travel along the strands and end dots that breathe as a pulse arrives.

let uid = 0;

// Top dips to just below the middle row right of centre, bottom rises to just above it left of
// centre, and the middle strand makes a gentle S — so the three cross each other in a wide
// zone instead of meeting at one knot.
const STRANDS = [
  { y: 28, from: "#ffb11f", to: "#ff7a3d", d: "M46 28 C104 28 108 74 134 74 C160 74 164 28 194 28" },
  { y: 70, from: "#ff7747", to: "#ff4a68", d: "M46 70 C92 70 98 58 120 60 C150 63 152 82 194 70" },
  { y: 112, from: "#ff3d8a", to: "#e0169a", d: "M46 112 C108 112 116 66 146 66 C172 66 170 112 194 112" },
];
const path = (s) => s.d;

export function logoSvg({ size = 28, working = false, cls = "", mono = false } = {}) {
  const id = `afh${++uid}`;
  const defs = STRANDS.map((s, i) =>
    `<linearGradient id="${id}g${i}" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="${mono ? "#fff" : s.from}"/><stop offset="1" stop-color="${mono ? "#c9c9d2" : s.to}"/></linearGradient>`
  ).join("");
  // magenta at the back, orange on top — matches the brand image
  const body = [2, 1, 0].map((i) => {
    const s = STRANDS[i];
    const d = path(s);
    return (
      `<path class="strand" d="${d}" stroke="url(#${id}g${i})"/>` +
      `<path class="pulse p${i}" d="${d}" pathLength="100"/>` +
      `<circle class="dot d${i}" cx="46" cy="${s.y}" r="15" fill="${mono ? "#fff" : s.from}"/>` +
      `<circle class="dot d${i} r" cx="194" cy="${s.y}" r="15" fill="${mono ? "#c9c9d2" : s.to}"/>`
    );
  }).join("");
  const h = Math.round((size * 140) / 240);
  return `<svg class="afh-logo${working ? " working" : ""}${cls ? " " + cls : ""}" width="${size}" height="${h}" viewBox="0 0 240 140" fill="none" aria-hidden="true"><defs>${defs}</defs>${body}</svg>`;
}

export function logoNode(opts) {
  const t = document.createElement("template");
  t.innerHTML = logoSvg(opts);
  return t.content.firstElementChild;
}

/** Toggle the working animation on one logo node or every logo inside `root`. */
export function setWorking(root, on) {
  if (!root) return;
  const nodes = root.classList?.contains("afh-logo") ? [root] : root.querySelectorAll(".afh-logo");
  nodes.forEach((n) => n.classList.toggle("working", !!on));
}
