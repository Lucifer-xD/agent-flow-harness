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
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

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
  const hub = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 0.5, 6), new THREE.MeshStandardMaterial({ color: 0x7a4a33, roughness: 0.34, metalness: 0.85, envMapIntensity: 1.1 }));
  body.rotation.x = Math.PI / 2;
  const seam = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.04, 8, 72), new THREE.MeshStandardMaterial({ color: 0xff8a50, emissive: 0xff6a2a, emissiveIntensity: 0.9, roughness: 0.4 }));
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.46, 32, 20), new THREE.MeshStandardMaterial({ color: 0xffe6c0, emissive: 0xffb11f, emissiveIntensity: 0.9, roughness: 0.35 }));
  core.position.z = 0.25;
  hub.add(body, seam, core);
  add("hub", hub, 0.25, [0.35, -0.3, 0]);
  add("torus", new THREE.Mesh(gradient(new THREE.TorusGeometry(0.72, 0.3, 40, 96), C.amber, C.pink), ceramic()), 0.3, [0.9, 0.2, 0]);
  add("pill", new THREE.Mesh(gradient(new THREE.CapsuleGeometry(0.34, 1.3, 12, 32), C.amber, C.orange, "y"), ceramic()), 0.34, [0.2, 0, Math.PI / 2 + 0.35]);
  add("sphereA", new THREE.Mesh(gradient(new THREE.SphereGeometry(1, 48, 32), C.coral, C.magenta, "y"), ceramic()), 1, [0, 0, 0]);
  add("sphereB", new THREE.Mesh(gradient(new THREE.SphereGeometry(1, 40, 28), C.amber, C.orange, "y"), ceramic()), 1, [0, 0, 0]);
  add("cube", new THREE.Mesh(gradient(new RoundedBoxGeometry(1.5, 1.5, 1.5, 4, 0.32), C.orange, C.pink), ceramic()), 0.75, [0.55, 0.75, 0.1]);
  // the mark itself: the logo's three strands as thick ceramic tubes that weave past each other,
  // with the six dots — two units wide, so `r` is half its width
  const STRANDS = [
    { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: C.amber, to: "#ff7a3d" },
    { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: C.coral },
    { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: C.pink, to: C.magenta },
  ];
  const mark = new THREE.Group();
  const toV = ([x, y], z) => new THREE.Vector3((x - 120) / 74, -(y - 70) / 74, z * 0.42);
  for (const s of STRANDS) {
    const P = s.pts.map((p, i) => toV(p, s.z[i]));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]));
    path.add(new THREE.CubicBezierCurve3(P[3], P[4], P[5], P[6]));
    mark.add(new THREE.Mesh(gradient(new THREE.TubeGeometry(path, 110, 0.1, 18, false), s.from, s.to), ceramic()));
    for (const [p, col] of [[P[0], s.from], [P[6], s.to]]) {
      const dot = new THREE.Mesh(gradient(new THREE.SphereGeometry(0.2, 32, 20), col, col), ceramic());
      dot.position.copy(p);
      mark.add(dot);
    }
  }
  add("mark", mark, 0.6, [0.12, -0.1, 0]);

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
      const spin = id === "torus" || id === "hub" ? t * 0.12 : id === "mark" ? Math.sin(t * 0.25) * 0.03 : Math.sin(t * 0.3 + o.seed) * 0.05;
      o.mesh.rotation.set(rx + Math.sin(t * 0.5 + o.seed) * (id === "mark" ? 0.03 : 0.06), ry + Math.sin(t * 0.37 + o.seed * 2) * (id === "mark" ? 0.05 : 0.08), rz + c.rot + spin);
    }
    core.material.emissiveIntensity = 0.7 + 0.3 * Math.sin(t * 2.4) + state.activity * 0.3;
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
