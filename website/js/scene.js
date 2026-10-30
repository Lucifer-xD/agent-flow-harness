// The 3D world behind every page. AFH's mark (three strands joining six points) is the start:
// the six points are agents, and as the page moves on they come apart into a living network —
// orbiting a lead core, joined by links that carry light packets out (work handed over) and back
// (results). Thousands of particles flow along the strands, then along the links, then out into a
// wide ring of models. A plan of glass cards and a panel of code being typed appear when the page
// talks about them. Hovering an agent lights its links; a click sends a pulse out from the core.
//
// The page steers it all through `state` (numbers, eased by the caller):
//   zoom spin tilt shiftX shiftY  framing      mark   the strands (0..1)
//   net     agents: 0 logo · 1 network · 2 ring  core   the lead core (0..1)
//   flow    particles: 0 strands · 1 links · 2 ring  tiles/code  the plan cards / code panel (0..1)
//   spread  particle scatter   activity  how busy the links are   dim  overall brightness
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { CODE, TOKEN_COLORS } from "./code-sample.js";

// The logo's SVG paths (viewBox 240×140), each as two cubic segments sharing a middle point,
// plus a depth (z) per control point so the strands weave in 3D.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.5, 0.1, -0.6, 0], from: "#ffb11f", to: "#ff7a3d" },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68" },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.5, -0.1, 0.6, 0], from: "#ff3d8a", to: "#e0169a" },
];
// the six agents, going round the mark: left column top→bottom, then right column bottom→top
const NODES = [[0, 0], [1, 0], [2, 0], [2, 6], [1, 6], [0, 6]]; // [strand, control point]
const NODE_COLORS = ["#ffb11f", "#ff7747", "#ff3d8a", "#e0169a", "#ff4a68", "#ff7a3d"];
const LINKS = 12; // 0–5: core → agent k, 6–11: agent k → agent k+1
const S = 1 / 30;
const toV = ([x, y], z) => new THREE.Vector3((x - 120) * S, -(y - 70) * S, z);
const PLAN = ["Read the auth code", "Build the login form", "Add session handling", "Write the tests", "Run them and fix"];

const NOISE_GLSL = /* glsl */ `
  // 3D simplex noise (Ashima Arts / Stefan Gustavson, MIT)
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }
`;

const CURVES_GLSL = /* glsl */ `
  uniform vec3 uP[21];
  uniform vec3 uLA[12], uLB[12], uLC[12];
  vec3 bez3(vec3 a, vec3 b, vec3 c, vec3 d, float t) {
    float u = 1.0 - t;
    return u*u*u*a + 3.0*u*u*t*b + 3.0*u*t*t*c + t*t*t*d;
  }
  vec3 strandAt(int s, float t) {
    int seg = t < 0.5 ? 0 : 1;
    float lt = seg == 0 ? t * 2.0 : t * 2.0 - 1.0;
    int b = s * 7 + seg * 3;
    return bez3(uP[b], uP[b + 1], uP[b + 2], uP[b + 3], lt);
  }
  vec3 linkAt(int l, float t) {
    float u = 1.0 - t;
    return u*u*uLA[l] + 2.0*u*t*uLC[l] + t*t*uLB[l];
  }
`;

/** A sphere of living light: noise-driven plasma with a bright rim. */
function plasma(a, b, c) {
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { uTime: { value: 0 }, uEnergy: { value: 1 }, uOpacity: { value: 1 }, uA: { value: new THREE.Color(a) }, uB: { value: new THREE.Color(b) }, uC: { value: new THREE.Color(c) } },
    vertexShader: /* glsl */ `
      ${NOISE_GLSL}
      uniform float uTime, uEnergy;
      varying vec3 vN, vView, vP;
      void main() {
        float n = snoise(normal * 1.8 + vec3(0.0, uTime * 0.45, 0.0));
        vec3 p = position + normal * n * 0.045 * uEnergy;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vN = normalize(normalMatrix * normal); vView = normalize(-mv.xyz); vP = position;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      ${NOISE_GLSL}
      uniform float uTime, uEnergy, uOpacity; uniform vec3 uA, uB, uC;
      varying vec3 vN, vView, vP;
      void main() {
        vec3 q = normalize(vP);
        float n1 = snoise(q * 2.4 + vec3(0.0, uTime * 0.35, uTime * 0.12));
        float n2 = snoise(q * 6.5 - vec3(uTime * 0.5) + n1 * 0.8);
        vec3 col = mix(uA, uB, smoothstep(-0.4, 0.6, n1));
        col = mix(col, uC, smoothstep(0.2, 0.9, n2));
        float veins = smoothstep(0.82, 0.98, 1.0 - abs(n2));
        float fres = pow(1.0 - max(dot(vN, vView), 0.0), 2.2);
        col *= 0.32 + 0.22 * uEnergy;
        col += veins * mix(uA, vec3(1.0, 0.85, 0.6), 0.35) * (0.25 + 0.45 * uEnergy);
        col += fres * mix(uB, vec3(1.0, 0.9, 0.8), 0.25) * 0.55;
        gl_FragColor = vec4(col, uOpacity);
      }`,
  });
}

/** Glass: clear where you look straight through, bright at the rim, with a sharp highlight. */
function glassMaterial(tint = "#ffd9c2") {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTint: { value: new THREE.Color(tint) }, uOpacity: { value: 1 } },
    vertexShader: /* glsl */ `
      varying vec3 vN, vView;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal); vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uTint; uniform float uOpacity;
      varying vec3 vN, vView;
      void main() {
        float f = pow(1.0 - max(dot(vN, vView), 0.0), 3.0);
        vec3 L = normalize(vec3(-0.5, 0.8, 0.6));
        float spec = pow(max(dot(reflect(-L, vN), vView), 0.0), 90.0);
        float spec2 = pow(max(dot(reflect(-normalize(vec3(0.7, -0.3, 0.5)), vN), vView), 0.0), 40.0) * 0.25;
        vec3 col = uTint * f * 0.55 + vec3(1.0, 0.96, 0.92) * (spec * 1.2 + spec2);
        gl_FragColor = vec4(col * uOpacity, 1.0);
      }`,
  });
}

/** A rounded card drawn on a canvas, used as a texture. */
function card(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d");
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const redraw = (...args) => {
    g.clearRect(0, 0, w, h);
    draw(g, w, h, ...args);
    tex.needsUpdate = true;
  };
  return { canvas: c, tex, redraw };
}
function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

export function createScene(canvas, { mobile = false, reduced = false, lite = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, lite ? 1.25 : mobile ? 1.5 : 1.75));
  renderer.setClearColor(0x030202, 1); // the composer works in linear light: #0a0807 on screen
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0807, 0.04);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; // real reflections on glass and metal
  const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 200);
  camera.position.set(0, 0, 10);

  const world = new THREE.Group();
  scene.add(world);
  const time = { t: 0 };
  const rnd = (a = 1) => (Math.random() * 2 - 1) * a;

  // ---- background: a slow nebula far behind, and dust for depth ----
  const nebula = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShaderMaterial({
    depthWrite: false,
    uniforms: { uTime: { value: 0 }, uDim: { value: 1 } },
    vertexShader: /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      ${NOISE_GLSL}
      uniform float uTime, uDim; varying vec2 vUv;
      void main() {
        vec2 p = (vUv - 0.5) * vec2(3.2, 2.0);
        float n = snoise(vec3(p * 0.9, uTime * 0.02)) * 0.6 + snoise(vec3(p * 2.1 + 4.0, uTime * 0.03)) * 0.3;
        float glow = smoothstep(1.6, 0.0, length(p - vec2(0.5, 0.1)));
        vec3 col = mix(vec3(0.09, 0.015, 0.03), vec3(0.16, 0.05, 0.012), smoothstep(-0.4, 0.6, n));
        gl_FragColor = vec4(col * (0.35 + 0.65 * smoothstep(-0.3, 0.8, n)) * glow * uDim * 0.3, 1.0);
      }`,
  }));
  nebula.scale.set(150, 95, 1);
  nebula.position.z = -45;
  scene.add(nebula);

  const D = lite ? 700 : mobile ? 900 : 2200;
  const dg = new THREE.BufferGeometry();
  const dp = new Float32Array(D * 3);
  for (let i = 0; i < D; i++) dp.set([rnd(40), rnd(24), -Math.random() * 60 + 6], i * 3);
  dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
  const dust = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0xffc9a8, size: 0.05, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(dust);

  // ---- the mark's strands as glowing tubes ----
  const mark = new THREE.Group();
  world.add(mark);
  const curves = STRANDS.map((s) => {
    const v = s.pts.map((p, i) => toV(p, s.z[i]));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(v[0], v[1], v[2], v[3]));
    path.add(new THREE.CubicBezierCurve3(v[3], v[4], v[5], v[6]));
    return { path, v };
  });
  const tubeMats = [];
  curves.forEach(({ path }, i) => {
    const s = STRANDS[i];
    for (const [radius, glow] of [[0.11, 0], [0.3, 1]]) {
      const mat = new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
        uniforms: { uTime: { value: 0 }, uA: { value: new THREE.Color(s.from) }, uB: { value: new THREE.Color(s.to) }, uOpacity: { value: 1 }, uGlow: { value: glow }, uOffset: { value: i * 0.33 } },
        vertexShader: /* glsl */ `
          varying vec2 vUv; varying vec3 vN; varying vec3 vView;
          void main() {
            vUv = uv;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            vN = normalize(normalMatrix * normal); vView = normalize(-mv.xyz);
            gl_Position = projectionMatrix * mv;
          }`,
        fragmentShader: /* glsl */ `
          uniform float uTime, uOpacity, uGlow, uOffset; uniform vec3 uA, uB;
          varying vec2 vUv; varying vec3 vN; varying vec3 vView;
          void main() {
            vec3 col = mix(uA, uB, vUv.x);
            float rim = pow(1.0 - abs(dot(vN, vView)), uGlow > 0.5 ? 1.2 : 2.5);
            float head = fract(vUv.x - uTime * 0.18 + uOffset);
            float pulse = smoothstep(0.0, 0.08, head) * smoothstep(0.32, 0.08, head);
            float a = uGlow > 0.5 ? (1.0 - rim) * 0.05 + pulse * 0.06 : 0.42 + rim * 0.25 + pulse * 0.7;
            gl_FragColor = vec4(col * (1.0 + pulse * 1.6), a * uOpacity);
          }`,
      });
      tubeMats.push(mat);
      mark.add(new THREE.Mesh(new THREE.TubeGeometry(path, 220, radius, 20, false), mat));
    }
  });

  // ---- the lead core: plasma inside a glass shell, three gyroscope rings, a warm light ----
  const core = new THREE.Group();
  world.add(core);
  const coreMat = plasma("#ff6a2a", "#ffb11f", "#e0169a");
  core.add(new THREE.Mesh(new THREE.SphereGeometry(0.62, mobile ? 64 : 96, mobile ? 64 : 96), coreMat));
  const shell = new THREE.Mesh(new THREE.SphereGeometry(0.9, 64, 64), glassMaterial());
  core.add(shell);
  const metal = new THREE.MeshStandardMaterial({ color: 0xd9b49c, metalness: 1, roughness: 0.32, envMapIntensity: 0.55 });
  const gyros = [0, 1, 2].map((i) => {
    const pivot = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.18 + i * 0.17, 0.013, 12, 200), metal);
    const bead = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 16), new THREE.MeshBasicMaterial({ color: new THREE.Color(NODE_COLORS[i * 2]).multiplyScalar(2.2) }));
    bead.position.x = 1.18 + i * 0.17;
    ring.add(bead);
    pivot.add(ring);
    pivot.rotation.set(i * 1.05 + 0.3, i * 0.7, i * 0.4);
    core.add(pivot);
    return { pivot, ring, speed: 0.35 + i * 0.22, dir: i % 2 ? -1 : 1 };
  });
  const light = new THREE.PointLight(0xff8a50, 0, 0, 2);
  core.add(light);
  scene.add(new THREE.HemisphereLight(0xffe2d0, 0x1a0c08, 0.35));

  // ---- the six agents ----
  const logoPos = NODES.map(([s, p]) => curves[s].v[p].clone());
  const nodeGeo = new THREE.SphereGeometry(1, 48, 48);
  const nodes = NODE_COLORS.map((c, k) => {
    const g = new THREE.Group();
    const mat = plasma(c, new THREE.Color(c).lerp(new THREE.Color("#fff1e0"), 0.35).getStyle(), NODE_COLORS[(k + 2) % 6]);
    const inner = new THREE.Mesh(nodeGeo, mat);
    const sh = new THREE.Mesh(nodeGeo, glassMaterial(c));
    g.add(inner, sh);
    world.add(g);
    const orbit = { r: 2.75 + (k % 3) * 0.55, incl: (k % 3 - 1) * 0.55 + 0.12, speed: (0.16 + (k % 2) * 0.06) * (k % 2 ? 1 : 1), phase: (k * Math.PI) / 3 };
    return { g, inner, sh, mat, orbit, pos: new THREE.Vector3(), hi: 0, color: new THREE.Color(c) };
  });

  // ---- links: shared endpoint uniforms, updated every frame ----
  const uLA = Array.from({ length: LINKS }, () => new THREE.Vector3());
  const uLB = Array.from({ length: LINKS }, () => new THREE.Vector3());
  const uLC = Array.from({ length: LINKS }, () => new THREE.Vector3());
  const linkAlpha = new Array(LINKS).fill(0);
  const linkHi = new Array(LINKS).fill(0);
  const uP = curves.flatMap(({ v }) => v);
  const nodeCols = nodes.map((n) => n.color);

  const LP = lite ? 120 : mobile ? 150 : 220; // points per link
  const lg = new THREE.BufferGeometry();
  const lLink = new Float32Array(LINKS * LP), lT = new Float32Array(LINKS * LP);
  for (let l = 0; l < LINKS; l++) for (let i = 0; i < LP; i++) { lLink[l * LP + i] = l; lT[l * LP + i] = i / (LP - 1); }
  lg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(LINKS * LP * 3), 3));
  lg.setAttribute("aLink", new THREE.BufferAttribute(lLink, 1));
  lg.setAttribute("aT", new THREE.BufferAttribute(lT, 1));
  lg.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 50);
  const linkMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uP: { value: uP }, uLA: { value: uLA }, uLB: { value: uLB }, uLC: { value: uLC }, uAlpha: { value: linkAlpha }, uHi: { value: linkHi },
      uTime: { value: 0 }, uAct: { value: 0 }, uPixel: { value: renderer.getPixelRatio() }, uSize: { value: mobile ? 12 : 11 },
      uNode: { value: nodeCols }, uCore: { value: new THREE.Color("#ffb11f") },
    },
    vertexShader: /* glsl */ `
      ${CURVES_GLSL}
      uniform float uAlpha[12], uHi[12], uTime, uAct, uPixel, uSize; uniform vec3 uNode[6], uCore;
      attribute float aLink, aT;
      varying vec3 vCol; varying float vA;
      void main() {
        int l = int(aLink + 0.5);
        vec3 p = linkAt(l, aT);
        float seed = float(l) * 0.618;
        float spd = 0.22 + uAct * 0.38;
        // packets going out (work handed over) and coming back (results), each with a tail
        float xo = fract((uTime * spd + seed - aT) * 2.0);
        float po = 1.0 - smoothstep(0.0, 0.11, xo);
        float xi = fract((uTime * spd * 0.75 + seed * 1.7 - (1.0 - aT)) * 1.5);
        float pi = (1.0 - smoothstep(0.0, 0.09, xi)) * step(float(l), 5.5);
        vec3 a = l < 6 ? uCore : uNode[l - 6];
        vec3 b = l < 6 ? uNode[l] : uNode[l == 11 ? 0 : l - 5];
        vec3 base = mix(a, b, aT);
        float hi = uHi[l];
        vCol = base * (l < 6 ? 0.8 : 0.5) * (1.0 + hi * 1.2) + mix(base, vec3(1.0, 0.92, 0.8), 0.45) * po * (0.9 + uAct * 1.4) + vec3(1.0, 0.45, 0.75) * pi * (0.8 + uAct);
        vA = uAlpha[l];
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = uSize * uPixel * (1.0 + po * 1.8 + pi * 1.4 + hi * 0.8) / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vCol; varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vCol, a * vA);
      }`,
  });
  const links = new THREE.Points(lg, linkMat);
  world.add(links);

  // ---- flowing particles: along the strands, then the links, then out into a ring ----
  const N = lite ? 3500 : reduced ? 2500 : mobile ? 5000 : 11000;
  const g = new THREE.BufferGeometry();
  const aStrand = new Float32Array(N), aLink = new Float32Array(N), aT = new Float32Array(N), aSpeed = new Float32Array(N), aRand = new Float32Array(N);
  const aJitter = new Float32Array(N * 3), aRing = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    aStrand[i] = i % 3;
    aLink[i] = i % LINKS;
    aT[i] = Math.random();
    aSpeed[i] = 0.02 + Math.random() * 0.05;
    aRand[i] = Math.random();
    const r = Math.pow(Math.random(), 0.8) * 0.3, th = Math.random() * Math.PI * 2, ph = Math.acos(rnd());
    aJitter.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph)], i * 3);
    const ra = Math.random() * Math.PI * 2, tr = 4.6 + rnd(0.35) + Math.pow(Math.random(), 4) * rnd(1.4);
    aRing.set([Math.cos(ra) * tr, rnd(0.18) + Math.pow(Math.random(), 6) * rnd(1.2), Math.sin(ra) * tr], i * 3);
  }
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N * 3), 3));
  for (const [name, arr, n] of [["aStrand", aStrand, 1], ["aLink", aLink, 1], ["aT", aT, 1], ["aSpeed", aSpeed, 1], ["aRand", aRand, 1], ["aJitter", aJitter, 3], ["aRing", aRing, 3]]) g.setAttribute(name, new THREE.BufferAttribute(arr, n));
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 50);
  const strandCols = STRANDS.flatMap((s) => [new THREE.Color(s.from), new THREE.Color(s.to)]);
  const pMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uP: { value: uP }, uLA: { value: uLA }, uLB: { value: uLB }, uLC: { value: uLC },
      uTime: { value: 0 }, uFlow: { value: 0 }, uSize: { value: mobile ? 16 : 13 }, uPixel: { value: renderer.getPixelRatio() },
      uCol: { value: strandCols }, uNode: { value: nodeCols }, uSpread: { value: 0 }, uAct: { value: 0 },
    },
    vertexShader: /* glsl */ `
      ${CURVES_GLSL}
      uniform float uTime, uFlow, uSize, uPixel, uSpread, uAct; uniform vec3 uCol[6], uNode[6];
      attribute float aStrand, aLink, aT, aSpeed, aRand; attribute vec3 aJitter, aRing;
      varying vec3 vCol; varying float vAlpha;
      mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
      void main() {
        int s = int(aStrand + 0.5);
        int l = int(aLink + 0.5);
        float t = fract(aT + uTime * aSpeed * (1.0 + uAct * 0.8));
        vec3 logo = strandAt(s, t) + aJitter * (1.0 + uSpread * 4.0);
        vec3 net = linkAt(l, t) + aJitter * (0.45 + uSpread * 3.0);
        vec3 ring = aRing;
        ring.xz = rot(uTime * 0.09) * ring.xz;

        // each particle leaves a little earlier or later, so one shape pours into the next
        float m = clamp(uFlow + (aRand - 0.5) * 0.35, 0.0, 2.0);
        vec3 p = mix(logo, net, smoothstep(0.0, 1.0, clamp(m, 0.0, 1.0)));
        p = mix(p, ring, smoothstep(0.0, 1.0, clamp(m - 1.0, 0.0, 1.0)));

        vec3 logoCol = mix(uCol[s * 2], uCol[s * 2 + 1], t);
        vec3 a = l < 6 ? vec3(1.0, 0.69, 0.12) : uNode[l - 6];
        vec3 b = l < 6 ? uNode[l] : uNode[l == 11 ? 0 : l - 5];
        vCol = mix(logoCol, mix(a, b, t), smoothstep(0.2, 0.8, clamp(m, 0.0, 1.0)));
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        float twinkle = 0.65 + 0.35 * sin(uTime * 3.0 + aRand * 40.0);
        vAlpha = twinkle * (0.9 + uAct * 0.4) * (1.0 + 0.7 * smoothstep(0.3, 1.0, clamp(m, 0.0, 1.0)) * (1.0 - smoothstep(1.2, 2.0, m)));
        gl_PointSize = uSize * uPixel * (0.35 + aRand * 0.65) / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vCol; varying float vAlpha;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vCol * (1.0 + max(vAlpha - 1.0, 0.0)), min(a * a * vAlpha * 0.55, 1.0));
      }`,
  });
  world.add(new THREE.Points(g, pMat));

  // ---- the plan: a goal and five to-do cards orbiting the core, ticked off as it works ----
  const tiles = new THREE.Group();
  world.add(tiles);
  const drawTile = (gx, w, h, text, st) => {
    roundRect(gx, 6, 6, w - 12, h - 12, 26);
    gx.fillStyle = st === "goal" ? "rgba(46, 30, 12, 0.9)" : "rgba(22, 17, 15, 0.88)";
    gx.fill();
    gx.lineWidth = 3;
    gx.strokeStyle = st === "now" ? "rgba(255,106,42,0.9)" : st === "goal" ? "rgba(255,177,31,0.6)" : "rgba(255,236,222,0.16)";
    gx.stroke();
    const cy = h / 2;
    if (st === "goal") {
      gx.fillStyle = "#ffb11f"; gx.font = "600 26px 'JetBrains Mono', monospace"; gx.fillText("◎ GOAL", 40, cy - 18);
      gx.fillStyle = "#f6efe9"; gx.font = "500 32px Inter, system-ui, sans-serif"; gx.fillText(text, 40, cy + 30);
      return;
    }
    gx.beginPath(); gx.arc(62, cy, 18, 0, Math.PI * 2);
    if (st === "done") {
      gx.fillStyle = "#3ddc84"; gx.fill();
      gx.strokeStyle = "#0a1f12"; gx.lineWidth = 5; gx.beginPath(); gx.moveTo(53, cy); gx.lineTo(60, cy + 8); gx.lineTo(72, cy - 8); gx.stroke();
    } else {
      gx.lineWidth = 4; gx.strokeStyle = st === "now" ? "#ff6a2a" : "rgba(255,236,222,0.35)"; gx.stroke();
    }
    gx.font = `${st === "now" ? 600 : 500} 34px Inter, system-ui, sans-serif`;
    gx.fillStyle = st === "done" ? "#85796f" : st === "now" ? "#ff8a50" : "#e9ddd3";
    gx.fillText(text, 104, cy + 12);
    if (st === "done") { const tw = gx.measureText(text).width; gx.fillRect(104, cy, tw, 3); }
  };
  const tileItems = [{ text: "Users can sign up and log in", goal: true }, ...PLAN.map((text) => ({ text }))].map((it, i) => {
    const states = it.goal ? ["goal"] : ["todo", "now", "done"];
    const tex = {};
    for (const st of states) { const c = card(it.goal ? 760 : 680, it.goal ? 170 : 120, drawTile); c.redraw(it.text, st); tex[st] = c.tex; }
    const mat = new THREE.MeshBasicMaterial({ map: tex[states[0]], transparent: true, depthWrite: false, opacity: 0, color: 0xb8b0aa });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(it.goal ? 2.0 : 1.75, it.goal ? 0.45 : 0.31), mat);
    tiles.add(mesh);
    return { mesh, mat, tex, goal: !!it.goal, i, st: states[0] };
  });

  // ---- the file being written: a code panel that types itself; the core's links feed into it ----
  const chars = [];
  for (const [kind, text] of CODE) for (const ch of text) chars.push([kind, ch]);
  const codeCard = card(1024, 720, (gx, w, h, n) => {
    roundRect(gx, 4, 4, w - 8, h - 8, 28);
    gx.fillStyle = "rgba(12, 10, 9, 0.94)"; gx.fill();
    gx.lineWidth = 3; gx.strokeStyle = "rgba(255,236,222,0.18)"; gx.stroke();
    gx.fillStyle = "#ff4a68"; gx.beginPath(); gx.arc(44, 46, 9, 0, Math.PI * 2); gx.fill();
    gx.fillStyle = "#c2b6ac"; gx.font = "500 24px 'JetBrains Mono', monospace"; gx.fillText("Live · src/pages/login.tsx", 66, 54);
    gx.fillStyle = "rgba(255,236,222,0.1)"; gx.fillRect(4, 86, w - 8, 2);
    gx.font = "400 22px 'JetBrains Mono', monospace";
    const lh = 30, x0 = 74;
    let x = x0, y = 128, line = 1;
    gx.fillStyle = "#5a4f48"; gx.fillText(String(line), 26, y);
    for (let i = 0; i < n && i < chars.length; i++) {
      const [kind, ch] = chars[i];
      if (ch === "\n") { x = x0; y += lh; line++; gx.fillStyle = "#5a4f48"; gx.fillText(String(line), 26, y); continue; }
      gx.fillStyle = TOKEN_COLORS[kind];
      gx.fillText(ch, x, y);
      x += 13.2;
    }
    if (n < chars.length) { gx.fillStyle = "#ff6a2a"; gx.fillRect(x + 1, y - 20, 3, 26); }
  });
  const codeMat = new THREE.MeshBasicMaterial({ map: codeCard.tex, transparent: true, opacity: 0, color: 0xc4bcb6 });
  const codePanel = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 2.25), codeMat);
  codePanel.renderOrder = 2;
  scene.add(codePanel);
  const typing = { n: 0, drawn: -1, hold: 0 };

  // ---- a click (or a download) sends a shock ring out from the core ----
  const shockMat = new THREE.MeshBasicMaterial({ color: new THREE.Color("#ff8a50").multiplyScalar(2), transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
  const shock = new THREE.Mesh(new THREE.RingGeometry(0.96, 1, 128), shockMat);
  world.add(shock);
  const pulse = { t: 1, strength: 0, boost: 0 };

  // ---- post: bloom ----
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.62, 0.5, 0.3);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  const state = { zoom: 0, spin: 0, tilt: 0, shiftX: 0, shiftY: 0, mark: 1, net: 0, core: 0, flow: 0, tiles: 0, code: 0, spread: 0, activity: 0.3, dim: 1 };
  const mouse = { x: 0, y: 0, sx: 0, sy: 0, px: -1e4, py: -1e4 };
  addEventListener("pointermove", (e) => {
    mouse.x = e.clientX / innerWidth - 0.5; mouse.y = e.clientY / innerHeight - 0.5;
    mouse.px = e.clientX; mouse.py = e.clientY;
  }, { passive: true });

  const baseZ = () => 10 * Math.max(1, 1.25 / Math.min(camera.aspect, 1.25)); // keep the mark inside narrow screens
  const resize = () => {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w / 2, h / 2);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  addEventListener("resize", resize);
  resize();

  const tmp = new THREE.Vector3(), tmp2 = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0), q = new THREE.Quaternion();
  const ease = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
  const panelLocal = new THREE.Vector3();

  function placeNodes(t) {
    const net = state.net;
    nodes.forEach((n, k) => {
      const o = n.orbit;
      const a = t * o.speed + o.phase;
      const orbit = tmp.set(Math.cos(a) * o.r, Math.sin(a) * o.r * Math.sin(o.incl) + Math.sin(t * 0.7 + k) * 0.18, Math.sin(a) * o.r * Math.cos(o.incl));
      if (net <= 1) n.pos.copy(logoPos[k]).lerp(orbit, ease(net));
      else {
        const ra = (k * Math.PI) / 3 + t * 0.05;
        tmp2.set(Math.cos(ra) * 4.6, Math.sin(t * 0.5 + k) * 0.25, Math.sin(ra) * 4.6);
        n.pos.copy(orbit).lerp(tmp2, ease(net - 1));
      }
      n.g.position.copy(n.pos);
    });
  }

  function placeLinks() {
    const c = ease(state.code);
    for (let k = 0; k < 6; k++) {
      const n = nodes[k].pos;
      // core → agent; while the code panel is up these links feed into it instead
      uLA[k].set(0, 0, 0).lerp(panelLocal, c);
      uLB[k].copy(n);
      const len = uLA[k].distanceTo(n);
      uLC[k].copy(uLA[k]).add(n).multiplyScalar(0.5).addScaledVector(tmp.copy(n).sub(uLA[k]).cross(up).normalize(), len * 0.22 * (k % 2 ? 1 : -1)).addScaledVector(up, len * 0.12);
      // agent → next agent, bowed outward
      const m = nodes[(k + 1) % 6].pos;
      uLA[6 + k].copy(n);
      uLB[6 + k].copy(m);
      uLC[6 + k].copy(n).add(m).multiplyScalar(0.5).multiplyScalar(1.22);
      const outA = Math.min(1, state.net * 1.4) * ease(Math.max(state.core, c));
      linkAlpha[k] = outA;
      linkAlpha[6 + k] = ease((state.net - 0.25) / 0.75) * (state.net > 1 ? 1 : 0.85);
    }
  }

  function hover() {
    // the agent nearest the pointer (on screen) lights up with its links
    let best = -1, bestD = mobile ? 0 : 80;
    if (state.net > 0.3) nodes.forEach((n, k) => {
      n.g.getWorldPosition(tmp).project(camera);
      const x = (tmp.x * 0.5 + 0.5) * innerWidth, y = (-tmp.y * 0.5 + 0.5) * innerHeight;
      const d = Math.hypot(x - mouse.px, y - mouse.py);
      if (d < bestD && tmp.z < 1) { bestD = d; best = k; }
    });
    nodes.forEach((n, k) => { n.hi += ((k === best ? 1 : 0) - n.hi) * 0.12; });
    for (let k = 0; k < 6; k++) {
      linkHi[k] = nodes[k].hi;
      linkHi[6 + k] = Math.max(nodes[k].hi, nodes[(k + 1) % 6].hi);
    }
  }

  function updateTiles(t) {
    const v = ease(state.tiles);
    tiles.visible = v > 0.005;
    if (!tiles.visible) return;
    const prog = (t * 0.55) % 7.5; // the plan keeps being worked through
    world.getWorldQuaternion(q).invert().multiply(camera.quaternion);
    for (const it of tileItems) {
      const appear = ease(v * 1.6 - it.i * 0.12);
      if (it.goal) it.mesh.position.set(0, 1.55 + (1 - appear) * 0.6, 0.4);
      else {
        const a = (it.i - 1) * 1.22 + t * 0.12;
        it.mesh.position.set(Math.cos(a) * 1.95, -0.3 + Math.sin(a) * 0.5 - (it.i - 3) * 0.1, Math.sin(a) * 1.95);
        const st = prog > it.i ? "done" : prog > it.i - 1 ? "now" : "todo";
        if (st !== it.st) { it.st = st; it.mat.map = it.tex[st]; }
      }
      it.mesh.quaternion.copy(q);
      it.mesh.scale.setScalar((0.55 + appear * 0.3) * (mobile ? 0.8 : 1));
      it.mat.opacity = appear;
    }
  }

  function updateCode(dt) {
    const v = ease(state.code);
    codePanel.visible = v > 0.005;
    // in front of the core and a little below, turned toward the camera
    world.localToWorld(tmp.set(0, 0, 0));
    codePanel.position.copy(tmp).add(tmp2.set(mobile ? 0 : -0.4, mobile ? -1.2 : -0.35, 2.3 + (1 - v) * 1.2));
    codePanel.quaternion.copy(camera.quaternion);
    codePanel.scale.setScalar((mobile ? 0.62 : 0.85) + v * 0.15);
    codeMat.opacity = v;
    panelLocal.copy(codePanel.position);
    world.worldToLocal(panelLocal);
    if (!codePanel.visible) return;
    if (typing.n >= chars.length) {
      typing.hold += dt;
      if (typing.hold > 2.6) { typing.n = 0; typing.hold = 0; }
    } else typing.n += dt * (reduced ? 30 : 52) * (0.6 + state.activity * 0.6);
    const n = Math.floor(typing.n);
    if (n !== typing.drawn) { typing.drawn = n; codeCard.redraw(n); }
  }

  const clock = new THREE.Clock();
  let running = true;
  const frame = () => {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.05);
    time.t += dt * (reduced ? 0.3 : 1);
    const t = time.t;
    mouse.sx += (mouse.x - mouse.sx) * Math.min(1, dt * 3);
    mouse.sy += (mouse.y - mouse.sy) * Math.min(1, dt * 3);
    pulse.boost *= Math.pow(0.25, dt);
    const act = state.activity + pulse.boost;

    // framing
    world.rotation.y = state.spin + mouse.sx * 0.5 + Math.sin(t * 0.25) * 0.08;
    world.rotation.x = state.tilt - mouse.sy * 0.3 + Math.cos(t * 0.2) * 0.04;
    world.position.set(state.shiftX, state.shiftY, 0);
    camera.position.set(mouse.sx * 0.6, -mouse.sy * 0.4, baseZ() - state.zoom);
    camera.lookAt(state.shiftX * 0.25, state.shiftY * 0.25, 0);
    camera.updateMatrixWorld();
    world.updateMatrixWorld();
    renderer.toneMappingExposure = 1.05 * state.dim;
    nebula.material.uniforms.uTime.value = t;
    dust.rotation.y = t * 0.01;
    dust.position.z = (state.zoom * 1.5) % 30;

    // the mark
    for (const m of tubeMats) { m.uniforms.uTime.value = t; m.uniforms.uOpacity.value = state.mark; }
    mark.visible = state.mark > 0.01;
    mark.scale.setScalar(0.85 + state.mark * 0.15);

    // the core
    const cv = ease(state.core);
    core.visible = cv > 0.005;
    core.scale.setScalar(0.001 + cv * (1 + Math.sin(t * 2.2) * 0.015 + pulse.boost * 0.08));
    coreMat.uniforms.uTime.value = t;
    coreMat.uniforms.uEnergy.value = 0.6 + act * 0.6;
    for (const gy of gyros) gy.ring.rotation.z += dt * gy.speed * gy.dir * (1 + act);
    light.intensity = 5 * cv * (0.7 + act * 0.4);

    // the agents
    placeNodes(t);
    hover();
    const netV = Math.min(1, state.net);
    nodes.forEach((n, k) => {
      const r = 0.25 - netV * 0.07 + (state.net > 1 ? 0.06 : 0) + n.hi * 0.08;
      n.inner.scale.setScalar(r);
      n.sh.scale.setScalar(r * 1.55);
      n.sh.material.uniforms.uOpacity.value = netV;
      n.mat.uniforms.uTime.value = t + k * 3.1;
      n.mat.uniforms.uEnergy.value = 0.5 + act * 0.5 + n.hi;
    });

    // links and particles
    updateCode(dt);
    placeLinks();
    linkMat.uniforms.uTime.value = t;
    linkMat.uniforms.uAct.value = act;
    links.visible = linkAlpha.some((a) => a > 0.01);
    pMat.uniforms.uTime.value = t;
    pMat.uniforms.uFlow.value = state.flow;
    pMat.uniforms.uSpread.value = state.spread;
    pMat.uniforms.uAct.value = act;
    updateTiles(t);

    // the shock ring
    if (pulse.t < 1) {
      pulse.t = Math.min(1, pulse.t + dt * 0.75);
      const e = 1 - Math.pow(1 - pulse.t, 3);
      shock.visible = true;
      shock.scale.setScalar(0.5 + e * (5 + pulse.strength * 3));
      shockMat.opacity = (1 - pulse.t) * (0.5 + pulse.strength * 0.5);
      world.getWorldQuaternion(q).invert().multiply(camera.quaternion);
      shock.quaternion.copy(q);
    } else shock.visible = false;

    composer.render();
  };
  frame();
  document.addEventListener("visibilitychange", () => {
    const was = running;
    running = !document.hidden;
    if (running && !was) { clock.getDelta(); frame(); }
  });

  /** Send a pulse out from the core and make every link busy for a moment. */
  const burst = (strength = 1) => {
    pulse.t = 0;
    pulse.strength = strength;
    pulse.boost = Math.min(3, pulse.boost + strength * 1.6);
  };
  return { state, burst };
}
