// Every page but the home page: the app's mark at work, in 3D, in the page's hero stage box
// (`[data-stage]`), and the 2D mark where there's no WebGL. Pages without a stage load no 3D at all.
// (Entrances and menus are in layout.js.)
const stages = [...document.querySelectorAll("[data-stage]")];
stages.forEach((s) => { s.classList.add("stage"); s.innerHTML = window.afhMarkSvg?.(240) || ""; });
if (stages.length) {
  import("./scene.js").then(({ createMarks }) => {
    const marks = createMarks(document.querySelector("#scene"));
    stages.forEach((s) => marks.add(s, { tilt: true }));
    window.afhMarks = marks;
  }).catch(() => {}); // no 3D: the 2D mark at work stays
} else {
  document.querySelector("#scene")?.remove();
}
