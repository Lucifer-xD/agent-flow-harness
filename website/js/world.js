// The home as a place. A night plain of dark dunes; in its basin the AFH mark stands as a monument:
// three glass cables, alive with light, braided over one another between six pylons that carry the
// mark's six dots. Scrolling is a journey: from far off, down to the sand, along a cable, under the
// braid among standing slabs that show the app at work, and up until the whole thing reads as the logo.
// One renderer, no post-processing (an integrated GPU must hold 60 fps): the glow is additive sprites.
import * as THREE from "three";

// The logo (viewBox 240×140), the same paths as the 2D mark: each strand is two cubic segments.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], from: "#ffb11f", to: "#ff7a3d", lift: 2 },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], from: "#ff7747", to: "#ff4a68", lift: 1 },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], from: "#ff3d8a", to: "#e0169a", lift: 0 },
];
const S = 0.26;            // logo units → world units (the mark is ~38 wide)
const END_Y = 7.5;         // height of the cable ends, on top of the pylons
const R = 1.5;             // cable radius (the logo's stroke, to scale)
const DOT = 2.9;           // sphere radius (the logo's dots, to scale)
const FOG = new THREE.Color("#0c0911");

const canvas = document.getElementById("world");
const mobile = matchMedia("(max-width: 760px)").matches;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
// Without WebGL the page is still a page: the words lay themselves out one under another (html.no3d in world.css).
let renderer;
try { renderer = new THREE.WebGLRenderer({ canvas, antialias: !mobile, powerPreference: "high-performance" }); }
catch (e) { document.documentElement.classList.add("no3d"); document.getElementById("veil")?.classList.add("w-gone"); throw e; }
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, mobile ? 1.25 : 1.5));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.35;

const scene = new THREE.Scene();
scene.background = FOG;
scene.fog = new THREE.FogExp2(FOG, 0.0044);
const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 1200);
const uniforms = { uTime: { value: 0 }, uWake: { value: 0 } };

// ---- noise for the land ----
const hash = (x, z) => { const s = Math.sin(x * 127.1 + z * 311.7) * 43758.5453; return s - Math.floor(s); };
const smooth = (t) => t * t * (3 - 2 * t);
function vnoise(x, z) {
  const xi = Math.floor(x), zi = Math.floor(z), xf = smooth(x - xi), zf = smooth(z - zi);
  const a = hash(xi, zi), b = hash(xi + 1, zi), c = hash(xi, zi + 1), d = hash(xi + 1, zi + 1);
  return a + (b - a) * xf + (c - a) * zf + (a - b - c + d) * xf * zf;
}
function fbm(x, z) { let v = 0, a = 0.5; for (let i = 0; i < 5; i++) { v += a * vnoise(x, z); x = x * 2.03 + 11.7; z = z * 2.03 - 5.3; a *= 0.5; } return v; }
/** Height of the land: a calm basin where the monument stands, dunes rising around it, ridges far off. */
function land(x, z) {
  const d = Math.hypot(x, z * 1.15);
  const rise = smooth(Math.min(1, Math.max(0, (d - 34) / 120)));
  const dunes = (fbm(x * 0.021 + 3.1, z * 0.021 - 1.7) - 0.42) * 34 * rise;
  const ridge = Math.pow(Math.abs(Math.sin(x * 0.012 + fbm(x * 0.006, z * 0.006) * 5)), 2.2) * 26 * smooth(Math.min(1, Math.max(0, (d - 120) / 160)));
  const ripples = (vnoise(x * 0.42, z * 0.16) - 0.5) * 0.42 + (vnoise(x * 1.7, z * 1.1) - 0.5) * 0.12;
  return dunes + ridge + ripples * (0.5 + rise);
}

// ---- sky: a dome that glows low on the horizon, and a few hundred stars ----
{
  const sky = new THREE.Mesh(new THREE.SphereGeometry(900, 32, 20), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color("#05060d") }, mid: { value: new THREE.Color("#161022") }, low: { value: new THREE.Color("#3a1626") }, haze: { value: FOG } },
    vertexShader: "varying vec3 d; void main(){ d = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `varying vec3 d; uniform vec3 top, mid, low, haze;
      void main(){ float h = clamp(d.y, -0.1, 1.0); vec3 c = mix(mid, top, smoothstep(0.08, 0.7, h));
        float warm = smoothstep(0.34, 0.0, h) * (0.55 + 0.45 * smoothstep(-0.2, 0.9, d.x));
        c = mix(c, low, warm * 0.85); c = mix(c, haze, smoothstep(0.07, -0.02, h)); gl_FragColor = vec4(c, 1.0); }`,
  }));
  scene.add(sky);
  const n = mobile ? 520 : 1300, pos = new Float32Array(n * 3), seed = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2, y = 0.06 + Math.pow(Math.random(), 1.5) * 0.94, r = Math.sqrt(1 - y * y);
    pos.set([Math.cos(a) * r * 860, y * 860, Math.sin(a) * r * 860], i * 3);
    seed.set([Math.random() * 6.283, Math.pow(Math.random(), 3)], i * 2); // when it twinkles; how bright it is (most are faint)
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("seed", new THREE.BufferAttribute(seed, 2));
  // each star breathes at its own pace; the bright few are larger and a little warm or cold
  scene.add(new THREE.Points(g, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, fog: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: uniforms.uTime, uPx: { value: 1 } },
    vertexShader: `attribute vec2 seed; uniform float uTime, uPx; varying float vA; varying float vW;
      void main(){ vA = (0.28 + 0.72 * seed.y) * (0.62 + 0.38 * sin(uTime * (0.6 + seed.x * 0.35) + seed.x * 7.0));
        vW = fract(seed.x * 3.7); gl_PointSize = (1.3 + seed.y * 2.6) * uPx; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying float vA; varying float vW;
      void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * vA;
        vec3 c = mix(vec3(0.78, 0.83, 1.0), vec3(1.0, 0.86, 0.78), vW); gl_FragColor = vec4(c * a, a); }`,
  })));
}
const starPx = () => scene.children.find((o) => o.isPoints && o.material.uniforms?.uPx)?.material.uniforms.uPx;
// a falling star every so often, high in the sky: a short line, bright at its head, gone in under a second
const meteor = (() => {
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
  g.setAttribute("color", new THREE.BufferAttribute(new Float32Array([1, 0.92, 0.86, 0, 0, 0]), 3));
  const l = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
  l.frustumCulled = false; l.visible = false; scene.add(l);
  return { l, at: 4 + Math.random() * 5, life: 0, from: new THREE.Vector3(), dir: new THREE.Vector3() };
})();

// ---- the land ----
{
  const seg = mobile ? 150 : 230, size = 760;
  const g = new THREE.PlaneGeometry(size, size, seg, seg); g.rotateX(-Math.PI / 2);
  const p = g.attributes.position, col = new Float32Array(p.count * 3);
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), h = land(x, z);
    p.setY(i, h);
    const grain = 0.82 + vnoise(x * 0.9, z * 0.9) * 0.3 + Math.min(0.25, Math.max(0, h) * 0.012);
    col.set([0.2 * grain, 0.165 * grain, 0.215 * grain], i * 3);
  }
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals();
  scene.add(new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true })));
}

// ---- what the glass reflects: the same night, made once into an environment map ----
// A dark dome with the dawn on one side, the moon's cold light on the other and a few soft panels in the
// mark's colours, so the cables and dots catch real highlights as the camera moves around them.
{
  const env = new THREE.Scene();
  env.add(new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.ShaderMaterial({ side: THREE.BackSide,
    vertexShader: "varying vec3 d; void main(){ d = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: `varying vec3 d; void main(){ float h = d.y; vec3 c = mix(vec3(0.035, 0.03, 0.06), vec3(0.09, 0.07, 0.14), smoothstep(-0.2, 0.8, h));
      c += vec3(0.9, 0.32, 0.2) * pow(max(0.0, 1.0 - abs(h - 0.04) * 4.0), 2.0) * smoothstep(-0.3, 0.8, d.x - d.z * 0.6) * 0.8;
      gl_FragColor = vec4(c, 1.0); }` })));
  const softbox = (hex, power, w, h, x, y, z) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(power), side: THREE.DoubleSide })); m.position.set(x, y, z); m.lookAt(0, 0, 0); env.add(m); };
  softbox("#b9c6ff", 2.6, 30, 12, -22, 30, -26);   // the moon, high behind on the left
  softbox("#ffffff", 1.3, 44, 4, 0, 16, 34);       // a long low strip in front: a line of light along each cable, but nothing that whitens the view from above
  softbox("#ff8a3c", 2.2, 22, 10, 36, 6, -30);     // the dawn
  softbox("#ff3d8a", 1.4, 16, 16, -30, 4, 30);     // the mark's own pink, thrown back from the sand
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(env, 0.035).texture; pm.dispose();
}

// ---- the mark ----
const srgb = (hex) => new THREE.Color(hex);
function bez(p0, p1, p2, p3, t) { const u = 1 - t; return [u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0], u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]]; }
/** A strand's centre line in the world: the logo's curve laid flat (x → x, y → z), lifted into an arch so
 *  the three pass over one another where the logo's strands cross. From straight above it is the logo. */
function centreLine(strand, n = 140) {
  const out = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n, [x, y] = u < 0.5 ? bez(...strand.pts.slice(0, 4), u * 2) : bez(...strand.pts.slice(3, 7), u * 2 - 1);
    const arch = Math.pow(Math.sin(Math.PI * u), 0.85);
    out.push(new THREE.Vector3((x - 120) * S, END_Y + arch * (3.6 + strand.lift * 3.3), (y - 70) * S));
  }
  return out;
}
const glowTex = (() => {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const x = c.getContext("2d"), g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.25, "rgba(255,255,255,0.42)"); g.addColorStop(0.6, "rgba(255,255,255,0.09)"); g.addColorStop(1, "rgba(255,255,255,0)");
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
})();
const halos = [], crowns = [], sparks = [];
function halo(pos, color, size, strength = 1) {
  const m = new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity: strength, blending: THREE.AdditiveBlending, depthWrite: false, fog: false });
  const s = new THREE.Sprite(m); s.position.copy(pos); s.scale.setScalar(size); s.userData.base = strength; scene.add(s); halos.push(s); return s;
}
const stone = new THREE.MeshStandardMaterial({ color: "#17131c", roughness: 0.62, metalness: 0.2, envMapIntensity: 0.5 });
const dots = [];
STRANDS.forEach((strand, k) => {
  const line = centreLine(strand), curve = new THREE.CatmullRomCurve3(line);
  const g = new THREE.TubeGeometry(curve, mobile ? 160 : 260, R, mobile ? 12 : 18, false);
  const a = srgb(strand.from), b = srgb(strand.to), uv = g.attributes.uv, col = new Float32Array(uv.count * 3), c = new THREE.Color();
  for (let i = 0; i < uv.count; i++) { c.copy(a).lerp(b, uv.getX(i)); col.set([c.r, c.g, c.b], i * 3); }
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  // glass with light inside: a glossy clear coat over a body that glows in its own colour, and packets of
  // brighter light that travel from the left dot to the right one, the way the app's mark draws itself
  const m = new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.2, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05, envMapIntensity: 1.15 });
  m.defines.USE_UV = "";
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = uniforms.uTime; sh.uniforms.uWake = uniforms.uWake; sh.uniforms.uOff = { value: k / 3 };
    sh.fragmentShader = "uniform float uTime, uWake, uOff;\n" + sh.fragmentShader.replace("#include <emissivemap_fragment>",
      `float along = vUv.x;
       float head = fract(uTime * 0.085 + uOff);
       float d = along - head; d -= floor(d + 0.5);
       float packet = exp(-d * d * 520.0) + 0.55 * exp(-pow(d + 0.07, 2.0) * 160.0) * step(d, 0.0);
       float lit = smoothstep(0.0, 0.02, uWake * 1.08 - along);
       float rim = pow(1.0 - abs(dot(normalize(vNormal), vec3(0.0, 0.0, 1.0))), 1.6);
       totalEmissiveRadiance = vColor.rgb * lit * (0.9 + rim * 0.6 + packet * 2.8 * uWake);`);
  };
  scene.add(new THREE.Mesh(g, m));
  // the dots: glass spheres on stone pylons at both ends of the strand
  [[line[0], strand.from, 0], [line[line.length - 1], strand.to, 1]].forEach(([p, hex, side]) => {
    const base = land(p.x, p.z), h = p.y - base;
    const pylon = new THREE.Mesh(new THREE.CylinderGeometry(1.15, 1.9, h, 20, 1), stone); pylon.position.set(p.x, base + h / 2, p.z); scene.add(pylon);
    const foot = new THREE.Mesh(new THREE.CylinderGeometry(3.1, 3.6, 0.7, 28), stone); foot.position.set(p.x, base + 0.3, p.z); scene.add(foot);
    const sm = new THREE.MeshPhysicalMaterial({ color: hex, emissive: hex, emissiveIntensity: 0.75, roughness: 0.14, clearcoat: 1, clearcoatRoughness: 0.04, envMapIntensity: 0.9 });
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(DOT, 40, 28), sm); sphere.position.copy(p); scene.add(sphere);
    dots.push({ sphere, mat: sm, side, k, halo: halo(p, hex, 20, 0.5) });
  });
  crowns.push(halo(curve.getPoint(0.5), c.copy(a).lerp(b, 0.5).clone(), 30, 0.28)); // one soft glow at the crown of each cable; more would cost frames up close
  const tint = c.copy(a).lerp(new THREE.Color("#ffffff"), 0.45).clone();
  sparks.push({ curve, k, head: halo(new THREE.Vector3(), tint, 7.5, 0.9), tail: halo(new THREE.Vector3(), tint, 4.5, 0.4) });
});

// light the mark throws on the sand: the logo, blurred, laid on the ground under it
{
  const c = document.createElement("canvas"); c.width = 720; c.height = 420;
  const x = c.getContext("2d"); x.filter = "blur(26px)"; x.lineCap = "round"; x.globalCompositeOperation = "lighter";
  STRANDS.forEach((s) => {
    const g = x.createLinearGradient(46 * 3, 0, 194 * 3, 0); g.addColorStop(0, s.from); g.addColorStop(1, s.to);
    x.strokeStyle = g; x.lineWidth = 46; x.beginPath(); const p = s.pts.map(([a, b]) => [a * 3, b * 3]);
    x.moveTo(...p[0]); x.bezierCurveTo(...p[1], ...p[2], ...p[3]); x.bezierCurveTo(...p[4], ...p[5], ...p[6]); x.stroke();
  });
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(240 * S * 1.02, 140 * S * 1.02), new THREE.MeshBasicMaterial({ map: t, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.42; m.renderOrder = 2; scene.add(m);
}

// ---- lights ----
scene.add(new THREE.HemisphereLight("#5a5880", "#120c10", 1.5));
const moon = new THREE.DirectionalLight("#a9b8ff", 1.6); moon.position.set(-70, 90, -110); scene.add(moon);
// a glow low on the horizon behind the monument: the place has a direction, and the mark stands against it
{ const dawn = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: "#ff5a3a", transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
  dawn.position.set(420, 6, -430); dawn.scale.set(900, 300, 1); scene.add(dawn);
  const dawn2 = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: "#b0206a", transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
  dawn2.position.set(300, 40, -520); dawn2.scale.set(1100, 520, 1); scene.add(dawn2); }
const lamps = [["#ff9a3c", -19, 10, -2], ["#ff4a68", 2, 14, 0], ["#e0169a", 19, 10, 3]].map(([hex, x, y, z]) => {
  const l = new THREE.PointLight(hex, 0, 150, 1.7); l.position.set(x, y, z); scene.add(l); return l;
});

// ---- standing slabs under the braid: the app at work, as glowing panels in stone ----
function panel(draw) {
  const c = document.createElement("canvas"); c.width = 512; c.height = 720; const x = c.getContext("2d");
  x.fillStyle = "#0d0a12"; x.fillRect(0, 0, 512, 720); draw(x);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
const line = (x, y, w, col, h = 12) => (c) => { c.fillStyle = col; c.beginPath(); c.roundRect(x, y, w, h, h / 2); c.fill(); };
const text = (s, x, y, col, font) => (c) => { c.fillStyle = col; c.font = font; c.fillText(s, x, y); };
const PANELS = [
  (c) => [text("Goal", 44, 86, "#8a8392", "500 26px system-ui"), text("Ship the login page", 44, 140, "#f4f1ee", "600 38px system-ui"), line(44, 196, 300, "#ffb11f", 6), text("1  Read the project", 44, 290, "#7d7684", "400 28px system-ui"), text("2  Write login.tsx", 44, 350, "#f4f1ee", "500 28px system-ui"), text("3  Run the tests", 44, 410, "#7d7684", "400 28px system-ui"), text("4  Show the result", 44, 470, "#7d7684", "400 28px system-ui"), line(44, 560, 424, "#2a2430", 10), line(44, 560, 190, "#ff7a3d", 10)].forEach((f) => f(c)),
  (c) => [text("$ npm test", 44, 96, "#f4f1ee", "500 30px ui-monospace, Consolas, monospace"), text("PASS  login.test.tsx", 44, 170, "#63d68b", "400 26px ui-monospace, Consolas, monospace"), text("PASS  session.test.ts", 44, 214, "#63d68b", "400 26px ui-monospace, Consolas, monospace"), text("FAIL  api.test.ts", 44, 258, "#ff5a68", "400 26px ui-monospace, Consolas, monospace"), text("  expected 200, got 401", 44, 302, "#8a8392", "400 24px ui-monospace, Consolas, monospace"), text("$ fixing the token…", 44, 400, "#ffb11f", "500 28px ui-monospace, Consolas, monospace"), line(44, 440, 360, "#2a2430"), line(44, 474, 280, "#2a2430"), line(44, 508, 320, "#2a2430")].forEach((f) => f(c)),
  (c) => [text("login.tsx", 44, 90, "#f4f1ee", "600 32px system-ui"), text("+42  −7", 330, 90, "#63d68b", "500 26px ui-monospace, Consolas, monospace"), ...[150, 190, 230].map((y, i) => line(44, y, 240 + i * 50, "#3a3340")), ...[290, 330, 370, 410].map((y, i) => (cc) => { cc.fillStyle = "rgba(99,214,139,0.16)"; cc.fillRect(30, y - 10, 452, 34); line(44, y, 200 + (i % 3) * 70, "#63d68b")(cc); }), ...[470, 510].map((y, i) => (cc) => { cc.fillStyle = "rgba(255,90,104,0.14)"; cc.fillRect(30, y - 10, 452, 34); line(44, y, 260 - i * 60, "#ff5a68")(cc); }), text("Review", 44, 630, "#ffb11f", "600 30px system-ui")].forEach((f) => f(c)),
  (c) => [text("Allow this step?", 44, 96, "#f4f1ee", "600 36px system-ui"), text("git push origin main", 44, 170, "#b9b2bd", "400 26px ui-monospace, Consolas, monospace"), (cc) => { cc.fillStyle = "#f4f1ee"; cc.beginPath(); cc.roundRect(44, 240, 190, 64, 32); cc.fill(); }, text("Allow", 96, 283, "#14090a", "600 28px system-ui"), (cc) => { cc.strokeStyle = "#4a4352"; cc.lineWidth = 2; cc.beginPath(); cc.roundRect(252, 240, 190, 64, 32); cc.stroke(); }, text("Not now", 290, 283, "#b9b2bd", "500 28px system-ui"), text("Rewind", 44, 430, "#8a8392", "500 26px system-ui"), text("the chat  ·  the files  ·  both", 44, 480, "#f4f1ee", "500 28px system-ui"), line(44, 540, 424, "#2a2430", 8), line(44, 540, 250, "#e0169a", 8)].forEach((f) => f(c)),
];
const slabs = PANELS.map((draw, i) => {
  const a = -0.62 + i * 0.42, r = 15.5, x = Math.sin(a) * r + 1, z = 13.5 + Math.cos(a) * 3.4, base = land(x, z);
  const grp = new THREE.Group(); grp.position.set(x, base, z); grp.rotation.y = -a * 0.8 + Math.PI;
  const body = new THREE.Mesh(new THREE.BoxGeometry(4.5, 6.9, 0.55), stone); body.position.y = 3.3; grp.add(body);
  const face = new THREE.Mesh(new THREE.PlaneGeometry(4.0, 5.62), new THREE.MeshBasicMaterial({ map: panel(draw), transparent: true, opacity: 0, fog: true })); face.position.set(0, 3.5, -0.285); face.rotation.y = Math.PI; grp.add(face);
  scene.add(grp); return face;
});

// ---- dust in the air, catching the light ----
const dust = (() => {
  const n = mobile ? 180 : 420, pos = new Float32Array(n * 3), seed = new Float32Array(n);
  for (let i = 0; i < n; i++) { pos.set([(Math.random() - 0.5) * 110, 1 + Math.random() * 26, (Math.random() - 0.5) * 80], i * 3); seed[i] = Math.random() * 6.28; }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const p = new THREE.Points(g, new THREE.PointsMaterial({ map: glowTex, color: "#ffb38a", size: 0.5, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
  scene.add(p); return { p, pos, seed, n };
})();

// ---- the journey: where the camera is, and what it looks at, along the scroll ----
const KEYS = [
  { t: 0.0, pos: [-128, 30, 132], look: [0, 10, 0] },
  { t: 0.17, pos: [-74, 7.5, 62], look: [-10, 10, -2] },
  { t: 0.36, pos: [-50, 12, 30], look: [-2, 12, -1] },
  { t: 0.56, pos: [-8, 5.2, 40], look: [2, 9, 6] },
  { t: 0.74, pos: [36, 10, 34], look: [2, 11.5, 0] },
  { t: 0.88, pos: [20, 62, 34], look: [0, 8, 0] },
  { t: 1.0, pos: [0, 104, 7.5], look: [0, 0, 7] }, // straight down, aimed a little below the mark so it sits above the words
];
const TALL = { 0: [-150, 38, 170], 0.17: [-96, 9, 84], 0.36: [-58, 14, 30], 0.56: [-14, 6.5, 46], 0.74: [40, 11, 44], 0.88: [20, 104, 46], 1: [0, 168, 12.5] };
const TALL_END_LOOK = [0, 0, 12]; // on a tall screen the finished mark sits above the words, so the camera aims a little below it
const path = { pos: null, look: null };
function buildPath() {
  const tall = camera.aspect < 0.9;
  path.pos = new THREE.CatmullRomCurve3(KEYS.map((k) => new THREE.Vector3(...(tall ? TALL[k.t] : k.pos))), false, "catmullrom", 0.5);
  path.look = new THREE.CatmullRomCurve3(KEYS.map((k) => new THREE.Vector3(...(tall && k.t === 1 ? TALL_END_LOOK : k.look))), false, "catmullrom", 0.5);
}
/** Scroll progress → curve parameter, so each key sits at its own t. */
function param(p) {
  for (let i = 1; i < KEYS.length; i++) if (p <= KEYS[i].t) { const a = KEYS[i - 1].t, b = KEYS[i].t; return (i - 1 + (p - a) / (b - a)) / (KEYS.length - 1); }
  return 1;
}

// ---- the page: scroll, the words, the corners ----
const caps = [...document.querySelectorAll(".w-cap")].map((el) => ({ el, a: +el.dataset.a, b: +el.dataset.b }));
const rail = document.getElementById("rail"), count = document.getElementById("count"), hint = document.getElementById("hint");
// The home has the journey (#world-sec); an inner page has a banner: one view of the place, drifting slowly.
const sec = document.getElementById("world-sec") || document.querySelector(".world.w-banner"), banner = sec.classList.contains("w-banner");
const VIEWS = { features: [-0.9, 46, 9, 11], docs: [0.7, 52, 14, 11], download: [0.02, 62, 22, 9], changelog: [-2.25, 58, 11, 10], models: [2.4, 52, 16, 10], cli: [-0.35, 42, 7.5, 10], api: [1.55, 50, 10, 11], lost: [-0.62, 185, 32, -39, -56] };
const view = VIEWS[sec.dataset.view] || [-0.75, 150, 30, 10]; // angle around the mark, distance, height, the height it looks at (and on a tall screen, if given)
let target = 0, prog = 0, px = 0, py = 0, tx = 0, ty = 0;
// The journey is as long as its section: progress is how far the section has scrolled past the top of the screen.
const readScroll = () => { if (banner) return; const max = sec.offsetHeight - innerHeight; target = max > 0 ? Math.min(1, Math.max(0, -sec.getBoundingClientRect().top / max)) : 0; };
addEventListener("scroll", readScroll, { passive: true });
addEventListener("pointermove", (e) => { tx = e.clientX / innerWidth - 0.5; ty = e.clientY / innerHeight - 0.5; }, { passive: true });
function resize() {
  const w = canvas.clientWidth || innerWidth, h = canvas.clientHeight || innerHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.fov = camera.aspect < 0.9 ? 52 : 40; camera.updateProjectionMatrix(); buildPath(); readScroll();
}
addEventListener("resize", resize); resize();

const up = new THREE.Vector3(), UP_Y = new THREE.Vector3(0, 1, 0), UP_TOP = new THREE.Vector3(0, 0, -1), look = new THREE.Vector3(), tmp = new THREE.Vector3();
const clock = new THREE.Clock();
let wake = reduced ? 1 : 0, arrive = reduced ? 1 : 0, shown = -1, frames = 0, fpsT = 0;
const away = new THREE.Vector3();
const fpsEl = new URLSearchParams(location.search).has("fps") ? document.body.appendChild(Object.assign(document.createElement("div"), { style: "position:fixed;right:12px;top:80px;z-index:20;font:12px ui-monospace,monospace;color:#9f9" })) : null;

function frame() {
  const dt = Math.min(0.05, clock.getDelta()), t = clock.elapsedTime;
  // below the tour nothing is drawn: the rest of the page costs no GPU time
  if (sec.getBoundingClientRect().bottom < -40) { requestAnimationFrame(frame); return; }
  prog += (target - prog) * (reduced ? 1 : 1 - Math.exp(-dt * 4.2));
  px += (tx - px) * 0.06; py += (ty - py) * 0.06;
  wake = Math.min(1, wake + dt * 0.42);                       // the mark lights up from its left dots when the page opens
  arrive = reduced ? 1 : Math.min(1, t * 0.36);              // and the camera glides in to where the page starts (real time, even on a slow GPU)
  uniforms.uTime.value = t; uniforms.uWake.value = wake;

  if (banner) {
    const a = view[0] + Math.sin(t * 0.045) * 0.16, r = view[1] * (camera.aspect < 0.9 ? 1.45 : 1);
    // scrolling down the page lifts the camera a little and pulls it back, so the banner moves with the page
    const s = Math.min(1, Math.max(0, -sec.getBoundingClientRect().top / Math.max(1, sec.offsetHeight)));
    camera.position.set(Math.sin(a) * r * (1 + s * 0.18), view[2] + s * 10, Math.cos(a) * r * (1 + s * 0.18)); look.set(0, (camera.aspect < 0.9 && view[4] != null ? view[4] : view[3]) - s * 3, 0);
  } else {
    const u = param(prog);
    path.pos.getPoint(u, camera.position); path.look.getPoint(u, look);
  }
  if (arrive < 1) { // from higher and further back, easing out
    const e = 1 - Math.pow(1 - arrive, 3); away.subVectors(camera.position, look).multiplyScalar(0.55 * (1 - e));
    camera.position.add(away); camera.position.y += 26 * (1 - e);
  }
  const sway = banner ? 0.6 : 1 - smooth(Math.min(1, Math.max(0, (prog - 0.86) / 0.12)));
  camera.position.x += (Math.sin(t * 0.21) * 0.6 + px * 4) * sway; camera.position.y += (Math.sin(t * 0.17 + 1.3) * 0.35 - py * 2) * sway;
  const floor = land(camera.position.x, camera.position.z) + 2.2; if (camera.position.y < floor) camera.position.y = floor;
  up.copy(UP_Y).lerp(UP_TOP, banner ? 0 : smooth(Math.min(1, Math.max(0, (prog - 0.86) / 0.13)))).normalize();
  camera.up.copy(up); camera.lookAt(look);

  // the dots answer the light that reaches them, like the app's mark: a pulse as a packet leaves or arrives
  for (const d of dots) {
    const head = (t * 0.085 + d.k / 3) % 1, near = d.side ? 1 - head : head, pulse = Math.exp(-near * near * 90);
    d.mat.emissiveIntensity = (0.55 + pulse * 1.5) * wake; d.sphere.scale.setScalar(1 + pulse * 0.07); d.halo.material.opacity = (0.34 + pulse * 0.5) * wake;
  }
  // seen from straight above the glows pile up into a white blur over the logo: soften them there
  const over = banner ? 0 : smooth(Math.min(1, Math.max(0, (prog - 0.84) / 0.14)));
  for (const h of crowns) h.material.opacity = h.userData.base * wake * (1 - over * 0.75);
  for (const d of dots) d.halo.material.opacity *= 1 - over * 0.45;
  for (const s of sparks) {
    const head = (t * 0.085 + s.k / 3) % 1, edge = Math.min(1, head * 14, (1 - head) * 14);
    s.curve.getPointAt(head, s.head.position); s.curve.getPointAt(Math.max(0, head - 0.035), s.tail.position);
    s.head.material.opacity = 0.95 * wake * edge * (1 - over * 0.5); s.tail.material.opacity = 0.42 * wake * edge * (1 - over * 0.5);
  }
  if (!reduced) {
    const m = meteor;
    if (m.life <= 0 && t > m.at) { // somewhere high on the far side of the sky, falling at a slant
      const a = Math.random() * Math.PI * 2, y = 0.42 + Math.random() * 0.4, r = Math.sqrt(1 - y * y);
      m.from.set(Math.cos(a) * r * 800, y * 800, Math.sin(a) * r * 800);
      m.dir.set(-Math.sin(a), -0.45 - Math.random() * 0.3, Math.cos(a)).normalize().multiplyScalar((Math.random() < 0.5 ? 1 : -1) * 260);
      m.dir.y = -Math.abs(m.dir.y); m.life = 1; m.at = t + 7 + Math.random() * 9;
    }
    if (m.life > 0) {
      m.life = Math.max(0, m.life - dt * 1.25); const k = 1 - m.life, p = m.l.geometry.attributes.position, c = m.l.geometry.attributes.color;
      const hx = m.from.x + m.dir.x * k, hy = m.from.y + m.dir.y * k, hz = m.from.z + m.dir.z * k, len = 0.16 + 0.2 * Math.sin(Math.PI * k);
      p.setXYZ(0, hx, hy, hz); p.setXYZ(1, hx - m.dir.x * len, hy - m.dir.y * len, hz - m.dir.z * len); p.needsUpdate = true;
      const b = Math.sin(Math.PI * k) * 0.9; c.setXYZ(0, b, b * 0.92, b * 0.85); c.needsUpdate = true;
    }
    m.l.visible = m.life > 0;
  }
  lamps.forEach((l, i) => { l.intensity = (i === 1 ? 900 : 650) * wake * (0.9 + 0.1 * Math.sin(t * 0.9 + i)); });
  const near = banner ? 1 : smooth(Math.min(1, Math.max(0, (prog - 0.4) / 0.12))) * (1 - smooth(Math.min(1, Math.max(0, (prog - 0.82) / 0.08))));
  slabs.forEach((f, i) => { f.material.opacity = Math.min(1, Math.max(0, near * 1.5 - i * 0.12)); });
  for (let i = 0; i < dust.n; i++) {
    dust.pos[i * 3] += Math.sin(t * 0.13 + dust.seed[i]) * 0.006; dust.pos[i * 3 + 1] += Math.cos(t * 0.11 + dust.seed[i] * 2) * 0.004;
  }
  dust.p.geometry.attributes.position.needsUpdate = true;

  renderer.render(scene, camera);

  // the words and the corners
  let chapter = 0;
  caps.forEach((c, i) => {
    const fadeIn = c.el.hasAttribute("data-first") ? 1 : smooth(Math.min(1, Math.max(0, (prog - c.a) / 0.035)));
    const o = fadeIn * (1 - smooth(Math.min(1, Math.max(0, (prog - c.b) / 0.035))));
    c.el.style.opacity = o.toFixed(3); c.el.style.transform = `translateY(${((1 - o) * (prog < c.a + 0.02 ? 18 : -18)).toFixed(1)}px)`;
    c.el.classList.toggle("w-on", o > 0.5);
    if (prog >= c.a - 0.02) chapter = i;
  });
  if (!banner) {
    if (chapter !== shown) { shown = chapter; if (count) count.textContent = String(chapter + 1).padStart(2, "0"); }
    if (rail) rail.style.transform = `scaleX(${prog.toFixed(4)})`; // the home no longer shows a progress line
    hint.classList.toggle("w-off", prog > 0.03);
  }

  if (fpsEl) { frames++; fpsT += dt; if (fpsT > 0.5) { fpsEl.textContent = `${Math.round(frames / fpsT)} fps`; frames = 0; fpsT = 0; } }
  requestAnimationFrame(frame);
}
tmp.set(0, 0, 0);
renderer.compile(scene, camera);
/** Sharpest pixel ratio this GPU draws in under ~10 ms a frame, measured at the heaviest view (close to the cables). */
function calibrate() {
  const gl = renderer.getContext(), top = Math.min(devicePixelRatio || 1, mobile ? 1.25 : 1.5);
  if (banner) { camera.position.set(Math.sin(view[0]) * view[1], view[2], Math.cos(view[0]) * view[1]); look.set(0, view[3], 0); }
  else { path.pos.getPoint(param(0.47), camera.position); path.look.getPoint(param(0.47), look); }
  camera.up.copy(UP_Y); camera.lookAt(look);
  for (const r of [top, 1.25, 1, 0.85, 0.7].filter((x, i, a) => x <= top && a.indexOf(x) === i)) {
    renderer.setPixelRatio(r); renderer.setSize(canvas.clientWidth || innerWidth, canvas.clientHeight || innerHeight, false); if (starPx()) starPx().value = r;
    renderer.render(scene, camera); gl.finish();
    const t0 = performance.now(); for (let i = 0; i < 5; i++) { renderer.render(scene, camera); gl.finish(); }
    if ((performance.now() - t0) / 5 <= 10) break;
  }
}
uniforms.uWake.value = 1; calibrate(); uniforms.uWake.value = 0; if (starPx()) starPx().value = renderer.getPixelRatio();
requestAnimationFrame(() => { document.getElementById("veil")?.classList.add("w-gone"); frame(); });
window.afhWorld = {
  seek: (p) => { scrollTo(0, scrollY + sec.getBoundingClientRect().top + p * (sec.offsetHeight - innerHeight)); target = prog = p; },
  /** Milliseconds a frame really costs on this GPU (render + wait for the GPU), averaged over n frames. */
  bench: (n = 30) => { const gl = renderer.getContext(), t0 = performance.now(); for (let i = 0; i < n; i++) { renderer.render(scene, camera); gl.finish(); } return +((performance.now() - t0) / n).toFixed(2); },
  ratio: () => renderer.getPixelRatio(),
};
// the version on the last screen comes from the installer the site is serving, like every other page
fetch("/downloads/latest.yml", { cache: "no-cache" }).then((r) => (r.ok ? r.text() : "")).then((t) => {
  const v = /^version:\s*([\w.-]+)/m.exec(t)?.[1];
  if (v) document.querySelectorAll("[data-version]").forEach((el) => { el.textContent = v; });
}).catch(() => {});
