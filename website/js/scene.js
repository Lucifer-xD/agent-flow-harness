// The 3D world behind every page is the AFH mark itself, alive. The three glossy strands of the
// logo are six cables (each strand is two halves that meet in the middle), ending in the six dots.
// Light runs inside them. When the page moves on, the same six cables and dots unwind into the
// shapes of the work: your words spiral into a hexagonal hub (the harness), the cables twist into
// a braided rope with the plan laid out along it, they fan out into six agents at work with sparks
// of work flowing between them and the hub, one of them feeds a file that types itself, and they
// close into a braided ring the models circle. On the 404 page the mark sags and comes apart.
//
// Built to stay smooth on integrated graphics: the six cables are one mesh whose points are bent
// on the CPU each frame (a few thousand vertices), glow comes from soft halos drawn in one pass
// instead of a bloom pass, and the drawing size is held to a pixel budget that steps down by
// itself if frames run long.
//
// The page steers it through `state` (numbers, eased by the caller):
//   shapes   mark core net plan code ring spread — weights; the world takes their blend
//            (core = the vortex into the hub, net = the agents, ring = the models, spread = lost)
//   framing  zoom spin tilt shiftX shiftY        mood  activity (how busy) · dim (brightness)
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { CODE, TOKEN_COLORS } from "./code-sample.js";

// The logo (viewBox 240×140): each strand is two cubic segments meeting at a middle point, with a
// depth per control point so the strands weave past each other. Stroke 14, dots r 15.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: "#ffb11f", to: "#ff7a3d" },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68" },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: "#ff3d8a", to: "#e0169a" },
];
const SHAPES = ["mark", "core", "net", "plan", "code", "ring", "spread"];
const PLAN = ["Read the auth code", "Build the login form", "Add session handling", "Write the tests", "Run them and fix"];
const S = 1 / 30;
const toV = ([x, y], z) => new THREE.Vector3((x - 120) * S, -(y - 70) * S, z);
const CABLE_R = 7 * S, DOT_R = 15 * S; // the logo's own proportions
// additive light that leaves the canvas alpha alone, so it adds onto the page's CSS background
// instead of punching opaque black squares into it
const ADD = { blending: THREE.CustomBlending, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneFactor, blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor };
const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const rnd = (a, b) => a + Math.random() * (b - a);
const TAU = Math.PI * 2;

// ---------- the cables ----------
// Six cables (K), each M segments long with RAD sides and rounded caps (CAP rows each end).
// Cable k is half of strand k % 3: k < 3 runs from the left dot to the middle, k ≥ 3 from the
// right dot to the middle — so along every cable, u = 0 is its dot and u = 1 is where it joins.
const K = 6, M = 72, RAD = 14, CAP = 5;
function markTable() {
  const out = [], v = new THREE.Vector3();
  for (let k = 0; k < K; k++) {
    const s = STRANDS[k % 3], P = s.pts.map((p, i) => toV(p, s.z[i]));
    const c = k < 3 ? new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]) : new THREE.CubicBezierCurve3(P[6], P[5], P[4], P[3]);
    const pts = new Float32Array((M + 1) * 3);
    for (let i = 0; i <= M; i++) c.getPoint(i / M, v).toArray(pts, i * 3);
    out.push(pts);
  }
  return out;
}
/** One geometry for all six cables; positions and normals are rewritten every frame. */
function cableGeometry() {
  const rows = [];
  for (let c = 0; c < CAP; c++) rows.push([0, -Math.PI / 2 + (c / CAP) * (Math.PI / 2)]);
  for (let i = 0; i <= M; i++) rows.push([i, 0]);
  for (let c = 1; c <= CAP; c++) rows.push([M, (c / CAP) * (Math.PI / 2)]);
  const per = rows.length * (RAD + 1), V = per * K;
  const pos = new Float32Array(V * 3), nrm = new Float32Array(V * 3), col = new Float32Array(V * 3), aT = new Float32Array(V), aSeed = new Float32Array(V);
  const idx = [];
  for (let k = 0; k < K; k++) {
    const s = STRANDS[k % 3], from = new THREE.Color(k < 3 ? s.from : s.to), mid = new THREE.Color(s.from).lerp(new THREE.Color(s.to), 0.5);
    const base = k * per;
    rows.forEach(([i], r) => {
      const t = i / M, c = from.clone().lerp(mid, t);
      for (let j = 0; j <= RAD; j++) { const v = base + r * (RAD + 1) + j; col.set([c.r, c.g, c.b], v * 3); aT[v] = t; aSeed[v] = k * 0.37; }
    });
    for (let r = 0; r < rows.length - 1; r++) for (let j = 0; j < RAD; j++) {
      const a = base + r * (RAD + 1) + j, b = a + RAD + 1;
      idx.push(a, a + 1, b, b, a + 1, b + 1);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute("normal", new THREE.BufferAttribute(nrm, 3).setUsage(THREE.DynamicDrawUsage));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("aT", new THREE.BufferAttribute(aT, 1));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(aSeed, 1));
  geo.setIndex(idx);
  return { geo, rows, per };
}

// ---------- canvas faces for the plan cards and the code panel ----------
function canvasTex(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}
function drawTask(g, w, h, text, st) {
  const cy = h / 2;
  if (st === "goal") {
    g.fillStyle = "#ffb11f"; g.font = "600 26px 'JetBrains Mono', monospace"; g.fillText("◎ GOAL", 40, cy - 18);
    g.fillStyle = "#fff4ea"; g.font = "500 34px Inter, system-ui, sans-serif"; g.fillText(text, 40, cy + 30);
    return;
  }
  g.beginPath(); g.arc(62, cy, 19, 0, Math.PI * 2);
  if (st === "done") {
    g.fillStyle = "#3ddc84"; g.fill();
    g.strokeStyle = "#0a1f12"; g.lineWidth = 5; g.beginPath(); g.moveTo(53, cy); g.lineTo(60, cy + 8); g.lineTo(72, cy - 8); g.stroke();
  } else { g.lineWidth = 4; g.strokeStyle = st === "now" ? "#ff6a2a" : "rgba(255,236,222,0.4)"; g.stroke(); }
  g.font = `${st === "now" ? 600 : 500} 34px Inter, system-ui, sans-serif`;
  g.fillStyle = st === "done" ? "#8a7e75" : st === "now" ? "#ffb48a" : "#efe4da";
  g.fillText(text, 104, cy + 12);
  if (st === "done") { g.fillRect(104, cy, g.measureText(text).width, 3); }
}
// The file, drawn once; the shader reveals it character by character (monospace, so it can).
const CODE_W = 1024, CODE_H = 720, CX = 78, CY = 132, LH = 30, CW = 13.2;
function codeLayout() {
  const lines = [[]];
  for (const [kind, text] of CODE) for (const ch of text) { if (ch === "\n") lines.push([]); else lines[lines.length - 1].push([kind, ch]); }
  return lines;
}
function drawCode(g, lines) {
  g.fillStyle = "#ff4a68"; g.beginPath(); g.arc(46, 48, 9, 0, Math.PI * 2); g.fill();
  g.fillStyle = "#c9bdb3"; g.font = "500 24px 'JetBrains Mono', monospace"; g.fillText("Live · src/pages/login.tsx", 68, 56);
  g.fillStyle = "rgba(255,236,222,0.12)"; g.fillRect(0, 88, CODE_W, 2);
  g.font = "400 22px 'JetBrains Mono', monospace";
  lines.forEach((line, i) => {
    const y = CY + i * LH;
    g.fillStyle = "#5f544c"; g.fillText(String(i + 1).padStart(2, " "), 22, y);
    line.forEach(([kind, ch], j) => { g.fillStyle = TOKEN_COLORS[kind]; g.fillText(ch, CX + j * CW, y); });
  });
}

export function createScene(canvas, { mobile = false, reduced = false, lite = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.setClearColor(0x000000, 0);
  // the backdrop is CSS (free): a warm haze behind the mark and a pink one lower left
  canvas.style.background = "radial-gradient(60% 70% at 62% 46%, #2a1007 0%, rgba(42,16,7,0) 70%), radial-gradient(45% 55% at 25% 70%, #1f0716 0%, rgba(31,7,22,0) 70%), #0a0807";
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; // studio reflections on the glass and metal
  const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.1, 150);
  camera.position.set(0, 0, 10);
  const world = new THREE.Group();
  scene.add(world);

  // lights: a warm key from above left, a pink rim from behind, and the hub's own light
  const key = new THREE.DirectionalLight(0xfff0e4, 1.1);
  key.position.set(-4, 6, 6);
  const rim = new THREE.DirectionalLight(0xff4a8a, 1.6);
  rim.position.set(5, -2, -6);
  scene.add(key, rim);
  scene.add(new THREE.HemisphereLight(0xffe6d6, 0x140806, 0.2));
  const hubLight = new THREE.PointLight(0xffa050, 0, 0, 2);
  world.add(hubLight);

  // drifting dust for depth
  const D = mobile ? 600 : 1100;
  const dp = new Float32Array(D * 3);
  for (let i = 0; i < D; i++) dp.set([(Math.random() * 2 - 1) * 36, (Math.random() * 2 - 1) * 22, -Math.random() * 40 + 3], i * 3);
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
  const dust = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0xffc9a8, size: 0.045, transparent: true, opacity: 0.5, depthWrite: false, ...ADD }));
  scene.add(dust);

  // ---- the cables: candy glass with light running inside ----
  const MARK = markTable();
  const { geo: cableGeo, rows, per } = cableGeometry();
  const cableU = { uFlow: { value: 0 }, uGlow: { value: 0.3 }, uPulse: { value: 1 } };
  const cableMat = new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.2, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.1, envMapIntensity: 0.8, emissive: 0xffffff });
  cableMat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, cableU);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float aT, aSeed; varying float vT, vSeed;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvT = aT; vSeed = aSeed;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform float uFlow, uGlow, uPulse; varying float vT, vSeed;")
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        // light travelling inside the glass towards the join: soft bands plus a bright packet
        float x = vT * 1.4 - uFlow + vSeed;
        float band = 0.5 + 0.5 * sin(x * 12.566);
        float pk = fract(x);
        float packet = pow(max(0.0, 1.0 - abs(pk - 0.5) / 0.11), 2.0);
        totalEmissiveRadiance = vColor.rgb * (uGlow * (0.55 + 0.45 * band) + packet * uPulse * 2.2);`);
  };
  cableMat.customProgramCacheKey = () => "afh-cable";
  const cables = new THREE.Mesh(cableGeo, cableMat);
  cables.frustumCulled = false;
  world.add(cables);
  const cPos = cableGeo.attributes.position.array, cNrm = cableGeo.attributes.normal.array;
  // scratch for bending: the points of one cable, its frames and radii
  const pts = Array.from({ length: K }, () => new Float32Array((M + 1) * 3));
  const radii = new Float32Array(M + 1);
  const Tn = Array.from({ length: M + 1 }, () => new THREE.Vector3()), Nn = Array.from({ length: M + 1 }, () => new THREE.Vector3()), Bn = Array.from({ length: M + 1 }, () => new THREE.Vector3());
  const REF = new THREE.Vector3(0.13, 1, 0.09).normalize(), cosT = [], sinT = [];
  for (let j = 0; j <= RAD; j++) { cosT.push(Math.cos((j / RAD) * TAU)); sinT.push(Math.sin((j / RAD) * TAU)); }
  const v1 = new THREE.Vector3(), v2 = new THREE.Vector3(), v3 = new THREE.Vector3(), v4 = new THREE.Vector3();
  /** Write cable k's tube round its points: a frame carried along the curve, so the tube never pinches. */
  const writeCable = (k) => {
    const P = pts[k], base = k * per;
    for (let i = 0; i <= M; i++) {
      const a = Math.max(0, i - 1) * 3, b = Math.min(M, i + 1) * 3;
      Tn[i].set(P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]);
      if (Tn[i].lengthSq() < 1e-10) Tn[i].copy(i ? Tn[i - 1] : REF); else Tn[i].normalize();
      if (i === 0) Nn[0].crossVectors(Tn[0], REF);
      else Nn[i].copy(Nn[i - 1]).addScaledVector(Tn[i], -Nn[i - 1].dot(Tn[i]));
      if (Nn[i].lengthSq() < 1e-6) Nn[i].crossVectors(Tn[i], Math.abs(Tn[i].y) < 0.9 ? REF : v1.set(1, 0, 0));
      Nn[i].normalize();
      Bn[i].crossVectors(Tn[i], Nn[i]);
    }
    for (let r = 0; r < rows.length; r++) {
      const [i, ph] = rows[r], cph = Math.cos(ph), sph = Math.sin(ph), rad = radii[i];
      const T = Tn[i], N = Nn[i], B = Bn[i], cx = P[i * 3], cy = P[i * 3 + 1], cz = P[i * 3 + 2];
      for (let j = 0; j <= RAD; j++) {
        const v = (base + r * (RAD + 1) + j) * 3;
        const nx = (N.x * cosT[j] + B.x * sinT[j]) * cph + T.x * sph, ny = (N.y * cosT[j] + B.y * sinT[j]) * cph + T.y * sph, nz = (N.z * cosT[j] + B.z * sinT[j]) * cph + T.z * sph;
        cNrm[v] = nx; cNrm[v + 1] = ny; cNrm[v + 2] = nz;
        cPos[v] = cx + nx * rad; cPos[v + 1] = cy + ny * rad; cPos[v + 2] = cz + nz * rad;
      }
    }
  };

  // ---- the dots: six glossy spheres, the agents ----
  const dotGeo = new THREE.SphereGeometry(DOT_R, 40, 28);
  const dots = Array.from({ length: K }, (_, k) => {
    const s = STRANDS[k % 3], c = new THREE.Color(k < 3 ? s.from : s.to);
    const mat = new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.18, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.08, envMapIntensity: 0.9, emissive: c, emissiveIntensity: 0.22 });
    const mesh = new THREE.Mesh(dotGeo, mat);
    world.add(mesh);
    return { mesh, mat, c, glow: c.clone().convertLinearToSRGB(), hi: 0, work: rnd(0, TAU) };
  });

  // ---- the hub: a hexagonal connector the six cables plug into — the harness ----
  const hub = new THREE.Group();
  world.add(hub);
  const hubBody = new THREE.Mesh(new THREE.CylinderGeometry(0.56, 0.56, 0.46, 6), new THREE.MeshStandardMaterial({ color: 0x2a1f1a, roughness: 0.22, metalness: 0.85, envMapIntensity: 1.1 }));
  const hubSeam = new THREE.Mesh(new THREE.TorusGeometry(0.57, 0.022, 8, 60), new THREE.MeshBasicMaterial({ color: new THREE.Color("#ff8a50").multiplyScalar(2), transparent: true, opacity: 0.9, depthWrite: false, ...ADD }));
  hubSeam.rotation.x = Math.PI / 2;
  const eyeMat = new THREE.MeshBasicMaterial({ color: new THREE.Color("#ffb11f"), transparent: true, opacity: 0.9, depthWrite: false, ...ADD, side: THREE.DoubleSide });
  const eyeTop = new THREE.Mesh(new THREE.CircleGeometry(0.4, 6), eyeMat), eyeBot = eyeTop.clone();
  eyeTop.rotation.x = -Math.PI / 2; eyeTop.position.y = 0.232;
  eyeBot.rotation.x = Math.PI / 2; eyeBot.position.y = -0.232;
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 16), new THREE.MeshBasicMaterial({ color: new THREE.Color("#fff1dc").multiplyScalar(2.2) }));
  hub.add(hubBody, hubSeam, eyeTop, eyeBot, core);

  // ---- glows: soft halos round everything that gives off light, in one draw (instead of bloom) ----
  const SPARKS = 18;
  const G_DOT = 0, G_HUB = K, G_SPARK = K + 1, GLOWS = G_SPARK + SPARKS;
  const glowPos = new Float32Array(GLOWS * 3), glowCol = new Float32Array(GLOWS * 3), glowSize = new Float32Array(GLOWS);
  const glowGeo = new THREE.BufferGeometry();
  glowGeo.setAttribute("position", new THREE.BufferAttribute(glowPos, 3));
  glowGeo.setAttribute("aCol", new THREE.BufferAttribute(glowCol, 3));
  glowGeo.setAttribute("aSize", new THREE.BufferAttribute(glowSize, 1));
  const glowU = { uScale: { value: 500 } };
  // each halo: a hot centre and a wide soft tail, like bloom
  const glows = new THREE.Points(glowGeo, new THREE.ShaderMaterial({
    uniforms: glowU, transparent: true, depthWrite: false, ...ADD,
    vertexShader: /* glsl */ `uniform float uScale; attribute float aSize; attribute vec3 aCol; varying vec3 vC;
      void main() { vC = aCol; vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = min(aSize * uScale / max(0.5, -mv.z), 1000.0); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: /* glsl */ `varying vec3 vC;
      void main() { float d = length(gl_PointCoord - 0.5) * 2.0; float a = (exp(-d * d * 9.0) * 0.6 + exp(-d * d * 2.6) * 0.4) * smoothstep(1.0, 0.6, d); gl_FragColor = vec4(vC * a, 1.0); }`,
  }));
  glows.frustumCulled = false;
  world.add(glows);
  const glowHub = new THREE.Color("#ff8a50").convertLinearToSRGB();
  const setGlow = (i, p, size, c, k) => { glowPos[i * 3] = p.x; glowPos[i * 3 + 1] = p.y; glowPos[i * 3 + 2] = p.z; glowSize[i] = size; glowCol[i * 3] = c.r * k; glowCol[i * 3 + 1] = c.g * k; glowCol[i * 3 + 2] = c.b * k; };
  const sparks = Array.from({ length: SPARKS }, (_, j) => ({ k: j % K, speed: 0.16 + (j % 5) * 0.025, ph: (j * 0.37) % 1, glow: dots[j % K].glow.clone().lerp(new THREE.Color(1, 0.97, 0.9), 0.45) }));

  // ---- the plan: glass cards along the rope, ticked off as the agents work ----
  const face = new THREE.Group(); // always faces the camera; plan and code live in it
  world.add(face);
  const plan = new THREE.Group();
  face.add(plan);
  const glass = (opacity) => new THREE.MeshStandardMaterial({ color: 0x1b1411, roughness: 0.22, metalness: 0.1, envMapIntensity: 0.9, transparent: true, opacity, emissive: 0xff6a2a, emissiveIntensity: 0 });
  const cards = [{ text: "Users can sign up and log in", goal: true }, ...PLAN.map((text) => ({ text }))].map((it, i) => {
    const w = it.goal ? 2.6 : 2.4, h = it.goal ? 0.56 : 0.42;
    const body = new THREE.Mesh(new RoundedBoxGeometry(w, h, 0.08, 4, 0.07), glass(0.9));
    const states = it.goal ? ["goal"] : ["todo", "now", "done"];
    const tex = Object.fromEntries(states.map((st) => [st, canvasTex(it.goal ? 760 : 700, it.goal ? 164 : 122, (g, cw, ch) => drawTask(g, cw, ch, it.text, st))]));
    const faceMat = new THREE.MeshBasicMaterial({ map: tex[states[0]], transparent: true, depthWrite: false });
    const front = new THREE.Mesh(new THREE.PlaneGeometry(w * 0.96, h * 0.92), faceMat);
    front.position.z = 0.045;
    const card = new THREE.Group();
    card.add(body, front);
    plan.add(card);
    return { card, body, faceMat, tex, i, goal: !!it.goal, st: states[0], y: 0 };
  });

  // ---- the file: a glass panel that types itself ----
  const lines = codeLayout();
  const codeTex = canvasTex(CODE_W, CODE_H, (g) => drawCode(g, lines));
  const codeU = { uMap: { value: codeTex }, uLine: { value: 0 }, uCol: { value: 0 }, uTime: { value: 0 }, uOpacity: { value: 1 } };
  const codePanel = new THREE.Group();
  face.add(codePanel);
  const codeBody = new THREE.Mesh(new RoundedBoxGeometry(3.7, 2.6, 0.1, 4, 0.1), glass(0.93));
  const codeFace = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 3.6 * (CODE_H / CODE_W)), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, uniforms: codeU,
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: /* glsl */ `
      uniform sampler2D uMap; uniform float uLine, uCol, uTime, uOpacity; varying vec2 vUv;
      void main() {
        vec2 px = vec2(vUv.x * ${CODE_W}.0, (1.0 - vUv.y) * ${CODE_H}.0);
        vec4 c = texture2D(uMap, vUv);
        float line = floor((px.y - ${CY}.0 + 22.0) / ${LH}.0);
        float col = (px.x - ${CX}.0) / ${CW};
        float shown = px.y < 96.0 ? 1.0 : line < uLine ? 1.0 : line > uLine ? 0.0 : (px.x < ${CX - 6}.0 ? 1.0 : step(col, uCol));
        vec2 caret = vec2(${CX}.0 + uCol * ${CW} + 2.0, ${CY}.0 + uLine * ${LH}.0 - 7.0);
        float k = step(abs(px.x - caret.x), 1.8) * step(abs(px.y - caret.y), 13.0) * step(0.45, fract(uTime * 1.4));
        vec3 rgb = mix(c.rgb, vec3(1.0, 0.5, 0.2) * 2.5, k);
        gl_FragColor = vec4(rgb, max(c.a * shown, k) * uOpacity);
        #include <colorspace_fragment>
      }`,
  }));
  codeFace.position.z = 0.056;
  codePanel.add(codeBody, codeFace);
  const typing = { n: 0, hold: 0, line: 0, col: 0 };
  const lineLen = lines.map((l) => l.length);

  // ---- the models: a belt of tokens circling the ring ----
  const RC = new THREE.Vector3(0, 0.3, 0), RING_R = 2.55; // the ring's centre and radius
  const TOKENS = 228;
  const belt = new THREE.InstancedMesh(new RoundedBoxGeometry(1, 1, 1, 2, 0.28), new THREE.MeshStandardMaterial({ roughness: 0.22, envMapIntensity: 0.65, emissive: 0x3a1206, emissiveIntensity: 1 }), TOKENS);
  belt.frustumCulled = false;
  world.add(belt);
  const tokenData = Array.from({ length: TOKENS }, (_, i) => {
    const lane = i % 2;
    belt.setColorAt(i, dots[(i * 7) % K].c.clone().lerp(new THREE.Color("#fff1e0"), Math.random() * 0.35));
    return { a: Math.random() * TAU, r: RING_R + 0.95 + lane * 0.42 + (Math.random() - 0.5) * 0.12, s: 0.08 + Math.random() * 0.08, spin: Math.random() * 6, speed: (lane ? -0.2 : 0.26), y: (Math.random() - 0.5) * 0.5 };
  });
  const tokM = new THREE.Matrix4(), tokQ = new THREE.Quaternion(), tokE = new THREE.Euler(), tokP = new THREE.Vector3(), tokS = new THREE.Vector3();

  // ---- a click (or a download) sends a shock ring out ----
  const shockMat = new THREE.MeshBasicMaterial({ color: new THREE.Color("#ff8a50").multiplyScalar(3), transparent: true, opacity: 0, depthWrite: false, ...ADD, side: THREE.DoubleSide });
  const shock = new THREE.Mesh(new THREE.TorusGeometry(1, 0.012, 8, 160), shockMat);
  world.add(shock);
  const pulse = { t: 1, strength: 0, boost: 0 };

  // ---- drawing size: a pixel budget (megapixels) that steps down by itself if frames run long ----
  const BUDGET = mobile ? [1.6, 1.1, 0.8] : lite ? [1.8, 1.3, 0.9] : [2.6, 1.9, 1.4, 1.0, 0.75];
  let level = 0, narrow = false; // narrow: a portrait screen, so the plan and code sit below the cables, not beside them
  const resize = () => {
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2, Math.sqrt((BUDGET[level] * 1e6) / (innerWidth * innerHeight))));
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    narrow = camera.aspect < 1.2 || innerWidth < 560; // matches the CSS's portrait layout
    glowU.uScale.value = renderer.getDrawingBufferSize(new THREE.Vector2()).y / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
  };
  const applyQuality = resize;
  addEventListener("resize", resize);
  applyQuality();
  const perf = { samples: [], wait: 1.5 };
  const watchFrames = (ms) => {
    if (perf.wait > 0) { perf.wait -= ms / 1000; return; }
    if (ms > 120) return; // a hitch, or a window the browser is throttling: says nothing about the GPU
    perf.samples.push(ms);
    if (perf.samples.length < 60) return;
    const median = perf.samples.sort((a, b) => a - b)[30];
    perf.samples.length = 0;
    if (median > 18.5 && level < BUDGET.length - 1) { level++; applyQuality(); perf.wait = 0.8; }
  };

  // ---- state and pointer ----
  let lastFade = -1;
  const state = { zoom: 0, spin: 0, tilt: 0, shiftX: 0, shiftY: 0, mark: 1, core: 0, net: 0, plan: 0, code: 0, ring: 0, spread: 0, activity: 0.3, dim: 1 };
  const mouse = { x: 0, y: 0, sx: 0, sy: 0, ndc: new THREE.Vector2(-9, -9) };
  addEventListener("pointermove", (e) => {
    mouse.x = e.clientX / innerWidth - 0.5; mouse.y = e.clientY / innerHeight - 0.5;
    mouse.ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  }, { passive: true });
  const ray = new THREE.Raycaster();
  const dotMeshes = dots.map((d) => d.mesh);

  const q = new THREE.Quaternion();
  const baseZ = () => 10.5 * Math.max(1, 1.3 / Math.min(camera.aspect, 1.3)); // keep the mark inside narrow screens
  const clock = { last: performance.now(), t: 0, plan: 0, intro: 0 };

  // ---- responsive framing: put a shape exactly into a box on the page ----
  // how much room each shape takes (world units, as seen from the camera; cx/cy: its middle)
  const markW = (194 - 46) * S + DOT_R * 2, markH = (112 - 28) * S + DOT_R * 2;
  const box = (name) => ({
    mark: { w: markW, h: markH, cx: 0, cy: 0 },
    core: { w: 8, h: 6.2, cx: 0, cy: 0 },
    plan: narrow ? { w: 7.6, h: 10, cx: -1.2, cy: -1.3 } : { w: 10.8, h: 6, cx: 0.5, cy: 0.5 },
    net: { w: 7.6, h: 6.4, cx: 0, cy: 0.3 },
    code: narrow ? { w: 7.6, h: 9.6, cx: -1.2, cy: -1.2 } : { w: 11.2, h: 6, cx: 1.1, cy: 0.6 },
    ring: { w: 8.2, h: 6.6, cx: 0, cy: 0.3 },
  })[name];
  const fitCam = new THREE.PerspectiveCamera(), fitS = new THREE.Vector3(), fitP = new THREE.Vector3(), fitMid = new THREE.Vector3();
  /** zoom/shiftX/shiftY that make a shape (default: the mark) fill `rect` (CSS px, viewport coordinates) — on any screen. */
  const fit = (rect, fill = 1, name = "mark") => {
    const b = box(name);
    fitMid.set(b.cx, b.cy, 0);
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const px = Math.min(rect.width / b.w, rect.height / b.h) * fill; // CSS px per world unit
    const dist = innerHeight / (2 * tan * px);
    const nx = ((rect.left + rect.width / 2) / innerWidth) * 2 - 1, ny = 1 - ((rect.top + rect.height / 2) / innerHeight) * 2;
    fitCam.fov = camera.fov; fitCam.aspect = innerWidth / innerHeight; fitCam.updateProjectionMatrix();
    fitS.set(0, 0, 0);
    for (let i = 0; i < 8; i++) { // the camera looks a quarter of the way towards the shift, so solve it in a few steps
      fitCam.position.set(0, 0, dist); fitCam.lookAt(fitS.x * 0.25, fitS.y * 0.25, 0); fitCam.updateMatrixWorld();
      fitP.copy(fitMid).add(fitS).project(fitCam);
      fitS.x += ((nx - fitP.x) * dist * tan * fitCam.aspect) / 0.75;
      fitS.y += ((ny - fitP.y) * dist * tan) / 0.75;
    }
    return { zoom: baseZ() - dist, shiftX: fitS.x, shiftY: fitS.y };
  };

  // ---- the shapes: where cable k's point u (0 = its dot, 1 = its join) is in each one ----
  const a0 = (k) => (k * TAU) / K;
  let t = 0; // the clock, read by the shapes
  // the vortex: your words spiral in along the six arms to the hub at the centre
  const shapeCore = (k, u, o) => {
    const s = 1 - u, r = 0.2 + 3.35 * Math.pow(s, 0.9), th = a0(k) + s * 2.3 + t * 0.12;
    return o.set(Math.cos(th) * r, -0.3 * s * s + Math.sin(th * 2 + t * 1.4) * 0.1 * s, Math.sin(th) * r);
  };
  // the rope: the six cables twist together from the hub on the left, then peel off one by one
  // into a column of dots — the list the plan is read from
  const ropeX = () => (narrow ? [-3.9, 1.5] : [-4.3, 1.3]);
  const shapePlan = (k, u, o) => {
    const s = 1 - u, [xh, xd] = ropeX();
    const ph = a0(k) + s * 4.2 - t * 0.35, rho = 0.5 * smooth(s / 0.12);
    o.set(xh + s * (xd - xh), 0.2 + rho * Math.cos(ph), rho * Math.sin(ph));
    const peel = smooth((s - 0.55) / 0.45);
    if (peel) o.lerp(v2.set(xd + 0.3, 0.2 + (2.5 - k) * 0.76, 0.2), peel);
    return o;
  };
  // the agents: six dots round the hub, each on an S-shaped cable like the logo's own
  const NET = { c: new THREE.Vector3(0, 0.3, 0), r: 2.9 };
  const CODE_C = { c: new THREE.Vector3(), r: 2.3, pull: new THREE.Vector3() };
  const dotAt = (k, L, o) => {
    const b = a0(k) + 0.5 + Math.sin(t * 0.18 + k) * 0.08;
    return o.set(L.c.x + Math.cos(b) * L.r, L.c.y + Math.sin(b) * L.r * 0.78, L.c.z + (k % 2 ? 0.9 : -0.9) + Math.sin(t * 0.7 + k * 1.9) * 0.25);
  };
  const shapeNet = (k, u, o, L) => {
    const s = 1 - u;
    dotAt(k, L, v2);
    if (L.pull && k === 1) v2.copy(L.pull); // the orange agent feeds the file
    o.lerpVectors(L.c, v2, s);
    v3.subVectors(v2, L.c); v4.set(-v3.y, v3.x, 0).normalize();
    const sw = Math.sin(s * TAU) * 0.3 * (k % 2 ? 1 : -1);
    o.addScaledVector(v4, sw);
    o.z += Math.sin(s * Math.PI) * 0.3 * (k < 3 ? 1 : -1);
    return o;
  };
  // the ring: six cables braided round a circle, the dots at the joins
  const shapeRing = (k, u, o) => {
    const s = 1 - u, al = a0(k) + (s * TAU) / K + t * 0.2, ph = k * Math.PI + s * Math.PI, rho = 0.32;
    const r = RING_R + rho * Math.cos(ph);
    return o.set(RC.x + Math.cos(al) * r, RC.y + rho * Math.sin(ph), RC.z + Math.sin(al) * r);
  };
  // lost: the mark sags, the dots fall and the joins drift apart
  const lostDrift = Array.from({ length: K }, () => new THREE.Vector3(rnd(-0.5, 0.5), rnd(0.3, 0.9), rnd(-0.6, 0.6)));
  const shapeLost = (k, u, o) => {
    const s = 1 - u, m = MARK[k], i = Math.round(u * M) * 3;
    o.set(m[i], m[i + 1], m[i + 2]);
    o.y -= (1.5 + (k % 3) * 0.3) * s * s;
    o.x += (k < 3 ? -0.5 : 0.5) * s * s;
    o.addScaledVector(lostDrift[k], u * u);
    o.y += Math.sin(t * 0.6 + k) * 0.08 * s;
    return o;
  };
  // where the hub stands in each shape (hidden in the mark, the ring and lost — it stays near the middle)
  const hubAt = { mark: new THREE.Vector3(0, 0, 0), core: new THREE.Vector3(0, 0, 0), plan: new THREE.Vector3(), net: NET.c, code: CODE_C.c, ring: RC, spread: new THREE.Vector3(0, -0.4, 0) };
  const hubPos = new THREE.Vector3(), sparkP = new THREE.Vector3();
  const pointAt = (k, u, o) => { // a point along cable k as it is now
    const x = Math.min(M - 1e-4, Math.max(0, u * M)), i = Math.floor(x), f = x - i, P = pts[k], a = i * 3, b = a + 3;
    return o.set(P[a] + (P[b] - P[a]) * f, P[a + 1] + (P[b + 1] - P[a + 1]) * f, P[a + 2] + (P[b + 2] - P[a + 2]) * f);
  };

  const frame = (now) => {
    requestAnimationFrame(frame);
    const ms = now - clock.last;
    clock.last = now;
    if (document.hidden) return;
    watchFrames(ms);
    const dt = Math.min(ms / 1000, 0.05) * (reduced ? 0.3 : 1);
    pulse.boost *= Math.pow(0.25, dt);
    const act = state.activity + pulse.boost;
    clock.t += dt;
    clock.plan += dt * 0.55 * (0.7 + act * 0.3);
    clock.intro = Math.min(1, clock.intro + dt / 1.5);
    t = clock.t;
    mouse.sx += (mouse.x - mouse.sx) * Math.min(1, dt * 3);
    mouse.sy += (mouse.y - mouse.sy) * Math.min(1, dt * 3);

    // framing
    world.rotation.y = state.spin + mouse.sx * 0.45 + Math.sin(t * 0.25) * 0.08;
    world.rotation.x = state.tilt - mouse.sy * 0.28 + Math.cos(t * 0.2) * 0.04;
    world.position.set(state.shiftX, state.shiftY, 0);
    camera.position.set(mouse.sx * 0.6, -mouse.sy * 0.4, baseZ() - state.zoom);
    camera.lookAt(state.shiftX * 0.25, state.shiftY * 0.25, 0);
    camera.updateMatrixWorld();
    world.updateMatrixWorld();
    world.getWorldQuaternion(q).invert().multiply(camera.quaternion);
    face.quaternion.copy(q);
    dust.rotation.y = t * 0.01;
    // the canvas is see-through, so dimming fades it rather than darkening the objects to black shapes
    const dim = Math.max(0, state.dim);
    renderer.toneMappingExposure = 0.5 + 0.5 * Math.min(1, dim);
    const fade = Math.round(Math.min(1, dim * 1.4) * 200) / 200;
    if (fade !== lastFade) canvas.style.opacity = lastFade = fade;

    // the blend of shapes
    const W = SHAPES.map((s) => Math.max(0, state[s]));
    const total = W.reduce((a, b) => a + b, 0) || 1;
    const [wM, wC, wN, wP, wK, wR, wS] = W.map((w) => w / total);
    const wHub = wC + wP + wN + wK; // the hub is out
    const wWork = wN + wK; // the agents at work
    const mixed = 1 - (wM * wM + wC * wC + wN * wN + wP * wP + wK * wK + wR * wR + wS * wS); // 0 in one shape, up to ~0.5 between two

    // the shapes' anchors for this screen
    hubAt.plan.set(ropeX()[0], 0.2, 0);
    if (narrow) { CODE_C.c.set(-1.2, 1.3, 0); CODE_C.r = 2.0; CODE_C.pull.set(-1.2, -2.45, 0.3); }
    else { CODE_C.c.set(-1.6, 0.6, 0); CODE_C.r = 2.3; CODE_C.pull.set(2.25, 0.6, 0.3); }
    hubPos.set(0, 0, 0);
    SHAPES.forEach((s, i) => { if (W[i]) hubPos.addScaledVector(hubAt[s], W[i] / total); });

    // the cables: every point's place is the blend of its places in every shape
    const taper = 0.35 * wHub; // thinner towards the hub, where the six gather
    const grow = smooth(clock.intro * 1.1); // on load the strands draw themselves from the dots to the middle, like the app's logo
    for (let k = 0; k < K; k++) {
      const P = pts[k], m = MARK[k];
      for (let i = 0; i <= M; i++) {
        const u = i / M;
        const p = tokP.set(0, 0, 0);
        if (wM) p.addScaledVector(v1.set(m[i * 3], m[i * 3 + 1], m[i * 3 + 2]), wM);
        if (wC) p.addScaledVector(shapeCore(k, u, v1), wC);
        if (wP) p.addScaledVector(shapePlan(k, u, v1), wP);
        if (wN) p.addScaledVector(shapeNet(k, u, v1, NET), wN);
        if (wK) p.addScaledVector(shapeNet(k, u, v1, CODE_C), wK);
        if (wR) p.addScaledVector(shapeRing(k, u, v1), wR);
        if (wS) p.addScaledVector(shapeLost(k, u, v1), wS);
        // a change of shape ripples along every cable
        p.y += mixed * Math.sin(u * 7 + t * 2.4 + k * 1.1) * 0.6;
        p.z += mixed * Math.cos(u * 5 + t * 1.9 + k) * 0.4;
        P[i * 3] = p.x; P[i * 3 + 1] = p.y; P[i * 3 + 2] = p.z;
        radii[i] = CABLE_R * (1 - taper * u * u);
      }
      if (grow < 1) { // not yet drawn past `grow`: the rest sits at the tip
        const e = Math.floor(grow * M) * 3;
        for (let i = e + 3; i < P.length; i += 3) { P[i] = P[e]; P[i + 1] = P[e + 1]; P[i + 2] = P[e + 2]; }
      }
      writeCable(k);
    }
    cableGeo.attributes.position.needsUpdate = true;
    cableGeo.attributes.normal.needsUpdate = true;
    cableU.uFlow.value += dt * (0.22 + act * 0.25);
    cableU.uGlow.value = 0.26 + act * 0.1 + pulse.boost * 0.15;
    cableU.uPulse.value = 0.7 + act * 0.5;

    // the dots: on the end of their cables; busy ones pulse, the pointed-at one lights up
    let hovered = -1;
    ray.setFromCamera(mouse.ndc, camera);
    const hit = ray.intersectObjects(dotMeshes, false)[0];
    if (hit) hovered = dotMeshes.indexOf(hit.object);
    dots.forEach((d, k) => {
      d.hi += ((k === hovered ? 1 : 0) - d.hi) * Math.min(1, dt * 8);
      d.mesh.position.set(pts[k][0], pts[k][1], pts[k][2]);
      const work = wWork * (0.5 + 0.5 * Math.sin(t * 1.6 + d.work)) * act;
      const sc = 1 + d.hi * 0.22 + work * 0.14 + pulse.boost * 0.06 + wWork * 0.08;
      d.mesh.scale.setScalar(sc);
      d.mat.emissiveIntensity = 0.22 + d.hi * 0.9 + work * 0.6 + pulse.boost * 0.3;
      setGlow(G_DOT + k, d.mesh.position, 0.9 + d.hi * 0.5 + work * 0.3, d.glow, 0.16 + d.hi * 0.6 + work * 0.35 + act * 0.05 + pulse.boost * 0.1);
    });

    // the hub
    const hv = smooth(wHub * 1.3);
    hub.visible = hv > 0.01;
    hub.position.copy(hubPos);
    hub.scale.setScalar(Math.max(0.001, hv));
    const upright = wHub ? wC / wHub : 0; // standing in the vortex; facing the page in the other shapes
    hub.rotation.set((1 - upright) * (Math.PI / 2) + Math.sin(t * 0.5) * 0.06, t * 0.35, 0);
    const beat = 0.75 + 0.25 * Math.sin(t * 3.2) + pulse.boost * 0.5;
    eyeMat.opacity = (0.55 + act * 0.25) * beat;
    core.scale.setScalar(0.85 + beat * 0.2);
    hubSeam.material.opacity = 0.6 + act * 0.3;
    hubLight.position.copy(hubPos);
    hubLight.intensity = hv * 16 * (0.7 + act * 0.3) + pulse.boost * 5;
    setGlow(G_HUB, hubPos, 2.4, glowHub, hv * (0.45 + act * 0.25 + pulse.boost * 0.3));

    // sparks of work running along the cables: in towards the hub (and the middle of the mark)
    const sv = (0.35 + act * 0.45) * (1 - wS * 0.8) * grow;
    sparks.forEach((sp, j) => {
      const u = (sp.ph + t * sp.speed * (0.8 + act * 0.5)) % 1;
      pointAt(sp.k, u, sparkP);
      const vis = sv * Math.sin(u * Math.PI) * (j < 6 ? 1 : wHub * 0.7 + wM * 0.3 + wR * 0.5);
      setGlow(G_SPARK + j, sparkP, 0.34, sp.glow, vis * 0.55);
    });

    // the plan: cards beside the rope; the current one lights up
    const pv = smooth(wP * 1.2);
    plan.visible = pv > 0.01;
    const prog = clock.plan % 7.5;
    const px = narrow ? -1.2 : 4.1, py = narrow ? -3.6 : 0.6;
    cards.forEach((cd) => {
      const appear = smooth(pv * 1.6 - cd.i * 0.1);
      const y = (cd.goal ? 1.45 : 1.1 - cd.i * 0.52) + (1 - appear) * -0.5;
      cd.card.position.set(px + (cd.goal ? 0.1 : 0) + (1 - appear) * 0.8, py + y, 0.3);
      cd.card.rotation.y = (1 - appear) * -0.9;
      cd.card.scale.setScalar(Math.max(0.001, appear) * (narrow ? 0.75 : 1));
      cd.card.visible = appear > 0.01;
      if (!cd.goal) {
        const st = prog > cd.i ? "done" : prog > cd.i - 1 ? "now" : "todo";
        if (st !== cd.st) { cd.st = st; cd.faceMat.map = cd.tex[st]; }
        cd.body.material.emissiveIntensity = st === "now" ? 0.05 + Math.sin(t * 5) * 0.025 : 0;
      }
    });
    // the code: a panel that types itself, fed by the orange agent
    const kv = smooth(wK * 1.2);
    codePanel.visible = kv > 0.01;
    codePanel.position.set(narrow ? -1.2 : 4.3 + (1 - kv) * 0.8, narrow ? -3.6 : 0.6, 0.4);
    codePanel.rotation.y = (1 - kv) * -0.8;
    codePanel.scale.setScalar(Math.max(0.001, kv) * (narrow ? 0.7 : 1));
    if (codePanel.visible) {
      if (typing.line >= lines.length - 1 && typing.col >= lineLen[lines.length - 1]) {
        typing.hold += dt;
        if (typing.hold > 2.6) { typing.line = 0; typing.col = 0; typing.hold = 0; }
      } else {
        typing.col += dt * 46 * (0.6 + act * 0.5);
        while (typing.col > lineLen[typing.line] + 2 && typing.line < lines.length - 1) { typing.col -= lineLen[typing.line] + 2; typing.line++; }
      }
      codeU.uLine.value = typing.line;
      codeU.uCol.value = Math.min(typing.col, lineLen[typing.line]);
      codeU.uTime.value = t;
    }

    // the belt of models
    const rv = smooth(wR * 1.15);
    belt.visible = rv > 0.01;
    if (belt.visible) {
      tokenData.forEach((d, i) => {
        const a = d.a + t * d.speed;
        const rr = d.r * (0.6 + rv * 0.4);
        tokP.set(RC.x + Math.cos(a) * rr, RC.y + d.y + Math.sin(t * 2 + i) * 0.02, RC.z + Math.sin(a) * rr);
        tokE.set(d.spin, -a + d.spin * 0.3, 0);
        tokM.compose(tokP, tokQ.setFromEuler(tokE), tokS.setScalar(d.s * smooth(rv * 1.4 - (i % 12) * 0.03)));
        belt.setMatrixAt(i, tokM);
      });
      belt.instanceMatrix.needsUpdate = true;
    }

    // the shock ring
    if (pulse.t < 1) {
      pulse.t = Math.min(1, pulse.t + dt * 0.75);
      const e = 1 - Math.pow(1 - pulse.t, 3);
      shock.visible = true;
      shock.position.copy(hubPos);
      shock.scale.setScalar(0.6 + e * (5 + pulse.strength * 3));
      shock.quaternion.copy(q);
      shockMat.opacity = (1 - pulse.t) * (0.6 + pulse.strength * 0.4);
    } else shock.visible = false;

    glowGeo.attributes.position.needsUpdate = true;
    glowGeo.attributes.aCol.needsUpdate = true;
    glowGeo.attributes.aSize.needsUpdate = true;

    renderer.render(scene, camera);
  };
  requestAnimationFrame(frame);

  /** Send a shock ring out from the hub and make everything busy for a moment. */
  const burst = (strength = 1) => {
    pulse.t = 0;
    pulse.strength = strength;
    pulse.boost = Math.min(3, pulse.boost + strength * 1.6);
  };
  const setLevel = (n) => { level = n; applyQuality(); };
  return { state, burst, fit, three: { renderer, scene, camera, typing, clock, frame, setLevel, cables: K, render: () => renderer.render(scene, camera), quality: () => [`${BUDGET[level]} MP`, `${renderer.getPixelRatio().toFixed(2)}x`, `${K} cables · ${cableGeo.attributes.position.count} verts`] } }; // three: for the console
}
