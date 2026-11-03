// The 3D on every page is the harness line: the logo's three strands as one glossy braided cable
// that runs through the page, behind the content. Where the page gives it a stage box it opens into
// the mark (the three strands and their six dots); between stages it braids into one line that
// threads down the page along the gutters and behind the cards, with light running inside it and
// the dots riding it as you scroll. On load it draws itself in from the first mark.
//
// The page hands it a route in page pixels (y grows downwards, like the DOM):
//   scene.setRoute({ marks: [box, box?], points: [{x, y}, …], radius, pageHeight })
//     marks   stage boxes (page coordinates) the line opens into: the first at the start, the
//             second (if any) at the end; the braid runs through `points` between them
//   scene.state.scroll = the window's scroll position, set by the page every frame
//
// Built to stay smooth on integrated graphics: three static tubes, nine spheres, one shadow map
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
const ceramic = (extra = {}) => new THREE.MeshPhysicalMaterial({ roughness: 0.3, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.14, envMapIntensity: 1.05, sheen: 0.2, sheenColor: 0xffe6d6, ...extra });

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
  scene.add(key, keyTarget, rim, new THREE.HemisphereLight(0xffffff, 0xf0e2d6, 0.85));
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
  // the dots: three stay at the first mark's left ends, three ride the line, three wait at the last mark's right ends
  const dotGeo = new THREE.SphereGeometry(1, 36, 24);
  const dots = Array.from({ length: 9 }, (_, i) => {
    const s = STRANDS[i % 3];
    const d = new THREE.Mesh(dotGeo, ceramic({ color: new THREE.Color(i < 6 ? s.from : s.to).lerp(new THREE.Color(i < 6 ? s.to : s.from), 0.25) }));
    d.castShadow = shadows;
    d.visible = false;
    scene.add(d);
    return d;
  });
  let route = null;

  /** Paint a tube geometry with the strand's gradient along its length. */
  const paint = (geo, from, to) => {
    const uv = geo.attributes.uv, n = uv.count, col = new Float32Array(n * 3), a = new THREE.Color(from), b = new THREE.Color(to), c = new THREE.Color();
    for (let i = 0; i < n; i++) { c.copy(a).lerp(b, uv.array[i * 2]); col.set([c.r, c.g, c.b], i * 3); }
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  };
  /** Strand k of the mark fitted into a page box: 48 points along it, in world units. */
  const markPoints = (k, box) => {
    const sc = Math.min(box.width / LOGO_W, box.height / LOGO_H) * 0.86;
    const ox = box.left + box.width / 2 - (LOGO_X + LOGO_W / 2) * sc, oy = box.top + box.height / 2 - (LOGO_Y + LOGO_H / 2) * sc;
    const s = STRANDS[k];
    const P = s.pts.map(([x, y], i) => new THREE.Vector3(ox + x * sc - W / 2, -(oy + y * sc), s.z[i] * 7 * sc * 0.7));
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
    const spacing = radius * 2.3, twist = TAU / 520; // the braid: the strands circle the line every 520px
    route.u = { hero: [0, 0, 0], cta: [1, 1, 1] };
    STRANDS.forEach((s, k) => {
      const pts = [];
      if (a) pts.push(...markPoints(k, a));
      samples.forEach((p, i) => {
        const ph = lengths[i] * twist + (k * TAU) / 3, t = tangents[i], nx = -t.y, ny = t.x;
        pts.push(new THREE.Vector3(p.x + nx * spacing * Math.sin(ph), p.y + ny * spacing * Math.sin(ph), spacing * 0.8 * Math.cos(ph)));
      });
      if (b) pts.push(...markPoints(k, b));
      if (pts.length < 4) return;
      const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
      curves[k] = curve;
      const segs = Math.min(2600, Math.max(200, Math.round(curve.getLength() / 9)));
      const geo = new THREE.TubeGeometry(curve, segs, radius, 14, false);
      paint(geo, s.from, s.to);
      tubes[k].geometry.dispose();
      tubes[k].geometry = geo;
      // where the marks end along the strand (by arc length), for the dots
      const L = curve.getLengths(600), total = L[L.length - 1];
      const at = (idx) => L[Math.round((idx / (pts.length - 1)) * 600)] / total;
      route.u.hero[k] = a ? at(47) : 0;
      route.u.cta[k] = b ? at(pts.length - 49) : 1;
    });
    route.radius = radius;
    route.dotR = radius * 15 / 7;
    route.startY = a ? a.top + a.height : 0;
    route.endY = b ? b.top - H * 0.45 : (route.spec.pageHeight || 4000);
    const ph = route.spec.pageHeight || H;
    page.scale.set(W * 3, ph * 1.2 + H * 3, 1);
    page.position.set(0, -ph / 2, -70);
  };

  const resize = () => {
    W = innerWidth; H = innerHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.5 : 2));
    renderer.setSize(W, H, false);
    camera.left = -W / 2; camera.right = W / 2; camera.top = H / 2; camera.bottom = -H / 2;
    camera.updateProjectionMatrix();
    if (shadows) { Object.assign(key.shadow.camera, { left: -W * 0.8, right: W * 0.8, top: H * 0.8, bottom: -H * 0.8 }); key.shadow.camera.updateProjectionMatrix(); }
    build();
  };
  addEventListener("resize", resize);
  resize();

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
    flow.uGlow.value = 0.08 + state.activity * 0.05 + Math.min(0.25, Math.abs(clock.vel) * 0.08);
    flow.uDraw.value = smooth(clock.draw);
    // the dots
    const p = smooth((sy - route.startY) / Math.max(1, route.endY - route.startY));
    const grow = smooth(clock.draw * 1.4);
    dots.forEach((d, i) => {
      const k = i % 3, c = curves[k];
      if (!c || (i < 3 && !route.spec.marks[0]) || (i >= 6 && !route.spec.marks[1])) { d.visible = false; return; }
      const u = i < 3 ? 0 : i < 6 ? route.u.hero[k] + (route.u.cta[k] - route.u.hero[k]) * p : 1;
      const q = Math.min(1, Math.max(0, u));
      if (q > flow.uDraw.value + 0.001) { d.visible = false; return; }
      c.getPointAt(q, tmp);
      d.visible = true;
      d.position.copy(tmp);
      d.scale.setScalar(route.dotR * grow * (i >= 3 && i < 6 ? 1 + Math.sin(clock.t * 2 + i) * 0.04 : 1));
    });
    const fade = Math.round(Math.min(1, Math.max(0, state.dim)) * 200) / 200;
    if (fade !== lastFade) canvas.style.opacity = lastFade = fade;
    renderer.render(scene, camera);
  };
  requestAnimationFrame(frame);

  /** Give the line its route (page pixels). Call again after the layout changes. */
  const setRoute = (spec) => { route = { spec, u: { hero: [0, 0, 0], cta: [1, 1, 1] } }; build(); };
  return { state, setRoute, three: { renderer, scene, camera, tubes, dots, curves, quality: () => [`${renderer.getPixelRatio().toFixed(2)}x`, shadows ? "shadows" : "no shadows", tubes.map((t) => t.geometry.attributes.position?.count || 0).join("+") + " verts"] } };
}
