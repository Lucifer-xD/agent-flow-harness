// The 3D on every page is the app's own mark at work: three glossy strands and six dots, animated
// exactly like the logo in AFH while a model works. Each strand draws itself from its left dot to
// its right dot, holds, then lets go from the left and reconnects, the three staggered by a third
// of a beat; a left dot pops as its strand leaves, a right dot lights up as the strand arrives.
// (Same timing as web/app.css: 3.2 s a beat, cubic-bezier(.65,0,.35,1), delays 0 / -1.05 / -2.1 s.)
//
// One fixed canvas behind the page draws a mark into every stage box the page registers:
//   const marks = createMarks(canvas)
//   marks.add(el, { tilt })      draw a mark centred in el, sized to its width; tilt: follow the pointer
// Stage boxes are empty, so the mark shows through them; cards and text sit on top of the canvas.
// It follows the page's theme (<html data-theme>) by itself and only draws while a stage is on screen.
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

// The logo (viewBox 240×140): each strand is two cubic segments meeting in the middle, with a depth
// per control point so the strands weave past each other in 3D.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: "#ffb11f", to: "#ff7a3d", delay: 2.1 },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68", delay: 1.05 },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: "#ff3d8a", to: "#e0169a", delay: 0 },
];
const BEAT = 3.2;
const STROKE = 9, DOT = 15, DEPTH = 34; // the app draws stroke 18 and dots r 15 in the 240×140 box

// cubic-bezier(.65,0,.35,1), the app's easing, solved for x
function bezier(p1x, p1y, p2x, p2y) {
  const cx = 3 * p1x, bx = 3 * (p2x - p1x) - cx, ax = 1 - cx - bx;
  const cy = 3 * p1y, by = 3 * (p2y - p1y) - cy, ay = 1 - cy - by;
  const X = (t) => ((ax * t + bx) * t + cx) * t, Y = (t) => ((ay * t + by) * t + cy) * t, dX = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    if (x <= 0) return 0; if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 6; i++) { const d = dX(t); if (Math.abs(d) < 1e-6) break; t -= (X(t) - x) / d; }
    return Y(Math.min(1, Math.max(0, t)));
  };
}
const EASE = bezier(0.65, 0, 0.35, 1);
const INOUT = bezier(0.42, 0, 0.58, 1); // ease-in-out, for the dots
const seg = (p, a, b) => Math.min(1, Math.max(0, (p - a) / (b - a)));
const lerp = (a, b, t) => a + (b - a) * t;

/** Where a strand is drawn at phase p (0..1): [tail, head] along it. Keyframes afh-link. */
function drawn(p) {
  if (p < 0.38) return [0, EASE(p / 0.38)];
  if (p < 0.58) return [0, 1];
  return [EASE(seg(p, 0.58, 1)), 1];
}
/** Left dot (afh-point): 1 → 1.25 at 6% → 1 at 20%. */
function leftDot(p) {
  if (p < 0.06) return lerp(1, 1.25, INOUT(p / 0.06));
  if (p < 0.2) return lerp(1.25, 1, INOUT(seg(p, 0.06, 0.2)));
  return 1;
}
/** Right dot (afh-point-r): scale and opacity. */
function rightDot(p) {
  if (p < 0.3) return [0.85, 0.6];
  if (p < 0.4) { const t = INOUT(seg(p, 0.3, 0.4)); return [lerp(0.85, 1.3, t), lerp(0.6, 1, t)]; }
  if (p < 0.58) return [lerp(1.3, 1, INOUT(seg(p, 0.4, 0.58))), 1];
  const t = INOUT(seg(p, 0.58, 1));
  return [lerp(1, 0.85, t), lerp(1, 0.6, t)];
}

const glossy = (extra = {}) => new THREE.MeshPhysicalMaterial({ roughness: 0.22, metalness: 0.05, clearcoat: 1, clearcoatRoughness: 0.08, envMapIntensity: 1.15, sheen: 0.25, sheenColor: 0xffe2d0, ...extra });

export function createMarks(canvas, { mobile = matchMedia("(max-width: 760px)").matches, reduced = matchMedia("(prefers-reduced-motion: reduce)").matches } = {}) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); }
  catch { canvas.remove(); return { add() {}, refresh() {} }; } // no WebGL: the stage boxes show their CSS fallback
  document.documentElement.classList.add("has-3d");
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, mobile ? 2 : 1.75));
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -4000, 4000);
  camera.position.z = 1000;
  const key = new THREE.DirectionalLight(0xfff3e8, 1.6);
  key.position.set(-0.5, 0.8, 1);
  const rim = new THREE.DirectionalLight(0xff5c9a, 0.7);
  rim.position.set(0.9, -0.4, 0.4);
  const fill = new THREE.HemisphereLight(0xffffff, 0x3a2030, 0.7);
  scene.add(key, rim, fill);

  // ---- the strands, shared by every mark (they all beat together) ----
  const curves = STRANDS.map((s) => {
    const P = s.pts.map(([x, y], i) => new THREE.Vector3(x - 120, 70 - y, s.z[i] * DEPTH));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]));
    path.add(new THREE.CubicBezierCurve3(P[3], P[4], P[5], P[6]));
    return path;
  });
  const geos = curves.map((c, k) => {
    const g = new THREE.TubeGeometry(c, mobile ? 140 : 220, STROKE, mobile ? 16 : 22, false);
    const from = new THREE.Color(STRANDS[k].from), to = new THREE.Color(STRANDS[k].to), col = new THREE.Color();
    const uv = g.attributes.uv, colors = new Float32Array(uv.count * 3);
    for (let i = 0; i < uv.count; i++) { col.copy(from).lerp(to, uv.getX(i)); col.toArray(colors, i * 3); }
    g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return g;
  });
  const uniforms = STRANDS.map(() => ({ uHead: { value: 1 }, uTail: { value: 0 }, uGlow: { value: 0.35 } }));
  const strandMats = STRANDS.map((_, k) => {
    const m = glossy({ vertexColors: true, emissive: 0xffffff });
    m.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, uniforms[k]);
      sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nvarying float vU;").replace("#include <begin_vertex>", "#include <begin_vertex>\nvU = uv.x;");
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform float uHead, uTail, uGlow; varying float vU;")
        .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
          if (vU > uHead || vU < uTail) discard;
          // the light that runs ahead of the drawing: brightest at the head, fading back along the strand
          float lead = exp(-max(0.0, uHead - vU) * 9.0) * step(uHead, 0.999);
          totalEmissiveRadiance = vColor.rgb * (0.10 + lead * uGlow);`);
    };
    m.customProgramCacheKey = () => "afh-strand";
    return m;
  });
  // round ends, like the logo's stroke-linecap: a cap at each end that follows the drawing
  const capGeo = new THREE.SphereGeometry(STROKE, 24, 16);
  const capMats = STRANDS.map(() => [glossy({ emissive: 0x000000 }), glossy({ emissive: 0x000000 })]);
  const dotGeo = new THREE.SphereGeometry(DOT, mobile ? 32 : 44, mobile ? 22 : 30);
  const dotMats = STRANDS.map((s) => [glossy({ color: s.from }), glossy({ color: s.to, transparent: true })]);

  const stages = [];
  function build() {
    const g = new THREE.Group();
    const parts = STRANDS.map((s, k) => {
      const tube = new THREE.Mesh(geos[k], strandMats[k]);
      const capT = new THREE.Mesh(capGeo, capMats[k][0]), capH = new THREE.Mesh(capGeo, capMats[k][1]);
      const L = new THREE.Mesh(dotGeo, dotMats[k][0]), R = new THREE.Mesh(dotGeo, dotMats[k][1]);
      L.position.set(46 - 120, 70 - s.pts[0][1], 0);
      R.position.set(194 - 120, 70 - s.pts[6][1], 0);
      R.renderOrder = 2;
      g.add(tube, capT, capH, L, R);
      return { tube, capT, capH, L, R };
    });
    g.visible = false;
    scene.add(g);
    return { g, parts };
  }

  const pointer = { x: 0, y: 0 };
  addEventListener("pointermove", (e) => { pointer.x = e.clientX / innerWidth - 0.5; pointer.y = e.clientY / innerHeight - 0.5; }, { passive: true });

  let W = 0, H = 0;
  function resize() {
    W = innerWidth; H = innerHeight;
    renderer.setSize(W, H, false);
    Object.assign(camera, { left: -W / 2, right: W / 2, top: H / 2, bottom: -H / 2 });
    camera.updateProjectionMatrix();
  }
  resize();
  addEventListener("resize", resize);

  const clock = new THREE.Clock();
  const tmpC = new THREE.Color();
  let running = false;
  function frame() {
    const t = reduced ? BEAT * 0.5 : clock.getElapsedTime();
    if (innerWidth !== W || innerHeight !== H) resize();
    // the beat, shared by every mark
    STRANDS.forEach((s, k) => {
      const p = (((t + s.delay) / BEAT) % 1 + 1) % 1;
      const [tail, head] = reduced ? [0, 1] : drawn(p);
      uniforms[k].uHead.value = head; uniforms[k].uTail.value = tail;
      const from = new THREE.Color(s.from), to = new THREE.Color(s.to);
      capMats[k][0].color.copy(tmpC.copy(from).lerp(to, tail));
      capMats[k][1].color.copy(tmpC.copy(from).lerp(to, head));
      const ls = reduced ? 1 : leftDot(p), [rs, ro] = reduced ? [1, 1] : rightDot(p);
      dotMats[k][1].opacity = ro;
      dotMats[k][1].emissive.copy(to).multiplyScalar(Math.max(0, rs - 1) * 1.4);
      dotMats[k][0].emissive.copy(from).multiplyScalar(Math.max(0, ls - 1) * 1.6);
      for (const st of stages) {
        const P = st.mark.parts[k], pos = curves[k];
        P.L.scale.setScalar(ls); P.R.scale.setScalar(rs);
        const on = head - tail > 0.004;
        P.tube.visible = P.capT.visible = P.capH.visible = on;
        if (on) { P.capT.position.copy(pos.getPointAt(Math.max(0.0005, tail))); P.capH.position.copy(pos.getPointAt(Math.min(0.9995, head))); }
      }
    });
    let any = false;
    for (const st of stages) {
      const r = st.el.getBoundingClientRect();
      const vis = r.bottom > -40 && r.top < H + 40 && r.width > 0;
      st.mark.g.visible = vis;
      if (!vis) continue;
      any = true;
      const sc = Math.min(r.width / 240, r.height / 140) * (st.fill || 0.94);
      const g = st.mark.g;
      g.position.set(r.left + r.width / 2 - W / 2, H / 2 - (r.top + r.height / 2), 0);
      g.scale.setScalar(sc);
      // a slow sway, and the pointer tilts it like an object in your hand
      const sway = reduced ? 0 : Math.sin(t * 0.55) * 0.12;
      const tx = (st.tilt ? pointer.y * 0.5 : 0) + (reduced ? 0 : Math.sin(t * 0.4 + 1) * 0.05);
      const ty = (st.tilt ? pointer.x * 0.7 : 0) + sway;
      g.rotation.x += (tx - g.rotation.x) * 0.06;
      g.rotation.y += (ty - g.rotation.y) * 0.06;
    }
    if (any) renderer.render(scene, camera);
    else renderer.clear();
    canvas.style.opacity = any ? "1" : "0";
  }
  function loop() { frame(); requestAnimationFrame(loop); }

  return {
    add(el, opts = {}) {
      if (!el) return;
      stages.push({ el, mark: build(), tilt: !!opts.tilt && !mobile, fill: opts.fill });
      if (!running) { running = true; requestAnimationFrame(loop); }
    },
    refresh: resize,
  };
}

// The film on the home page builds on the same strands and the same beat.
export { STRANDS, BEAT, drawn, leftDot, rightDot, glossy };
