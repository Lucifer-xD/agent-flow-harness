// The 3D on every page is a studio set: glossy ceramic objects in the brand colours resting on the
// page itself — a hex hub (the harness), a torus, a pill, two spheres and a rounded cube — with
// tight contact shadows, so they read as things placed on the paper, not floating over it. The
// page decides where each object sits (in CSS pixels, next to real elements) and the scene keeps
// them there as the page scrolls; objects it doesn't place shrink away.
//
//   scene.place(id, { x, y, r, rot, vis })   id: hub torus pill sphereA sphereB cube
//                                             x,y: centre in CSS px (viewport); r: radius in px
//                                             rot: extra turn in radians; vis: 0..1
//   scene.hide(id) / scene.hideAll()
//
// Built to stay smooth on integrated graphics: six small meshes, one shadow map, no post-processing,
// and a pixel budget that steps down by itself if frames run long.
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const FOV = 32, DIST = 22;
const C = { amber: "#ffb11f", orange: "#ff6a2a", coral: "#ff4a68", pink: "#ff3d8a", magenta: "#e0169a" };
const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };

/** Paint a geometry with a gradient along one of its axes (vertex colours). */
function gradient(geo, from, to, axis = "x") {
  const pos = geo.attributes.position, n = pos.count, col = new Float32Array(n * 3);
  const a = new THREE.Color(from), b = new THREE.Color(to), c = new THREE.Color();
  const i = { x: 0, y: 1, z: 2 }[axis];
  let lo = Infinity, hi = -Infinity;
  for (let k = 0; k < n; k++) { const v = pos.array[k * 3 + i]; lo = Math.min(lo, v); hi = Math.max(hi, v); }
  for (let k = 0; k < n; k++) { c.copy(a).lerp(b, (pos.array[k * 3 + i] - lo) / (hi - lo || 1)); col.set([c.r, c.g, c.b], k * 3); }
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  return geo;
}
const ceramic = (extra = {}) => new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.28, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.12, envMapIntensity: 1.05, sheen: 0.2, sheenColor: 0xffe6d6, ...extra });

export function createScene(canvas, { mobile = false, reduced = false, lite = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x000000, 0);
  const shadows = !lite;
  renderer.shadowMap.enabled = shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  const camera = new THREE.PerspectiveCamera(FOV, innerWidth / innerHeight, 0.1, 100);
  camera.position.set(0, 0, DIST);
  camera.lookAt(0, 0, 0);

  // light: a soft key from the upper left, close to the viewing direction, so shadows hug the objects
  const key = new THREE.DirectionalLight(0xfff4ea, 1.8);
  key.position.set(-6, 9, 18);
  if (shadows) {
    key.castShadow = true;
    key.shadow.mapSize.set(mobile ? 1024 : 2048, mobile ? 1024 : 2048);
    key.shadow.radius = 4;
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.03;
    Object.assign(key.shadow.camera, { left: -16, right: 16, top: 12, bottom: -12, near: 1, far: 50 });
  }
  const rim = new THREE.DirectionalLight(0xff6a9a, 0.4);
  rim.position.set(6, -3, 6);
  scene.add(key, rim, new THREE.HemisphereLight(0xffffff, 0xf0e2d6, 0.8));

  // the page: an invisible plane that only shows the shadows the objects throw on it
  const page = new THREE.Mesh(new THREE.PlaneGeometry(120, 120), new THREE.ShadowMaterial({ color: 0x2a1408, opacity: 0.2, transparent: true, depthWrite: false }));
  page.receiveShadow = shadows;
  page.visible = shadows;
  scene.add(page);

  // ---- the objects (unit size; `depth` is how far their underside sits below their centre) ----
  const objects = {};
  const add = (id, mesh, depth, rest) => {
    mesh.castShadow = shadows;
    mesh.traverse((m) => { if (m.isMesh) m.castShadow = shadows; });
    mesh.visible = false;
    scene.add(mesh);
    objects[id] = { mesh, depth, rest, cur: { x: 0, y: 0, r: 0, rot: 0, vis: 0 }, tgt: { x: 0, y: 0, r: 0, rot: 0, vis: 0 }, placed: false, seed: Math.random() * 7 };
  };
  // Everything in the set is cut from the logo: its three strands (viewBox 240x140, each strand two
  // cubic segments meeting in the middle, with a depth per control point so they weave) and its dots.
  const STRANDS = [
    { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: C.amber, to: "#ff7a3d" },
    { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: C.coral },
    { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: C.pink, to: C.magenta },
  ];
  const toV = ([x, y], z) => new THREE.Vector3((x - 120) / 74, -(y - 70) / 74, z * 0.42);
  const curve = (s) => {
    const P = s.pts.map((p, i) => toV(p, s.z[i]));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]));
    path.add(new THREE.CubicBezierCurve3(P[3], P[4], P[5], P[6]));
    return path;
  };
  const dotMesh = (col, r = 0.2) => new THREE.Mesh(gradient(new THREE.SphereGeometry(r, 32, 20), col, col), ceramic());
  /** A piece of strand `k` between u0 and u1 (0 = left dot, 1 = right dot), with dots on the ends asked for, centred on itself. */
  const piece = (k, u0, u1, { dot0 = false, dot1 = false, radius = 0.1, dotR = 0.2 } = {}) => {
    const s = STRANDS[k], full = curve(s);
    const pts = Array.from({ length: 64 }, (_, i) => full.getPointAt(u0 + ((u1 - u0) * i) / 63));
    const path = new THREE.CatmullRomCurve3(pts);
    const g = new THREE.Group();
    const tube = new THREE.Mesh(gradient(new THREE.TubeGeometry(path, 80, radius, 18, false), s.from, s.to), ceramic());
    g.add(tube);
    if (dot0) { const d = dotMesh(s.from, dotR); d.position.copy(pts[0]); g.add(d); }
    if (dot1) { const d = dotMesh(s.to, dotR); d.position.copy(pts[pts.length - 1]); g.add(d); }
    // centre the piece on its own bounds, so x/y place its middle
    const box = new THREE.Box3().setFromObject(g), c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
    g.children.forEach((m) => m.position.sub(c));
    const scale = 2 / Math.max(size.x, size.y); // two units across, like a unit sphere: `r` is half its longest side
    g.scale.setScalar(scale);
    const inner = new THREE.Group();
    inner.add(g);
    return inner;
  };
  // the whole mark: all three strands with all six dots, 2.4 units wide (so r is half its width)
  const mark = new THREE.Group();
  STRANDS.forEach((s, k) => {
    mark.add(new THREE.Mesh(gradient(new THREE.TubeGeometry(curve(s), 110, 0.1, 18, false), s.from, s.to), ceramic()));
    const P = [toV(s.pts[0], 0), toV(s.pts[6], 0)];
    [[P[0], s.from], [P[1], s.to]].forEach(([p, col]) => { const d = dotMesh(col); d.position.copy(p); mark.add(d); });
  });
  add("mark", mark, 0.6, [0.1, 0, 0]); // faces the page squarely, so it reads as the logo
  // the pieces: the hub is the crossing in the middle of the mark (all three strands, middle third)
  const knot = new THREE.Group();
  STRANDS.forEach((s, k) => knot.add(piece(k, 0.3, 0.7, { radius: 0.15 })));
  { const box = new THREE.Box3().setFromObject(knot), size = box.getSize(new THREE.Vector3()); knot.scale.setScalar(2 / Math.max(size.x, size.y)); }
  add("hub", knot, 0.3, [0.15, 0, 0]);
  add("torus", piece(0, 0, 0.5, { dot0: true, radius: 0.16, dotR: 0.3 }), 0.3, [0.2, 0, 0.5]);   // the amber hook: a strand's left half with its dot
  add("pill", piece(2, 0.5, 1, { dot1: true, radius: 0.16, dotR: 0.3 }), 0.3, [0.2, 0, -0.4]);   // the magenta hook: a strand's right half with its dot
  add("sphereA", dotMesh(C.magenta, 1), 1, [0, 0, 0]);  // two of the dots on their own
  add("sphereB", dotMesh(C.amber, 1), 1, [0, 0, 0]);
  add("cube", piece(1, 0, 0.42, { dot0: true, dot1: true, radius: 0.17, dotR: 0.32 }), 0.3, [0.3, 0, 0.9]); // the coral link: a short run of strand between two dots

  // ---- size: CSS pixels ↔ world units on the page plane ----
  const BUDGET = mobile ? [1.6, 1.1, 0.8] : lite ? [1.8, 1.3] : [2.6, 1.9, 1.4, 1.0];
  let level = 0, ppu = 1;
  const resize = () => {
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2, Math.sqrt((BUDGET[level] * 1e6) / (innerWidth * innerHeight))));
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    ppu = innerHeight / (2 * Math.tan(THREE.MathUtils.degToRad(FOV / 2)) * DIST); // px per unit at z = 0
  };
  addEventListener("resize", resize);
  resize();
  const perf = { samples: [], wait: 1.5 };
  const watchFrames = (ms) => {
    if (perf.wait > 0) { perf.wait -= ms / 1000; return; }
    if (ms > 120) return;
    perf.samples.push(ms);
    if (perf.samples.length < 60) return;
    const median = perf.samples.sort((a, b) => a - b)[30];
    perf.samples.length = 0;
    if (median > 18.5 && level < BUDGET.length - 1) { level++; resize(); perf.wait = 0.8; }
  };

  // ---- pointer: the set leans a little towards the pointer ----
  const mouse = { x: 0, y: 0, sx: 0, sy: 0 };
  addEventListener("pointermove", (e) => { mouse.x = e.clientX / innerWidth - 0.5; mouse.y = e.clientY / innerHeight - 0.5; }, { passive: true });

  const state = { dim: 1, activity: 0.3 };
  let lastFade = -1;
  const clock = { last: performance.now(), t: 0 };
  const frame = (now) => {
    requestAnimationFrame(frame);
    const ms = now - clock.last;
    clock.last = now;
    if (document.hidden) return;
    watchFrames(ms);
    const dt = Math.min(ms / 1000, 0.05) * (reduced ? 0.3 : 1);
    clock.t += dt;
    const t = clock.t;
    mouse.sx += (mouse.x - mouse.sx) * Math.min(1, dt * 3);
    mouse.sy += (mouse.y - mouse.sy) * Math.min(1, dt * 3);
    const k = 1 - Math.exp(-Math.min(0.1, ms / 1000) * 18); // follows the page closely, eases between layouts
    camera.position.set(mouse.sx * 0.5, -mouse.sy * 0.35, DIST);
    camera.lookAt(mouse.sx * 0.15, -mouse.sy * 0.1, 0);
    key.position.set(-6 + mouse.sx * 2, 9 - mouse.sy * 2, 18);
    for (const id in objects) {
      const o = objects[id], c = o.cur, g = o.tgt;
      c.x += (g.x - c.x) * k; c.y += (g.y - c.y) * k; c.r += (g.r - c.r) * k; c.rot += (g.rot - c.rot) * k; c.vis += (g.vis - c.vis) * k;
      const s = (c.r / ppu) * smooth(c.vis);
      o.mesh.visible = s > 0.004;
      if (!o.mesh.visible) continue;
      const wx = (c.x - innerWidth / 2) / ppu, wy = -(c.y - innerHeight / 2) / ppu;
      o.mesh.position.set(wx, wy, o.depth * s);
      o.mesh.scale.setScalar(s * (1 + Math.sin(t * 1.3 + o.seed) * 0.012));
      const [rx, ry, rz] = o.rest;
      const spin = id === "mark" || id === "hub" ? Math.sin(t * 0.25 + o.seed) * 0.03 : Math.sin(t * 0.3 + o.seed) * 0.06;
      o.mesh.rotation.set(rx + Math.sin(t * 0.5 + o.seed) * (id === "mark" ? 0.03 : 0.06), ry + Math.sin(t * 0.37 + o.seed * 2) * (id === "mark" ? 0.05 : 0.08), rz + c.rot + spin);
    }
    const fade = Math.round(Math.min(1, Math.max(0, state.dim)) * 200) / 200;
    if (fade !== lastFade) canvas.style.opacity = lastFade = fade;
    renderer.render(scene, camera);
  };
  requestAnimationFrame(frame);

  const place = (id, { x, y, r, rot = 0, vis = 1 }) => {
    const o = objects[id];
    if (!o) return;
    if (!o.placed) { o.placed = true; Object.assign(o.cur, { x, y, r: 0, rot, vis: 0 }); } // a new object grows where it is put
    Object.assign(o.tgt, { x, y, r, rot, vis });
  };
  const hide = (id) => { const o = objects[id]; if (o) { o.tgt.vis = 0; o.tgt.r = o.cur.r; o.placed = false; } };
  const hideAll = () => Object.keys(objects).forEach(hide);
  const ids = Object.keys(objects);
  return { state, place, hide, hideAll, ids, three: { renderer, scene, camera, objects, quality: () => [`${BUDGET[level]} MP`, `${renderer.getPixelRatio().toFixed(2)}x`, shadows ? "shadows" : "no shadows"] } };
}
