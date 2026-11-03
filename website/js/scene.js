// The 3D on every page is the harness line: the logo's three strands as one glossy braided cable
// that runs through the page, behind the content. Where the page gives it a stage box it opens into
// the mark, drawn to the logo's own proportions and colours (three strands, six dots). Each strand
// leaves through its dot, the three sweep round nested like lanes and gather into the braid, which
// thins as they meet; the braid threads down the page along the gutters and behind the cards, with
// light running inside it and dots riding it as you scroll, and fans back out into the last mark's
// dots the same way. On load it draws itself in from the first mark.
//
// The page hands it a route in page pixels (y grows downwards, like the DOM):
//   scene.setRoute({ marks: [box, box?], points: [{x, y}, …], radius, pageHeight })
//     marks   stage boxes (page coordinates) the line opens into: the first at the start, the
//             second (if any) at the end. markBounds(box) says where a mark will sit in its box.
//     points  the braid, from where the strands gather to where they part
//     tight   braid the strands closer, for a line that has to fit a narrow gutter
//   scene.state.scroll = the window's scroll position, set by the page every frame
// It follows the page's theme (<html data-theme>) by itself.
//
// Built to stay smooth on integrated graphics: three static tubes, fifteen spheres, one shadow map
// that follows the viewport, no post-processing.
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

// The logo (viewBox 240×140): each strand is two cubic segments meeting in the middle, with a depth
// per control point so the strands weave past each other. Stroke 14, dots r 15.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.55, 0.2, -0.6, 0], from: "#ffb11f", to: "#ff7a3d" },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68" },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.55, -0.2, 0.6, 0], from: "#ff3d8a", to: "#e0169a" },
];
const LOGO_W = 148, LOGO_H = 84, LOGO_X = 46, LOGO_Y = 28; // the strands' extent in the viewBox
const TAU = Math.PI * 2;
const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const STROKE = 7, DOT = 15; // the logo's stroke radius and dot radius, in viewBox units
const RADIAL = 14; // sides of the tubes
const fit = (box) => {
  const sc = Math.min(box.width / LOGO_W, box.height / LOGO_H) * 0.86;
  return { sc, ox: box.left + box.width / 2 - (LOGO_X + LOGO_W / 2) * sc, oy: box.top + box.height / 2 - (LOGO_Y + LOGO_H / 2) * sc };
};
/** Where a mark sits in its stage box: the strands' ends (left, right, top, bottom), its middle line, its dot radius and its scale. */
export function markBounds(box) {
  const { sc, ox, oy } = fit(box);
  return { left: ox + LOGO_X * sc, right: ox + (LOGO_X + LOGO_W) * sc, top: oy + LOGO_Y * sc, bottom: oy + (LOGO_Y + LOGO_H) * sc, midY: oy + (LOGO_Y + LOGO_H / 2) * sc, dot: DOT * sc, sc };
}
const ceramic = (extra = {}) => new THREE.MeshPhysicalMaterial({ roughness: 0.3, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.14, envMapIntensity: 1.05, sheen: 0.2, sheenColor: 0xffe6d6, ...extra });

export function createScene(canvas, { mobile = false, reduced = false, lite = false } = {}) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" }); }
  catch { canvas.remove(); return { state: {}, setRoute() {}, three: {} }; } // no WebGL here: the page simply has no line
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(0x000000, 0);
  const shadows = !lite;
  renderer.shadowMap.enabled = shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  // page pixels are world units: x from the middle of the viewport, y up (page y is negated)
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -3000, 3000);
  camera.position.z = 600;
  let W = innerWidth, H = innerHeight;

  // light: a soft key from the upper left that follows the viewport, so the shadow map covers what's on screen
  const key = new THREE.DirectionalLight(0xfff4ea, 1.7);
  const keyTarget = new THREE.Object3D();
  key.target = keyTarget;
  if (shadows) {
    key.castShadow = true;
    key.shadow.mapSize.set(mobile ? 1024 : 2048, mobile ? 1024 : 2048);
    key.shadow.radius = 5;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 1.5;
    Object.assign(key.shadow.camera, { near: 1, far: 4000 });
  }
  const rim = new THREE.DirectionalLight(0xff6a9a, 0.35);
  rim.position.set(400, -200, 300);
  const fill = new THREE.HemisphereLight(0xffffff, 0xf0e2d6, 0.85);
  scene.add(key, keyTarget, rim, fill);
  // the page: an invisible plane behind the line that only shows the shadow it throws
  const page = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ color: 0x2a1408, opacity: 0.16, transparent: true, depthWrite: false }));
  page.receiveShadow = shadows;
  page.visible = shadows;
  scene.add(page);

  // ---- the line: three tubes, rebuilt whenever the page gives a new route ----
  const flow = { uFlow: { value: 0 }, uGlow: { value: 0.1 }, uDraw: { value: 0 } };
  const mats = STRANDS.map(() => {
    const m = ceramic({ vertexColors: true, emissive: 0xffffff });
    m.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, flow);
      sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nvarying vec2 vUvF;").replace("#include <begin_vertex>", "#include <begin_vertex>\nvUvF = uv;");
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform float uFlow, uGlow, uDraw; varying vec2 vUvF;")
        .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
          // light packets travelling along the line; nothing past where it has drawn itself in
          if (vUvF.x > uDraw) discard;
          float x = vUvF.x * 60.0 - uFlow;
          float packet = pow(max(0.0, 1.0 - abs(fract(x) - 0.5) / 0.12), 2.0);
          totalEmissiveRadiance = vColor.rgb * (uGlow * 0.5 + packet * uGlow * 2.2);`);
    };
    m.customProgramCacheKey = () => "afh-line";
    return m;
  });
  const tubes = STRANDS.map((_, k) => { const m = new THREE.Mesh(new THREE.BufferGeometry(), mats[k]); m.castShadow = shadows; m.frustumCulled = false; scene.add(m); return m; });
  const curves = [null, null, null];
  // the dots: each mark's six stay put, the logo's own (left: 0-2 and 9-11; right: 3-5 and 12-14),
  // and three more (6-8) ride the line between them as you scroll
  const dotGeo = new THREE.SphereGeometry(1, 36, 24);
  const DOT_COLOR = ["#ffb11f", "#ff7747", "#ff3d8a", "#ff7a3d", "#ff4a68", "#e0169a"];
  const dots = Array.from({ length: 15 }, (_, i) => {
    const d = new THREE.Mesh(dotGeo, ceramic({ color: DOT_COLOR[i >= 9 ? i - 9 : i >= 6 ? i - 3 : i] }));
    d.castShadow = shadows;
    d.visible = false;
    scene.add(d);
    return d;
  });
  let route = null;

  /** A tube whose radius changes along it, painted by `colorAt`: both take u, from 0 to 1 along the curve. */
  const tube = (curve, segs, radiusAt, colorAt) => {
    const geo = new THREE.TubeGeometry(curve, segs, 1, RADIAL, false);
    const pos = geo.attributes.position, nor = geo.attributes.normal, n = RADIAL + 1, col = new Float32Array(pos.count * 3), c = new THREE.Color();
    for (let i = 0; i <= segs; i++) {
      const r = radiusAt(i / segs) - 1;
      colorAt(i / segs, c);
      for (let j = i * n; j < i * n + n; j++) {
        pos.setXYZ(j, pos.getX(j) + nor.getX(j) * r, pos.getY(j) + nor.getY(j) * r, pos.getZ(j) + nor.getZ(j) * r);
        col.set([c.r, c.g, c.b], j * 3);
      }
    }
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return geo;
  };
  /** The stretch between a mark's dot and the braid: out along `dir`, round into `toDir`. The strand
      on the outside of the bend reaches further (`lane`, -1 to 1), clearing the dots it passes, so
      the three nest and never cross; no strand reaches past the braid and doubles back. */
  const sweep = (from, dir, to, toDir, lane, dot) => {
    const d = from.distanceTo(to), ahead = to.clone().sub(from).dot(dir);
    const reach = Math.min(d * (0.42 + 0.3 * lane), Math.max(ahead * 0.85, dot * (1.3 + 1.4 * (lane + 1))));
    const c = new THREE.CubicBezierCurve3(from, from.clone().addScaledVector(dir, reach), to.clone().addScaledVector(toDir, -d * (0.34 + 0.12 * lane)), to);
    return c.getSpacedPoints(Math.max(8, Math.round(d / 12))).slice(1, -1);
  };
  /** Strand k of the mark fitted into a page box: 48 points along it, in world units. */
  const markPoints = (k, box) => {
    const { sc, ox, oy } = fit(box);
    const s = STRANDS[k];
    const P = s.pts.map(([x, y], i) => new THREE.Vector3(ox + x * sc - W / 2, -(oy + y * sc), s.z[i] * STROKE * sc * 0.7));
    const path = new THREE.CurvePath();
    path.add(new THREE.CubicBezierCurve3(P[0], P[1], P[2], P[3]));
    path.add(new THREE.CubicBezierCurve3(P[3], P[4], P[5], P[6]));
    return path.getSpacedPoints(48);
  };
  const build = () => {
    if (!route) return;
    const { marks, points, radius } = route.spec;
    const a = marks[0], b = marks[1];
    const braid = points.length >= 2 ? new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(p.x - W / 2, -p.y, 0)), false, "centripetal") : null;
    const N = braid ? Math.max(120, Math.min(900, Math.round(braid.getLength() / 14))) : 0;
    const samples = braid ? braid.getSpacedPoints(N) : [];
    const tangents = braid ? samples.map((_, i) => braid.getTangentAt(i / N)) : [];
    const lengths = braid ? braid.getLengths(N) : [];
    const spacing = radius * (route.spec.tight ? 1.7 : 2.3), twist = TAU / 520; // the braid: the strands circle the line every 520px
    route.u = { hero: [0, 0, 0], cta: [1, 1, 1] };
    const X = new THREE.Vector3(1, 0, 0), rA = a ? STROKE * fit(a).sc : radius, rB = b ? STROKE * fit(b).sc : radius;
    const first = tangents[0], last = tangents[tangents.length - 1];
    STRANDS.forEach((s, k) => {
      const head = a ? markPoints(k, a) : [], tail = b ? markPoints(k, b) : [];
      const line = samples.map((p, i) => {
        const ph = lengths[i] * twist + (k * TAU) / 3, t = tangents[i], nx = -t.y, ny = t.x;
        return new THREE.Vector3(p.x + nx * spacing * Math.sin(ph), p.y + ny * spacing * Math.sin(ph), spacing * 0.8 * Math.cos(ph));
      });
      // the logo stacks its strands top (k = 0) to bottom: which of them is outermost depends on the way the braid bends
      const out = a && line.length ? sweep(head[head.length - 1], X, line[0], first, (k - 1) * first.y, DOT * fit(a).sc) : [];
      const into = b && line.length ? sweep(tail[0], X.clone().negate(), line[line.length - 1], last.clone().negate(), (1 - k) * last.y, DOT * fit(b).sc).reverse() : [];
      const pts = [...head, ...out, ...line, ...into, ...tail];
      if (pts.length < 4) return;
      const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
      curve.arcLengthDivisions = pts.length * 2;
      curves[k] = curve;
      // the places that matter along the strand, as fractions of its length
      const run = [0];
      for (let i = 1; i < pts.length; i++) run.push(run[i - 1] + pts[i].distanceTo(pts[i - 1]));
      const at = (i) => run[i] / run[run.length - 1];
      const u1 = a ? at(head.length - 1) : 0, u2 = a ? at(head.length + out.length) : 0;
      const u4 = b ? at(pts.length - tail.length) : 1, u3 = b ? at(pts.length - tail.length - into.length - 1) : 1;
      route.u.hero[k] = u1;
      route.u.cta[k] = u4;
      // each mark runs the logo's gradient across it; the braid carries the colour from one to the other
      const from = new THREE.Color(s.from), to = new THREE.Color(s.to);
      const colorAt = (u, c) => (u < u1 ? c.copy(from).lerp(to, u / u1) : u > u4 ? c.copy(from).lerp(to, (u - u4) / (1 - u4)) : c.copy(to).lerp(from, (u - u1) / Math.max(1e-6, u4 - u1)));
      const radiusAt = (u) => (u < u2 ? rA + (radius - rA) * smooth((u - u1) / Math.max(1e-6, u2 - u1)) : u > u3 ? radius + (rB - radius) * smooth((u - u3) / Math.max(1e-6, u4 - u3)) : radius);
      const geo = tube(curve, Math.min(3000, Math.max(200, Math.round(curve.getLength() / 8))), radiusAt, colorAt);
      tubes[k].geometry.dispose();
      tubes[k].geometry = geo;
      route.ends[k] = { aL: head[0], aR: head[head.length - 1], bL: tail[0], bR: tail[tail.length - 1] };
    });
    route.radius = radius;
    route.dotA = a ? DOT * fit(a).sc : 0;
    route.dotB = b ? DOT * fit(b).sc : 0;
    route.rider = radius * 1.8;
    route.startY = a ? a.top + a.height : 0;
    route.endY = b ? b.top - H * 0.45 : (route.spec.pageHeight || 4000);
    const ph = route.spec.pageHeight || H;
    page.scale.set(W * 3, ph * 1.2 + H * 3, 1);
    page.position.set(0, -ph / 2, -70);
  };

  // the canvas is as tall as the largest viewport, so a phone's address bar sliding away changes nothing
  const resize = () => {
    const widthChanged = innerWidth !== W;
    W = innerWidth; H = canvas.clientHeight || innerHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.5 : 2));
    renderer.setSize(W, H, false);
    camera.left = -W / 2; camera.right = W / 2; camera.top = H / 2; camera.bottom = -H / 2;
    camera.updateProjectionMatrix();
    if (shadows) { Object.assign(key.shadow.camera, { left: -W * 0.8, right: W * 0.8, top: H * 0.8, bottom: -H * 0.8 }); key.shadow.camera.updateProjectionMatrix(); }
    if (widthChanged) build();
  };
  addEventListener("resize", resize);
  W = 0;
  resize();

  // light and dark: on a dark page the line is lit less and glows more, and its shadow goes black
  let glow = 1;
  const theme = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    page.material.color.set(dark ? 0x000000 : 0x2a1408);
    page.material.opacity = dark ? 0.55 : 0.16;
    key.intensity = dark ? 1.5 : 1.7;
    rim.intensity = dark ? 1.1 : 0.35;
    fill.intensity = dark ? 0.5 : 0.85;
    fill.groundColor.set(dark ? 0x3a2418 : 0xf0e2d6);
    [...mats, ...dots.map((d) => d.material)].forEach((m) => { m.envMapIntensity = dark ? 0.72 : 1.05; });
    glow = dark ? 2.6 : 1;
  };
  theme();
  new MutationObserver(theme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const state = { scroll: 0, activity: 0.3, dim: 1 };
  const mouse = { x: 0, y: 0, sx: 0, sy: 0 };
  addEventListener("pointermove", (e) => { mouse.x = e.clientX / W - 0.5; mouse.y = e.clientY / H - 0.5; }, { passive: true });
  const clock = { last: performance.now(), t: 0, draw: 0, lastScroll: 0, vel: 0 };
  let lastFade = -1;
  const tmp = new THREE.Vector3();
  const frame = (now) => {
    requestAnimationFrame(frame);
    const ms = now - clock.last;
    clock.last = now;
    if (document.hidden || !route) return;
    const dt = Math.min(ms / 1000, 0.05);
    clock.t += dt;
    clock.draw = Math.min(1, clock.draw + (reduced ? 1 : Math.min(ms, 100) / 2600));
    const sy = state.scroll;
    clock.vel += ((sy - clock.lastScroll) / Math.max(1, ms) - clock.vel) * Math.min(1, dt * 6);
    clock.lastScroll = sy;
    mouse.sx += (mouse.x - mouse.sx) * Math.min(1, dt * 3);
    mouse.sy += (mouse.y - mouse.sy) * Math.min(1, dt * 3);
    // the camera follows the page; the light follows the camera
    camera.position.set(mouse.sx * 6, -(sy + H / 2) - mouse.sy * 4, 600);
    key.position.set(camera.position.x - W * 0.35, camera.position.y + H * 0.55, 900);
    keyTarget.position.set(camera.position.x, camera.position.y, 0);
    flow.uFlow.value += dt * (0.5 + state.activity * 0.4) + clock.vel * 0.02;
    flow.uGlow.value = (0.08 + state.activity * 0.05 + Math.min(0.25, Math.abs(clock.vel) * 0.08)) * glow;
    flow.uDraw.value = smooth(clock.draw);
    // the dots
    const p = smooth((sy - route.startY) / Math.max(1, route.endY - route.startY));
    const grow = smooth(clock.draw * 1.4), [hasA, hasB] = route.spec.marks.map(Boolean);
    dots.forEach((d, i) => {
      const k = i % 3, c = curves[k], e = route.ends[k], rider = i >= 6 && i < 9;
      if (!c || !e || !(i < 9 ? hasA : hasB)) { d.visible = false; return; }
      const u = i < 3 ? 0 : i < 6 ? route.u.hero[k] : rider ? route.u.hero[k] + ((hasB ? route.u.cta[k] : 1) - route.u.hero[k]) * p : i < 12 ? route.u.cta[k] : 1;
      if (u > flow.uDraw.value + 0.001) { d.visible = false; return; }
      if (rider) c.getPointAt(Math.min(1, Math.max(0, u)), tmp);
      else tmp.copy(i < 3 ? e.aL : i < 6 ? e.aR : i < 12 ? e.bL : e.bR);
      d.visible = true;
      d.position.copy(tmp);
      d.scale.setScalar(grow * (rider ? route.rider * (1 + Math.sin(clock.t * 2 + i) * 0.04) : i < 9 ? route.dotA : route.dotB));
    });
    const fade = Math.round(Math.min(1, Math.max(0, state.dim)) * 200) / 200;
    if (fade !== lastFade) canvas.style.opacity = lastFade = fade;
    renderer.render(scene, camera);
  };
  requestAnimationFrame(frame);

  /** Give the line its route (page pixels). Call again after the layout changes. */
  let routeKey = "";
  const setRoute = (spec) => {
    const key = `${W} ${JSON.stringify(spec)}`;
    if (key === routeKey) return; // the page asks often; only a real change rebuilds the tubes
    routeKey = key;
    route = { spec, u: { hero: [0, 0, 0], cta: [1, 1, 1] }, ends: [] };
    build();
  };
  return { state, setRoute, three: { renderer, scene, camera, tubes, dots, curves, quality: () => [`${renderer.getPixelRatio().toFixed(2)}x`, shadows ? "shadows" : "no shadows", tubes.map((t) => t.geometry.attributes.position?.count || 0).join("+") + " verts"] } };
}
