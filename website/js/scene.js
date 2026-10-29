// The 3D world behind the page: AFH's mark (three strands joining six points) built as glowing
// tubes, with thousands of light particles flowing along them. Scrolling morphs the particles
// into other shapes (a core, three orbiting agents, a ring of models) and back into the mark.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// The logo's SVG paths (viewBox 240×140), each as two cubic segments sharing a middle point,
// plus a depth (z) per control point so the strands weave in 3D.
const STRANDS = [
  { pts: [[46, 28], [104, 28], [108, 74], [134, 74], [160, 74], [164, 28], [194, 28]], z: [0, 0.9, 0.9, 0.5, 0.1, -0.6, 0], from: "#ffb11f", to: "#ff7a3d" },
  { pts: [[46, 70], [92, 70], [98, 58], [120, 60], [150, 63], [152, 82], [194, 70]], z: [0, -0.5, -0.5, 0, 0.5, 0.5, 0], from: "#ff7747", to: "#ff4a68" },
  { pts: [[46, 112], [108, 112], [116, 66], [146, 66], [172, 66], [170, 112], [194, 112]], z: [0, -0.9, -0.9, -0.5, -0.1, 0.6, 0], from: "#ff3d8a", to: "#e0169a" },
];
const S = 1 / 30;
const toV = ([x, y], z) => new THREE.Vector3((x - 120) * S, -(y - 70) * S, z);

const BEZIER_GLSL = /* glsl */ `
  uniform vec3 uP[21];
  vec3 bez(vec3 a, vec3 b, vec3 c, vec3 d, float t) {
    float u = 1.0 - t;
    return u*u*u*a + 3.0*u*u*t*b + 3.0*u*t*t*c + t*t*t*d;
  }
  vec3 strandAt(int s, float t) {
    int seg = t < 0.5 ? 0 : 1;
    float lt = seg == 0 ? t * 2.0 : t * 2.0 - 1.0;
    int b = s * 7 + seg * 3;
    return bez(uP[b], uP[b + 1], uP[b + 2], uP[b + 3], lt);
  }
`;

export function createScene(canvas, { mobile = false, reduced = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, mobile ? 1.5 : 1.75));
  // the composer works in linear light, so this is #0a0807 once it reaches the screen
  renderer.setClearColor(0x030202, 1);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0807, 0.045);
  const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 200);
  camera.position.set(0, 0, 10);

  const world = new THREE.Group();
  scene.add(world);
  const mark = new THREE.Group(); // tubes + end points
  world.add(mark);

  // ---- strands as tubes ----
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
            float a;
            if (uGlow > 0.5) a = (1.0 - rim) * 0.05 + pulse * 0.06;
            else a = 0.42 + rim * 0.25 + pulse * 0.7;
            gl_FragColor = vec4(col * (1.0 + pulse * 1.6), a * uOpacity);
          }`,
      });
      tubeMats.push(mat);
      mark.add(new THREE.Mesh(new THREE.TubeGeometry(path, 220, radius, 20, false), mat));
    }
  });

  // ---- the six points ----
  const dotMats = [];
  const dotGeo = new THREE.SphereGeometry(0.25, 40, 40);
  curves.forEach(({ v }, i) => {
    for (const [p, c] of [[v[0], STRANDS[i].from], [v[6], STRANDS[i].to]]) {
      const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(c).multiplyScalar(1.15), transparent: true });
      dotMats.push(mat);
      const m = new THREE.Mesh(dotGeo, mat);
      m.position.copy(p);
      mark.add(m);
    }
  });

  // ---- flowing particles (and their other shapes) ----
  const N = reduced ? 2500 : mobile ? 5000 : 11000;
  const g = new THREE.BufferGeometry();
  const aStrand = new Float32Array(N), aT = new Float32Array(N), aSpeed = new Float32Array(N), aRand = new Float32Array(N);
  const aJitter = new Float32Array(N * 3), aCore = new Float32Array(N * 3), aAgents = new Float32Array(N * 3), aRing = new Float32Array(N * 3);
  const rnd = (a = 1) => (Math.random() * 2 - 1) * a;
  for (let i = 0; i < N; i++) {
    aStrand[i] = i % 3;
    aT[i] = Math.random();
    aSpeed[i] = 0.02 + Math.random() * 0.05;
    aRand[i] = Math.random();
    // a soft cloud around the tube
    const r = Math.pow(Math.random(), 0.8) * 0.3, th = Math.random() * Math.PI * 2, ph = Math.acos(rnd());
    aJitter.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph)], i * 3);
    // core: a shell of points around a bright centre, like a mind at work
    const cr = 2.1 + Math.pow(Math.random(), 3) * 1.2 * (Math.random() < 0.3 ? 1 : 0.25);
    const u = rnd(), a = Math.random() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    aCore.set([cr * s * Math.cos(a), cr * u, cr * s * Math.sin(a)], i * 3);
    // agents: one lead in the centre and three subagents (shape picked by index in the shader)
    const ar = Math.pow(Math.random(), 0.5) * (i % 4 === 0 ? 1.15 : 0.62);
    const au = rnd(), aa = Math.random() * Math.PI * 2, as = Math.sqrt(1 - au * au);
    aAgents.set([ar * as * Math.cos(aa), ar * au, ar * as * Math.sin(aa)], i * 3);
    // ring: a wide torus where the models orbit
    const ra = Math.random() * Math.PI * 2, tr = 4.6 + rnd(0.35) + Math.pow(Math.random(), 4) * rnd(1.4);
    aRing.set([Math.cos(ra) * tr, rnd(0.18) + Math.pow(Math.random(), 6) * rnd(1.2), Math.sin(ra) * tr], i * 3);
  }
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N * 3), 3));
  g.setAttribute("aStrand", new THREE.BufferAttribute(aStrand, 1));
  g.setAttribute("aT", new THREE.BufferAttribute(aT, 1));
  g.setAttribute("aSpeed", new THREE.BufferAttribute(aSpeed, 1));
  g.setAttribute("aRand", new THREE.BufferAttribute(aRand, 1));
  g.setAttribute("aJitter", new THREE.BufferAttribute(aJitter, 3));
  g.setAttribute("aCore", new THREE.BufferAttribute(aCore, 3));
  g.setAttribute("aAgents", new THREE.BufferAttribute(aAgents, 3));
  g.setAttribute("aRing", new THREE.BufferAttribute(aRing, 3));
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 50);

  const uP = curves.flatMap(({ v }) => v);
  const colors = STRANDS.flatMap((s) => [new THREE.Color(s.from), new THREE.Color(s.to)]);
  const pMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uP: { value: uP }, uTime: { value: 0 }, uMorph: { value: 0 }, uSize: { value: mobile ? 16 : 13 },
      uPixel: { value: renderer.getPixelRatio() }, uCol: { value: colors }, uSpread: { value: 0 },
    },
    vertexShader: /* glsl */ `
      ${BEZIER_GLSL}
      uniform float uTime, uMorph, uSize, uPixel, uSpread; uniform vec3 uCol[6];
      attribute float aStrand, aT, aSpeed, aRand; attribute vec3 aJitter, aCore, aAgents, aRing;
      varying vec3 vCol; varying float vAlpha;
      mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
      void main() {
        int s = int(aStrand + 0.5);
        float t = fract(aT + uTime * aSpeed);
        vec3 logo = strandAt(s, t) + aJitter * (1.0 + uSpread * 4.0);

        vec3 core = aCore * (1.0 + 0.06 * sin(uTime * 1.3 + aRand * 12.0));
        core.xz = rot(uTime * 0.18 + aRand * 0.2) * core.xz;

        // agents: index 0 = lead in the middle, 1..3 = subagents orbiting it
        int k = int(mod(float(gl_VertexID), 4.0));
        vec3 agents = aAgents;
        agents.xz = rot(uTime * 0.6) * agents.xz;
        if (k > 0) {
          float a = uTime * 0.35 + float(k) * 2.0944;
          agents += vec3(cos(a) * 3.3, sin(a * 1.3) * 0.7, sin(a) * 3.3);
        }

        vec3 ring = aRing;
        ring.xz = rot(uTime * 0.09) * ring.xz;

        // each particle leaves a little earlier or later so shapes pour into each other
        float m = clamp(uMorph * 1.0 + (aRand - 0.5) * 0.35, 0.0, 3.0);
        vec3 p = mix(logo, core, smoothstep(0.0, 1.0, clamp(m, 0.0, 1.0)));
        p = mix(p, agents, smoothstep(0.0, 1.0, clamp(m - 1.0, 0.0, 1.0)));
        p = mix(p, ring, smoothstep(0.0, 1.0, clamp(m - 2.0, 0.0, 1.0)));

        vCol = mix(uCol[s * 2], uCol[s * 2 + 1], t);
        if (k == 0 && m > 1.4 && m < 2.6) vCol = mix(vCol, vec3(1.0, 0.85, 0.6), 0.5);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        float twinkle = 0.65 + 0.35 * sin(uTime * 3.0 + aRand * 40.0);
        float away = smoothstep(0.0, 1.0, clamp(m, 0.0, 1.0)); // out of the logo: bigger, brighter
        vAlpha = twinkle * (1.0 + away * 0.9);
        gl_PointSize = uSize * uPixel * (0.35 + aRand * 0.65) * (1.0 + away * 0.9) / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      varying vec3 vCol; varying float vAlpha;
      void main() {
        vec2 c = gl_PointCoord - 0.5;
        float d = length(c);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vCol * (1.0 + max(vAlpha - 1.0, 0.0)), min(a * a * vAlpha * 0.55, 1.0));
      }`,
  });
  const points = new THREE.Points(g, pMat);
  world.add(points);

  // ---- deep-space dust for depth ----
  const D = mobile ? 900 : 2200;
  const dg = new THREE.BufferGeometry();
  const dp = new Float32Array(D * 3);
  for (let i = 0; i < D; i++) dp.set([rnd(40), rnd(24), -Math.random() * 60 + 6], i * 3);
  dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
  const dust = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0xffc9a8, size: 0.05, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(dust);

  // ---- post: bloom ----
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.62, 0.55, 0.22);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---- state driven by the page ----
  const state = { morph: 0, mark: 1, spin: 0, tilt: 0, zoom: 0, shiftX: 0, shiftY: 0, spread: 0 };
  const mouse = { x: 0, y: 0, sx: 0, sy: 0 };
  addEventListener("pointermove", (e) => { mouse.x = e.clientX / innerWidth - 0.5; mouse.y = e.clientY / innerHeight - 0.5; }, { passive: true });

  const resize = () => {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w / 2, h / 2);
    camera.aspect = w / h;
    // keep the mark comfortably inside narrow screens
    camera.position.z = 10 * Math.max(1, 1.25 / Math.min(camera.aspect, 1.25));
    camera.updateProjectionMatrix();
  };
  addEventListener("resize", resize);
  resize();

  const clock = new THREE.Clock();
  let running = true;
  const frame = () => {
    if (!running) return;
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime * (reduced ? 0.3 : 1);
    mouse.sx += (mouse.x - mouse.sx) * Math.min(1, dt * 3);
    mouse.sy += (mouse.y - mouse.sy) * Math.min(1, dt * 3);

    pMat.uniforms.uTime.value = t;
    pMat.uniforms.uMorph.value = state.morph;
    pMat.uniforms.uSpread.value = state.spread;
    for (const m of tubeMats) { m.uniforms.uTime.value = t; m.uniforms.uOpacity.value = state.mark; }
    for (const m of dotMats) m.opacity = state.mark;
    mark.visible = state.mark > 0.01;
    mark.scale.setScalar(0.85 + state.mark * 0.15);

    world.rotation.y = state.spin + mouse.sx * 0.5 + Math.sin(t * 0.25) * 0.08;
    world.rotation.x = state.tilt - mouse.sy * 0.3 + Math.cos(t * 0.2) * 0.04;
    world.position.x = state.shiftX;
    world.position.y = state.shiftY;
    camera.position.x = mouse.sx * 0.6;
    camera.position.y = -mouse.sy * 0.4;
    camera.lookAt(state.shiftX * 0.25, state.shiftY * 0.25, 0);
    const baseZ = 10 * Math.max(1, 1.25 / Math.min(camera.aspect, 1.25));
    camera.position.z = baseZ - state.zoom;
    dust.rotation.y = t * 0.01;
    dust.position.z = (state.zoom * 1.5) % 30;

    composer.render();
  };
  frame();
  document.addEventListener("visibilitychange", () => {
    const was = running;
    running = !document.hidden;
    if (running && !was) { clock.getDelta(); frame(); }
  });

  return { state };
}
