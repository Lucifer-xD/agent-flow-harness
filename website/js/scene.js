// The 3D world behind every page, made of real, lit objects. It starts as AFH's mark: three glossy
// candy-glass strands with light running inside them, joining six glossy spheres. Each strand is
// two cables that meet in the middle, so when the page moves on, the same cables bend and stretch
// into the links of a working team: the spheres become agents orbiting a molten core in a glass
// bubble (with three polished gyroscope rings), and sparks of work run out along the cables and
// results run back. The core can lay out a plan (glass cards it ticks off), write a file (a panel
// that types itself, fed by a cable from the core) or open into a belt of 228 model tokens.
//
// Built to stay smooth on integrated graphics: the cables are bent on the GPU (a cubic curve per
// cable, four points as uniforms), glow comes from soft halos drawn in one pass instead of a bloom
// pass, and the drawing size is held to a pixel budget that steps down by itself if frames run long.
//
// The page steers it through `state` (numbers, eased by the caller):
//   shapes   mark core net plan code ring spread — weights; the world takes their blend
//   framing  zoom spin tilt shiftX shiftY        mood  activity (how busy) · dim (brightness)
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { CODE, TOKEN_COLORS } from "./code-sample.js";

// The logo (viewBox 240×140): each strand is two cubic segments meeting at a middle point, with a
// depth per control point so the strands weave past each other.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: "#ffb11f", to: "#ff7a3d" },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68" },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: "#ff3d8a", to: "#e0169a" },
];
const ENDS = [[0, 0], [1, 0], [2, 0], [2, 6], [1, 6], [0, 6]]; // agent k = [strand, point], round the mark
const AGENT_COLORS = ["#ffb11f", "#ff7747", "#ff3d8a", "#e0169a", "#ff4a68", "#ff7a3d"];
const SHAPES = ["mark", "core", "net", "plan", "code", "ring", "spread"];
const PLAN = ["Read the auth code", "Build the login form", "Add session handling", "Write the tests", "Run them and fix"];
const S = 1 / 30;
const toV = ([x, y], z) => new THREE.Vector3((x - 120) * S, -(y - 70) * S, z);
const UP = new THREE.Vector3(0, 1, 0);
// additive light that leaves the canvas alpha alone, so it adds onto the page's CSS background
// instead of punching opaque black squares into it
const ADD = { blending: THREE.CustomBlending, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneFactor, blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor };
const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };

// ---------- the cables ----------
// A tube along a cubic curve, built in (t, angle, cap) space; the vertex shader bends it.
function cableGeometry(seg = 140, rad = 22, cap = 6) {
  const rows = [];
  for (let k = 0; k < cap; k++) rows.push([0, -Math.PI / 2 + (k / cap) * (Math.PI / 2)]);
  for (let i = 0; i <= seg; i++) rows.push([i / seg, 0]);
  for (let k = 1; k <= cap; k++) rows.push([1, (k / cap) * (Math.PI / 2)]);
  const pos = new Float32Array(rows.length * (rad + 1) * 3);
  rows.forEach(([t, ph], r) => { for (let j = 0; j <= rad; j++) pos.set([t, (j / rad) * Math.PI * 2, ph], (r * (rad + 1) + j) * 3); });
  const idx = [];
  for (let r = 0; r < rows.length - 1; r++) for (let j = 0; j < rad; j++) {
    const a = r * (rad + 1) + j, b = a + rad + 1;
    idx.push(a, a + 1, b, b, a + 1, b + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx);
  return g;
}

function cableMaterial() {
  const u = {
    uA: { value: new THREE.Vector3() }, uB: { value: new THREE.Vector3() }, uC: { value: new THREE.Vector3() }, uD: { value: new THREE.Vector3() },
    uRef: { value: new THREE.Vector3(0, 0, 1) }, uRadius: { value: 0.1 }, uGrow: { value: 1 },
    uColA: { value: new THREE.Color() }, uColB: { value: new THREE.Color() },
    uFlow: { value: 0 }, uDir: { value: 1 }, uGlow: { value: 0.2 }, uPulse: { value: 1 }, uSeed: { value: Math.random() },
  };
  const mat = new THREE.MeshStandardMaterial({ roughness: 0.24, metalness: 0, envMapIntensity: 0.6, emissive: 0xffffff });
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", `#include <common>
        uniform vec3 uA, uB, uC, uD, uRef; uniform float uRadius, uGrow; varying float vT;
        vec3 cub(float t) { float s = 1.0 - t; return s * s * s * uA + 3.0 * s * s * t * uB + 3.0 * s * t * t * uC + t * t * t * uD; }
        vec3 cubD(float t) { float s = 1.0 - t; return 3.0 * s * s * (uB - uA) + 6.0 * s * t * (uC - uB) + 3.0 * t * t * (uD - uC); }`)
      .replace("#include <beginnormal_vertex>", `
        float tt = position.x * uGrow;
        vec3 T = normalize(cubD(clamp(tt, 0.002, 0.998)) + 1e-6);
        vec3 N = normalize(cross(T, uRef) + 1e-6), Bn = cross(T, N);
        vec3 ring = cos(position.y) * N + sin(position.y) * Bn;
        vec3 objectNormal = ring * cos(position.z) + T * sin(position.z);
        vT = tt;`)
      .replace("#include <begin_vertex>", "vec3 transformed = cub(tt) + objectNormal * uRadius;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>
        uniform vec3 uColA, uColB; uniform float uFlow, uDir, uGlow, uPulse, uSeed; varying float vT;`)
      .replace("vec4 diffuseColor = vec4( diffuse, opacity );", "vec3 cab = mix(uColA, uColB, vT); vec4 diffuseColor = vec4(cab, opacity);")
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        // light travelling inside the glass: soft bands plus a bright packet
        float x = vT * 1.4 - uFlow * 0.55 * uDir + uSeed;
        float band = 0.5 + 0.5 * sin(x * 6.2832 * 2.0);
        float pk = fract(x);
        float packet = pow(max(0.0, 1.0 - pk / 0.09), 2.0);
        totalEmissiveRadiance = cab * (uGlow * (0.55 + 0.45 * band) + packet * uPulse * 2.2);`);
  };
  mat.customProgramCacheKey = () => "afh-cable";
  return { mat, u };
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
  // the backdrop is CSS (free): a warm haze behind the core and a pink one lower left
  canvas.style.background = "radial-gradient(60% 70% at 62% 46%, #2a1007 0%, rgba(42,16,7,0) 70%), radial-gradient(45% 55% at 25% 70%, #1f0716 0%, rgba(31,7,22,0) 70%), #0a0807";
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; // studio reflections on the gloss and metal
  const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.1, 150);
  camera.position.set(0, 0, 10);
  const world = new THREE.Group();
  scene.add(world);

  // lights: a warm key from above left, a pink rim from behind, and the core's own light
  const key = new THREE.DirectionalLight(0xfff0e4, 1.1); key.position.set(-4, 6, 6); scene.add(key);
  const rim = new THREE.DirectionalLight(0xff4a8a, 1.6); rim.position.set(5, -2, -6); scene.add(rim);
  scene.add(new THREE.HemisphereLight(0xffe6d6, 0x140806, 0.2));
  const coreLight = new THREE.PointLight(0xff8040, 0, 0, 2);
  world.add(coreLight);

  // drifting dust for depth
  const D = mobile ? 600 : 1100;
  const dp = new Float32Array(D * 3);
  for (let i = 0; i < D; i++) dp.set([(Math.random() * 2 - 1) * 36, (Math.random() * 2 - 1) * 22, -Math.random() * 40 + 3], i * 3);
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
  const dust = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0xffc9a8, size: 0.045, transparent: true, opacity: 0.5, depthWrite: false, ...ADD }));
  scene.add(dust);

  // ---- the mark's geometry: half-strands (end → middle) and where things sit ----
  const strandV = STRANDS.map((s) => s.pts.map((p, i) => toV(p, s.z[i])));
  const halves = ENDS.map(([s, p]) => (p === 0 ? [0, 1, 2, 3] : [6, 5, 4, 3]).map((i) => strandV[s][i]));
  const halfMidColor = ENDS.map(([s]) => new THREE.Color(STRANDS[s].from).lerp(new THREE.Color(STRANDS[s].to), 0.5));
  const endPos = ENDS.map(([s, p]) => strandV[s][p]);
  const markCenter = new THREE.Vector3(0.45, 0.11, 0);
  const agentCol = AGENT_COLORS.map((c) => new THREE.Color(c));
  const amber = new THREE.Color("#ffb11f");

  // ---- cables: 0–5 core↔agent (the mark's half-strands), 6–11 agent→next agent, 12 the core's feed ----
  const cableGeo = cableGeometry(mobile ? 100 : 140, mobile ? 16 : 22);
  const cables = Array.from({ length: 13 }, (_, i) => {
    const { mat, u } = cableMaterial();
    const mesh = new THREE.Mesh(cableGeo, mat);
    mesh.frustumCulled = false;
    world.add(mesh);
    return { mesh, u, A: new THREE.Vector3(), B: new THREE.Vector3(), C: new THREE.Vector3(), D: new THREE.Vector3(), i };
  });

  // ---- agents: glossy spheres, with a spinning halo while they work ----
  const sphereGeo = new THREE.SphereGeometry(1, 56, 40);
  const haloGeo = new THREE.TorusGeometry(1.32, 0.03, 8, 96);
  const agents = agentCol.map((c, k) => {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: c, roughness: 0.18, metalness: 0, envMapIntensity: 0.7, emissive: c, emissiveIntensity: 0.3 });
    const ball = new THREE.Mesh(sphereGeo, mat);
    const haloMat = new THREE.MeshBasicMaterial({ color: c.clone().multiplyScalar(1.3), transparent: true, opacity: 0, depthWrite: false });
    const halo = new THREE.Mesh(haloGeo, haloMat);
    halo.rotation.set(1.1 + k * 0.4, k * 0.9, 0);
    g.add(ball, halo);
    world.add(g);
    return { g, ball, mat, halo, haloMat, pos: new THREE.Vector3(), hi: 0, r: 0.4 };
  });

  // ---- the core: molten inside, a glass bubble round it, three polished gyroscope rings ----
  const core = new THREE.Group();
  world.add(core);
  const coreU = { uTime: { value: 0 }, uEnergy: { value: 1 } };
  const coreMat = new THREE.MeshStandardMaterial({ color: 0x1a0602, roughness: 0.55, envMapIntensity: 0.2, emissive: 0xffffff });
  coreMat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, coreU);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nuniform float uTime, uEnergy; varying vec3 vObj;")
      .replace("#include <begin_vertex>", `vec3 transformed = position;
        vObj = position;
        transformed += normal * (sin(position.x * 7.0 + uTime * 1.7) * sin(position.y * 6.0 - uTime * 1.3) * sin(position.z * 6.5 + uTime) * 0.035 * uEnergy);`);
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform float uTime, uEnergy; varying vec3 vObj;")
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        vec3 q = normalize(vObj);
        float n = sin(q.x * 4.0 + uTime * 0.8) * sin(q.y * 5.0 - uTime * 0.6) * sin(q.z * 4.5 + uTime * 0.45);
        // cracks where a sum of waves crosses zero: a network of thin glowing seams in an ember crust
        float w = sin(q.x * 7.0 + q.y * 3.0 + uTime * 0.9 + n * 2.0) + sin(q.y * 8.0 - q.z * 4.0 - uTime * 0.7) + sin(q.z * 6.0 + q.x * 5.0 + uTime * 0.5);
        float cracks = 1.0 - smoothstep(0.0, 0.17, abs(w));
        float lava = 0.5 + 0.5 * n;
        vec3 crust = mix(vec3(0.3, 0.035, 0.008), vec3(0.85, 0.18, 0.02), lava);
        vec3 glow = mix(vec3(1.0, 0.4, 0.06), vec3(1.0, 0.8, 0.4), lava);
        totalEmissiveRadiance = crust * (0.22 + 0.3 * uEnergy) + glow * cracks * (1.1 + 1.3 * uEnergy);`);
  };
  core.add(new THREE.Mesh(sphereGeo, coreMat));
  // the bubble: clear where you look straight through, bright at the rim, with a sharp highlight
  const shell = new THREE.Mesh(sphereGeo, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, ...ADD,
    vertexShader: /* glsl */ `varying vec3 vN, vView;
      void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: /* glsl */ `varying vec3 vN, vView;
      void main() {
        float f = pow(1.0 - max(dot(vN, vView), 0.0), 3.0);
        float spec = pow(max(dot(reflect(-normalize(vec3(-0.5, 0.8, 0.6)), vN), vView), 0.0), 80.0);
        gl_FragColor = vec4(vec3(1.0, 0.78, 0.62) * f * 0.45 + vec3(1.0, 0.95, 0.9) * spec * 0.9, 1.0);
      }`,
  }));
  shell.scale.setScalar(1.32);
  shell.renderOrder = 2;
  core.add(shell);
  const metal = new THREE.MeshStandardMaterial({ color: 0xf0c8ae, metalness: 1, roughness: 0.24, envMapIntensity: 0.9 });
  const gyros = [0, 1, 2].map((i) => {
    const pivot = new THREE.Group();
    const r = 1.62 + i * 0.2;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.026, 14, 220), metal);
    const bead = new THREE.Mesh(new THREE.SphereGeometry(0.07, 20, 14), new THREE.MeshBasicMaterial({ color: agentCol[i * 2].clone().lerp(new THREE.Color("#fff1e0"), 0.4) }));
    bead.position.x = r;
    ring.add(bead);
    pivot.add(ring);
    pivot.rotation.set(i * 1.05 + 0.35, i * 0.7, i * 0.4);
    core.add(pivot);
    return { ring, bead, speed: (0.4 + i * 0.22) * (i % 2 ? -1 : 1) };
  });

  // ---- sparks: beads of light riding the cables (work out, results back) ----
  const SPARKS = 13 * 3;
  const sparks = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff }), SPARKS);
  sparks.frustumCulled = false;
  world.add(sparks);
  const sparkSeed = Array.from({ length: SPARKS }, () => Math.random());
  const sparkColor = new THREE.Color();

  // ---- glows: soft halos round everything that gives off light, in one draw (instead of bloom) ----
  const CABLE_GLOW = 14, GC = 1 + 6 + SPARKS + 3; // halo beads traced along each cable, and where they start
  const GLOWS = GC + 13 * CABLE_GLOW; // core, agents, sparks, gyro beads, cables
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
  const srgb = (c) => c.clone().convertLinearToSRGB();
  const glowAgent = agentCol.map(srgb), glowCore = srgb(new THREE.Color("#ff6a2a"));
  const setGlow = (i, p, size, c, k) => { glowPos[i * 3] = p.x; glowPos[i * 3 + 1] = p.y; glowPos[i * 3 + 2] = p.z; glowSize[i] = size; glowCol[i * 3] = c.r * k; glowCol[i * 3 + 1] = c.g * k; glowCol[i * 3 + 2] = c.b * k; };

  // ---- the plan: glass cards beside the core, ticked off as it works ----
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

  // ---- the models: a belt of glossy tokens round the core ----
  const TOKENS = 228;
  const belt = new THREE.InstancedMesh(new RoundedBoxGeometry(1, 1, 1, 2, 0.28), new THREE.MeshStandardMaterial({ roughness: 0.22, envMapIntensity: 0.65, emissive: 0x3a1206, emissiveIntensity: 1 }), TOKENS);
  belt.frustumCulled = false;
  world.add(belt);
  const tokenData = Array.from({ length: TOKENS }, (_, i) => {
    const lane = i % 3;
    belt.setColorAt(i, agentCol[(i * 7) % 6].clone().lerp(new THREE.Color("#fff1e0"), Math.random() * 0.35));
    return { a: Math.random() * Math.PI * 2, r: 2.9 + lane * 0.62 + (Math.random() - 0.5) * 0.4, y: (Math.random() - 0.5) * 0.35, s: 0.07 + Math.random() * 0.07, spin: Math.random() * 6, speed: 0.22 / (1 + lane * 0.45) };
  });
  const tokM = new THREE.Matrix4(), tokQ = new THREE.Quaternion(), tokE = new THREE.Euler(), tokP = new THREE.Vector3(), tokS = new THREE.Vector3();

  // ---- a click (or a download) sends a shock ring out from the core ----
  const shockMat = new THREE.MeshBasicMaterial({ color: new THREE.Color("#ff8a50").multiplyScalar(3), transparent: true, opacity: 0, depthWrite: false, ...ADD, side: THREE.DoubleSide });
  const shock = new THREE.Mesh(new THREE.TorusGeometry(1, 0.012, 8, 160), shockMat);
  world.add(shock);
  const pulse = { t: 1, strength: 0, boost: 0 };

  const v1 = new THREE.Vector3(), v2 = new THREE.Vector3(), v3 = new THREE.Vector3(), v4 = new THREE.Vector3(), v5 = new THREE.Vector3();

  // ---- drawing size: a pixel budget (megapixels) that steps down by itself if frames run long ----
  const BUDGET = mobile ? [1.6, 1.1, 0.8] : lite ? [1.8, 1.3, 0.9] : [2.6, 1.9, 1.4, 1.0, 0.75];
  let level = 0, narrow = false; // narrow: a portrait screen, so the plan and code sit below the core, not beside it
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
  const balls = agents.map((a) => a.ball);

  // where each agent is in each shape
  const orbit = (k, t, s, v) => {
    const m3 = k % 3, r = (2.7 + m3 * 0.5) * s, incl = (m3 - 1) * 0.55 + 0.12;
    const a = t * (0.15 + (k % 2) * 0.06) + k * 1.0471976;
    return v.set(Math.cos(a) * r, Math.sin(a) * r * Math.sin(incl) + Math.sin(t * 0.7 + k) * 0.18, Math.sin(a) * r * Math.cos(incl));
  };
  const ringPos = (k, t, v) => { const a = k * 1.0471976 + t * 0.06; return v.set(Math.cos(a) * 3.55, Math.sin(t * 0.5 + k) * 0.18, Math.sin(a) * 3.55); };
  const lostPos = (k, t, v) => {
    const a = k * 1.0471976 + 0.4 + Math.sin(t * 0.13 + k) * 0.35;
    return v.set(Math.cos(a) * (3.3 + Math.sin(t * 0.3 + k * 2) * 0.5), Math.sin(t * 0.21 + k * 1.7) * 1.4, Math.sin(a) * 1.6 - 0.5);
  };

  const q = new THREE.Quaternion();
  const baseZ = () => 10.5 * Math.max(1, 1.3 / Math.min(camera.aspect, 1.3)); // keep the mark inside narrow screens
  const clock = { last: performance.now(), t: 0, flow: 0, plan: 0 };

  // ---- responsive framing: put the mark exactly into a box on the page ----
  const markBox = new THREE.Box3().setFromPoints(endPos).expandByScalar(0.5);
  const markSize = markBox.getSize(new THREE.Vector3()), markMid = markBox.getCenter(new THREE.Vector3());
  const fitCam = new THREE.PerspectiveCamera(), fitS = new THREE.Vector3(), fitP = new THREE.Vector3(), fitMid = new THREE.Vector3();
  // how much room each shape takes (world units, as seen from the camera; cx/cy: its middle)
  const box = (name) => ({
    mark: { w: markSize.x, h: markSize.y, cx: markMid.x, cy: markMid.y },
    core: { w: 4.6, h: 4.6, cx: 0, cy: 0 },
    plan: narrow ? { w: 4.8, h: 6.6, cx: 0, cy: -0.4 } : { w: 8.2, h: 4.4, cx: 0.05, cy: 0 },
    net: { w: 8, h: 4.8, cx: 0, cy: 0 },
    code: narrow ? { w: 4.8, h: 6.4, cx: 0, cy: -0.4 } : { w: 8.8, h: 4.6, cx: 0.4, cy: 0 },
    ring: { w: 9.6, h: 5, cx: 0, cy: 0 },
  })[name];
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
  const corePos = new THREE.Vector3();
  const tmpCol = new THREE.Color();

  /** Control points of a link from p (an agent) into the core at c, bowed sideways. */
  const link = (p, c, k, out) => {
    v4.subVectors(c, p);
    const len = v4.length();
    v5.crossVectors(v4, UP).normalize().multiplyScalar(len * 0.2 * (k % 2 ? 1 : -1)).addScaledVector(UP, len * 0.1);
    out[0].copy(p); out[3].copy(c);
    out[1].copy(p).addScaledVector(v4, 0.33).add(v5);
    out[2].copy(p).addScaledVector(v4, 0.7).addScaledVector(v5, 0.6);
  };
  const tmpPts = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const cubic = (A, B, C, Dd, t, out) => {
    const s = 1 - t;
    return out.set(0, 0, 0).addScaledVector(A, s * s * s).addScaledVector(B, 3 * s * s * t).addScaledVector(C, 3 * s * t * t).addScaledVector(Dd, t * t * t);
  };
  const setRef = (c) => {
    v1.subVectors(c.D, c.A); v2.addVectors(c.B, c.C).multiplyScalar(0.5).sub(c.A);
    v3.crossVectors(v1, v2);
    if (v3.lengthSq() < 1e-6) v3.crossVectors(v1, Math.abs(v1.y) < 0.9 ? UP : v4.set(1, 0, 0));
    if (v3.lengthSq() < 1e-8) v3.set(0, 0, 1);
    c.u.uRef.value.copy(v3.normalize());
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
    clock.flow += dt * (0.5 + act * 0.8);
    clock.plan += dt * 0.55 * (0.7 + act * 0.3);
    const t = clock.t;
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
    const wWork = wP + wK; // plan and code: agents step back, the core works

    // the core
    const coreScale = wC * 1.0 + wN * 0.62 + wWork * 0.55 + wR * 0.5;
    corePos.copy(markCenter).multiplyScalar(wM + wS);
    core.position.copy(corePos);
    core.visible = coreScale > 0.004;
    core.scale.setScalar(Math.max(0.001, coreScale * (1 + Math.sin(t * 2.1) * 0.012 + pulse.boost * 0.06)));
    coreU.uTime.value = t;
    coreU.uEnergy.value = 0.55 + act * 0.45;
    for (const g of gyros) g.ring.rotation.z += dt * g.speed * (1 + act * 0.8);
    coreLight.position.copy(corePos);
    coreLight.intensity = coreScale * 38 * (0.75 + act * 0.25);

    // agents: where they are, how big, and whether the pointer is on one
    let hovered = -1;
    if (W[0] + W[2] + W[5] > 0.3) {
      ray.setFromCamera(mouse.ndc, camera);
      const hit = ray.intersectObjects(balls, false)[0];
      if (hit) hovered = balls.indexOf(hit.object);
    }
    agents.forEach((a, k) => {
      const p = a.pos.set(0, 0, 0);
      if (wM) p.addScaledVector(endPos[k], wM);
      if (wC) p.addScaledVector(v1.copy(endPos[k]).normalize().multiplyScalar(0.3), wC);
      if (wN) p.addScaledVector(orbit(k, t, 1, v1), wN);
      if (wWork) p.addScaledVector(orbit(k, t, 0.62, v1).add(v2.set(narrow ? 0 : -1.6, narrow ? 1.6 : 0.2, -2.2)), wWork); // the team waits behind
      if (wR) p.addScaledVector(ringPos(k, t, v1), wR);
      if (wS) p.addScaledVector(lostPos(k, t, v1), wS);
      a.hi += ((k === hovered ? 1 : 0) - a.hi) * Math.min(1, dt * 8);
      a.r = 0.46 * wM + 0.27 * wN + 0.15 * wWork + 0.23 * wR + 0.36 * wS;
      a.g.position.copy(p);
      a.g.visible = a.r > 0.01;
      a.g.scale.setScalar(Math.max(0.001, a.r * (1 + a.hi * 0.22 + Math.sin(t * 2 + k) * 0.02)));
      a.mat.emissiveIntensity = 0.42 + a.hi * 0.9 + pulse.boost * 0.2 + act * 0.08;
      a.haloMat.opacity = (wN + wR * 0.7) * (0.35 + a.hi * 0.65);
      a.halo.visible = a.haloMat.opacity > 0.01;
      a.halo.rotation.z += dt * (1.2 + act);
    });

    // cables 0–5: the mark's half-strands, or links from agent k into the core
    for (let k = 0; k < 6; k++) {
      const c = cables[k], a = agents[k];
      c.A.set(0, 0, 0); c.B.set(0, 0, 0); c.C.set(0, 0, 0); c.D.set(0, 0, 0);
      const add = (pts, w) => { if (!w) return; c.A.addScaledVector(pts[0], w); c.B.addScaledVector(pts[1], w); c.C.addScaledVector(pts[2], w); c.D.addScaledVector(pts[3], w); };
      add(halves[k], wM);
      const rest = 1 - wM - wS;
      if (rest > 0) { link(a.pos, corePos, k, tmpPts); add(tmpPts, rest); }
      if (wS) { // lost: the cable has come away from the middle and hangs loose
        const h = halves[k];
        tmpPts[0].copy(a.pos);
        v1.subVectors(h[3], h[0]).multiplyScalar(0.55);
        tmpPts[3].copy(a.pos).add(v1).add(v2.set(Math.sin(t * 0.7 + k) * 0.4, -0.9 + Math.cos(t * 0.5 + k) * 0.3, Math.sin(t * 0.4 + k * 2) * 0.4));
        tmpPts[1].copy(a.pos).addScaledVector(v1, 0.4);
        tmpPts[2].lerpVectors(tmpPts[1], tmpPts[3], 0.6).add(v2.set(0, -0.35, 0));
        add(tmpPts, wS);
      }
      const r = 0.2 * wM + 0.13 * wS + (0.06 * wN + 0.045 * wWork + 0.045 * wR) * (1 + a.hi * 0.6);
      c.u.uRadius.value = r;
      c.mesh.visible = r > 0.004;
      c.u.uGrow.value = 1;
      c.u.uColA.value.copy(agentCol[k]);
      c.u.uColB.value.copy(halfMidColor[k]).lerp(amber, 1 - wM - wS);
      c.u.uDir.value = wM > 0.5 ? (k < 3 ? 1 : -1) : -1;
      c.u.uGlow.value = (0.22 + a.hi * 0.4) * (0.8 + act * 0.25);
      c.u.uPulse.value = (0.6 + act * 0.6) * (1 + a.hi);
      setRef(c);
    }
    // cables 6–11: agent k → agent k+1, grown in while the team works
    for (let k = 0; k < 6; k++) {
      const c = cables[6 + k], a = agents[k].pos, b = agents[(k + 1) % 6].pos;
      v4.subVectors(b, a);
      v5.addVectors(a, b).multiplyScalar(0.5).sub(corePos).normalize().multiplyScalar(v4.length() * 0.22);
      c.A.copy(a); c.D.copy(b);
      c.B.copy(a).addScaledVector(v4, 0.33).add(v5);
      c.C.copy(a).addScaledVector(v4, 0.67).add(v5);
      const grow = smooth((wN + wR + wWork * 0.7) * 1.15);
      c.u.uGrow.value = grow;
      c.u.uRadius.value = 0.03 * grow;
      c.mesh.visible = grow > 0.01;
      c.u.uColA.value.copy(agentCol[k]); c.u.uColB.value.copy(agentCol[(k + 1) % 6]);
      c.u.uDir.value = 1; c.u.uGlow.value = 0.3; c.u.uPulse.value = 0.5 + act * 0.4;
      setRef(c);
    }

    // the plan: cards stacked beside the core; the current one lights up and the core feeds it
    const pv = smooth(wP * 1.2);
    plan.visible = pv > 0.01;
    const prog = clock.plan % 7.5;
    const nowIdx = Math.min(5, Math.max(1, Math.floor(prog) + 1));
    const px = narrow ? 0 : 2.75, py = narrow ? -2.2 : 0;
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
    // the code: a panel that types itself
    const kv = smooth(wK * 1.2);
    codePanel.visible = kv > 0.01;
    codePanel.position.set(narrow ? 0 : 2.85 + (1 - kv) * 0.8, narrow ? -2.1 : 0, 0.4);
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
    // the feed: a cable from the core to whatever it is working on
    {
      const c = cables[12];
      const r = 0.05 * (pv + kv);
      c.mesh.visible = r > 0.003;
      if (c.mesh.visible) {
        const target = v3;
        if (pv >= kv) { // the current card's tick box
          const s = narrow ? 0.75 : 1;
          target.set(px + (-1.152 + (62 / 700) * 2.304) * s, py + 1.1 - nowIdx * 0.52, 0.36);
        } else { // the caret
          const s = narrow ? 0.7 : 1, k = 3.6 / CODE_W;
          target.copy(codePanel.position).add(v4.set((-1.8 + (CX + codeU.uCol.value * CW) * k) * s, (CODE_H / 2 - (CY + codeU.uLine.value * LH - 8)) * k * s, 0.06));
        }
        target.applyQuaternion(face.quaternion);
        c.A.copy(corePos); c.D.copy(target);
        v4.subVectors(target, corePos);
        c.B.copy(corePos).addScaledVector(v4, 0.35).addScaledVector(UP, 0.6);
        c.C.copy(corePos).addScaledVector(v4, 0.75).addScaledVector(UP, 0.35);
        c.u.uRadius.value = r; c.u.uGrow.value = 1;
        c.u.uColA.value.copy(amber); c.u.uColB.value.set("#ff6a2a");
        c.u.uDir.value = 1; c.u.uGlow.value = 0.4; c.u.uPulse.value = 1.4;
        setRef(c);
      }
    }
    for (const c of cables) {
      c.u.uFlow.value = clock.flow;
      c.u.uA.value.copy(c.A); c.u.uB.value.copy(c.B); c.u.uC.value.copy(c.C); c.u.uD.value.copy(c.D);
    }

    // sparks: three per cable; core links send work out and get results back
    let si = 0;
    const sparkVis = 1 - wM - wS;
    for (const c of cables) {
      for (let j = 0; j < 3; j++, si++) {
        const visible = c.mesh.visible && sparkVis > 0.05 && (c.i !== 12 || j < 2);
        if (!visible) { tokM.makeScale(0, 0, 0); sparks.setMatrixAt(si, tokM); glowSize[7 + si] = 0; continue; }
        const back = c.i < 6 && j === 2;
        let s = (sparkSeed[si] + clock.flow * (0.22 + sparkSeed[si] * 0.08)) % 1;
        if (c.i < 6) s = back ? s : 1 - s; // P0 is the agent, P3 the core
        s *= c.u.uGrow.value;
        cubic(c.A, c.B, c.C, c.D, s, tokP);
        const size = (c.u.uRadius.value * 1.2 + 0.012) * sparkVis * (0.8 + Math.sin(s * Math.PI) * 0.4);
        tokM.compose(tokP, tokQ.identity(), tokS.setScalar(size));
        sparks.setMatrixAt(si, tokM);
        sparkColor.copy(back ? tmpCol.set("#ff7ab6") : c.i === 12 ? amber : agentCol[c.i % 6]).lerp(tmpCol.set("#fff1e0"), 0.25).multiplyScalar(1.5 + act * 0.5);
        sparks.setColorAt(si, sparkColor);
        setGlow(7 + si, tokP, size * 7, sparkColor.convertLinearToSRGB(), 0.18);
      }
    }
    sparks.instanceMatrix.needsUpdate = true;
    if (sparks.instanceColor) sparks.instanceColor.needsUpdate = true;

    // the models' belt
    const rv = smooth(wR * 1.15);
    belt.visible = rv > 0.01;
    if (belt.visible) {
      tokenData.forEach((d, i) => {
        const a = d.a + t * d.speed;
        const rr = d.r * (0.6 + rv * 0.4);
        tokP.set(Math.cos(a) * rr, d.y + Math.sin(t * 0.8 + i) * 0.04, Math.sin(a) * rr).add(corePos);
        tokE.set(d.spin + t * 0.6, d.spin * 2 + t * 0.4, 0);
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
      shock.position.copy(corePos);
      shock.scale.setScalar(0.6 + e * (5 + pulse.strength * 3));
      shock.quaternion.copy(q);
      shockMat.opacity = (1 - pulse.t) * (0.6 + pulse.strength * 0.4);
    } else shock.visible = false;

    // glows
    const live = (wN + wR + wWork * 0.6) * (0.8 + act * 0.2);
    setGlow(0, corePos, coreScale * 6.4 * (1 + pulse.boost * 0.15), glowCore, Math.min(0.95, coreScale * 0.9) * (0.8 + act * 0.25));
    agents.forEach((a, k) => setGlow(1 + k, a.pos, a.r * (5.2 + a.hi * 2.6), glowAgent[k], (0.55 + wM * 0.1 + live * 0.25 + a.hi * 0.5 + pulse.boost * 0.2) * (a.g.visible ? 1 : 0)));
    // every cable glows along its length: overlapping soft beads read as one continuous halo
    for (const c of cables) {
      const base = GC + c.i * CABLE_GLOW;
      if (!c.mesh.visible) { for (let j = 0; j < CABLE_GLOW; j++) glowSize[base + j] = 0; continue; }
      const r = c.u.uRadius.value, g = c.u.uGrow.value;
      const k = (0.1 + c.u.uGlow.value * 0.32 + pulse.boost * 0.08) * Math.min(1, r * 14);
      for (let j = 0; j < CABLE_GLOW; j++) {
        const s = ((j + 0.5) / CABLE_GLOW) * g;
        cubic(c.A, c.B, c.C, c.D, s, v1);
        tmpCol.copy(c.u.uColA.value).lerp(c.u.uColB.value, s).convertLinearToSRGB();
        setGlow(base + j, v1, r * 7 + 0.22, tmpCol, k);
      }
    }
    gyros.forEach((g, i) => { g.bead.getWorldPosition(v1); world.worldToLocal(v1); setGlow(7 + SPARKS + i, v1, 0.55 * coreScale, glowAgent[i * 2], core.visible ? 0.6 : 0); });
    glowGeo.attributes.position.needsUpdate = true;
    glowGeo.attributes.aCol.needsUpdate = true;
    glowGeo.attributes.aSize.needsUpdate = true;

    renderer.render(scene, camera);
  };
  requestAnimationFrame(frame);

  /** Send a shock ring out from the core and make every cable busy for a moment. */
  const burst = (strength = 1) => {
    pulse.t = 0;
    pulse.strength = strength;
    pulse.boost = Math.min(3, pulse.boost + strength * 1.6);
  };
  const setLevel = (n) => { level = n; applyQuality(); };
  return { state, burst, fit, three: { renderer, scene, camera, typing, setLevel, render: () => renderer.render(scene, camera), quality: () => [`${BUDGET[level]} MP`, `${renderer.getPixelRatio().toFixed(2)}x`] } }; // three: for the console
}
