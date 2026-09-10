// The voice aura — VOICE.md §3. A field of light around the body that breathes
// with Poppy's voice: it blooms and frays outward when he speaks, draws in and
// settles when he listens, drifts in slow thought between the two.
//
// One displaced shell, one point cloud, six rings — but they all read from the
// SAME smoothed level, the same band groups, the same colour ramp and the same
// time base, so the thing on screen is one entity and not three effects
// stacked. Nothing here snaps: levels are attack/release filtered and every
// phase is a weight that cross-fades against the others.
import * as THREE from 'three';
import { clamp01, easeOutQuart, lerp } from './easing';
import type { HoloTheme } from './materials';

export type VoicePhase =
  'off' | 'connecting' | 'listening' | 'hearing' | 'thinking' | 'speaking';

export interface HoloVoice {
  phase: VoicePhase;
  out: number;        // 0..1 raw outgoing envelope   (smoothing lives here)
  in: number;         // 0..1 raw mic envelope
  bands: number[];    // 8 values 0..1, low -> high
}

export interface VoiceAura {
  group: THREE.Group;
  /** Phase-weighted smoothed level — index.ts adds it to the bloom. */
  readonly energy: number;
  /** True once the fade-out is done and the group can be thrown away. */
  readonly closed: boolean;
  setVoice(v: HoloVoice): void;
  /** Session over: fade to nothing instead of vanishing mid-frame. */
  close(): void;
  setPixelRatio(dpr: number): void;
  /** `camera` billboards the corona — it is drawn in the plane of the screen. */
  update(dt: number, time: number, camera: THREE.Camera): void;
  dispose(): void;
}

const TAU = Math.PI * 2;
const CENTER_Y = 0.32;            // the aura hangs on the chest, not the base
// Hugs the body. It grows with his voice, so the resting size has to leave
// somewhere to grow TO — a field that starts big has nothing left to say.
const RADII: [number, number, number] = [0.42, 0.52, 0.42];
// 1.0 == the frame edge at the subject plane. Everything fades before it, so
// no part of the field ever meets a hard rectangle.
const SAFE: [number, number, number] = [0.95, 0.72, 0.95];

const ATTACK = 0.025;             // level follower, seconds
const RELEASE = 0.18;
const B_ATTACK = 0.030;           // bands are a touch lazier than the level
const B_RELEASE = 0.220;
const PHASE_TAU = 0.115;          // ~350 ms to settle a phase cross-fade
const ONSET_LEVEL = 0.18;         // syllable trigger
const ONSET_GAP = 0.12;           // refractory
const FUZZ = 2000;                // points
const RING_COUNT = 6;
const RING_LIFE = 1.3;

// index into the phase weight vector; 'off' is kept so a caller that leaves the
// aura mounted while the session dies still fades out instead of snapping.
const PHASES: VoicePhase[] =
  ['off', 'connecting', 'listening', 'hearing', 'thinking', 'speaking'];

// The dark ramp glows on black; the light one is a watercolour wash on paper
// that deepens instead of brightening (KIOSK.md §2). `hot` is what the shaders
// mix toward on a syllable: white on black, and deep cobalt on paper, because
// mixing toward white on a white page is mixing toward nothing. `gain` lifts
// the alphas for normal blending, which is far fainter than additive at the
// same numbers.
interface AuraLook { low: THREE.Color; mid: THREE.Color; high: THREE.Color;
                     hot: THREE.Color; gain: number; blending: THREE.Blending; }
const LOOKS: Record<HoloTheme, AuraLook> = {
  dark: {
    low: new THREE.Color(0x1e5c99),
    mid: new THREE.Color(0x4fc3ff),
    high: new THREE.Color(0xcff3ff),
    hot: new THREE.Color(0xffffff),
    gain: 1.0,
    blending: THREE.AdditiveBlending,
  },
  light: {
    low: new THREE.Color(0x1b4f8a),
    mid: new THREE.Color(0x3b8ee0),
    high: new THREE.Color(0x8fc6f5),
    hot: new THREE.Color(0x1450b8),
    gain: 1.8,
    blending: THREE.NormalBlending,
  },
};

/** One-pole follower with separate attack/release — snap up, relax down. */
function follow(cur: number, target: number, dt: number, up: number, down: number): number {
  const tau = target > cur ? up : down;
  return cur + (target - cur) * (1 - Math.exp(-dt / tau));
}

/** The vertical gradient, sampled on the CPU so rings match the shell. */
function rampAt(look: AuraLook, t: number, out: THREE.Color): void {
  if (t < 0.5) out.copy(look.low).lerp(look.mid, clamp01(t * 2));
  else out.copy(look.mid).lerp(look.high, clamp01((t - 0.5) * 2));
}

// ---- GLSL ---------------------------------------------------------------

// Classic 3D simplex noise — Ashima Arts / Stefan Gustavson (webgl-noise,
// "simplex noise 3D", MIT). Kept verbatim so it is recognisable.
const SNOISE = `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));
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

// Everything the field is made of, shared by all three shader stages that
// touch it — one uniform block, one fade, one definition of "extra light".
const COMMON = `
#define AU_PI 3.141592653589793
#define AU_TAU 6.283185307179586
uniform float uFlow;      // shared clock; runs faster the louder he is
uniform float uEnergy;    // phase-weighted smoothed level
uniform float uAmp;       // displacement amplitude
uniform vec3  uOct;       // octave amplitudes <- low / mid / high band groups
uniform float uScale;     // breath + bloom, applied to the whole field
uniform vec3  uRadii;
uniform vec3  uSafe;
uniform float uPulseY;    // syllable pulse, travelling up the body
uniform float uPulseAmp;
uniform float uOrbit;     // the thinking band's angle
uniform float uOrbitAmp;
uniform float uB[8];

/** Dissolve to nothing before the field reaches the edge of the frame. */
float safeFade(vec3 p) {
  return 1.0 - smoothstep(0.78, 1.0, length(p / uSafe));
}

/** Extra light: the syllable pulse riding up, plus the thinking band. */
float bright(vec3 p) {
  float ny = clamp(p.y / (uRadii.y * uScale), -1.2, 1.2);
  float dy = (ny - uPulseY) * 2.2;                 // pow() hates negative bases
  float a = atan(p.z, p.x);
  float da = (abs(mod(a - uOrbit + AU_PI, AU_TAU) - AU_PI)) * 1.8;
  return uPulseAmp * exp(-dy * dy) + uOrbitAmp * exp(-da * da);
}
`;

// Domain-warped 3-octave noise. The warp is what stops it looking like a
// lava lamp: the ripples curl around the body instead of pulsing in place.
const FIELD = `
float field(vec3 dir) {
  vec3 w = vec3(
    snoise(dir * 0.90 + vec3(0.0, uFlow * 0.35, 0.0)),
    snoise(dir * 0.90 + vec3(4.7, uFlow * 0.31, 1.3)),
    snoise(dir * 0.90 + vec3(9.2, uFlow * 0.27, 6.4)));
  vec3 p = dir + w * (0.22 + 0.40 * uEnergy);
  float n = uOct.x * snoise(p * 1.30 + vec3(0.0, uFlow * 0.42, 0.0));
  n += uOct.y * snoise(p * 2.90 + vec3(1.7, uFlow * 0.85, 0.0));
  n += uOct.z * snoise(p * 5.60 + vec3(0.0, uFlow * 1.55, 3.3));
  return n * uAmp;
}
`;

const RAMP = `
uniform vec3 uColLow;
uniform vec3 uColMid;
uniform vec3 uColHigh;
uniform float uAlpha;     // the shell's rim
uniform float uFuzz;      // the point cloud, scaled independently of the rim
uniform float uTint;      // 1 = pulled down to the deep blue (hearing)
uniform vec3 uHot;        // what a syllable mixes toward: white on black

vec3 ramp(float t) {
  vec3 c = t < 0.5 ? mix(uColLow, uColMid, t * 2.0)
                   : mix(uColMid, uColHigh, (t - 0.5) * 2.0);
  return mix(c, uColLow, uTint * 0.75);
}
`;

// The corona is a screen-facing quad, not a shell.
//
// Every lit closed surface — fresnel, rim, wisps, whatever — reads as a
// container the robot is sitting inside, because the eye locks onto the
// silhouette. Tried it three ways; it was a soap bubble every time. A halo
// drawn in the plane of the screen cannot enclose anything: its middle is
// transparent by construction, so the body is never behind glass. What was
// the shell's displacement becomes the wobble of the halo's radius, which
// says the same thing about his voice and says it more legibly.
const HALO_VERT = `
varying vec2 vP;
void main() {
  vP = (uv - 0.5) * 2.0;                 // -1..1 across the quad
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const HALO_FRAG = `${SNOISE}${COMMON}${RAMP}
uniform float uHaloR;     // ring radius, in quad half-widths
uniform float uHaloW;     // gaussian thickness
uniform float uWobble;    // how far the band strays from a circle
varying vec2 vP;

void main() {
  float r = length(vP);
  float ang = atan(vP.y, vP.x);
  vec2 c = vec2(cos(ang), sin(ang));
  // three octaves around the ring, each weighted by a band group — the low end
  // makes it swell, the top end makes it fray
  float n1 = snoise(vec3(c * 1.5, uFlow * 0.30));
  float n2 = snoise(vec3(c * 4.0, uFlow * 0.75 + 11.0));
  float n3 = snoise(vec3(c * 9.0, uFlow * 1.40 + 23.0));
  float rad = uHaloR + uWobble * (n1 * 0.55 * uOct.x
                                + n2 * 0.32 * uOct.y
                                + n3 * 0.18 * uOct.z);
  float x = (r - rad) / max(uHaloW, 1e-3);
  float band = exp(-x * x);

  // the syllable pulse riding up, and the thinking band sweeping round
  float dy = (vP.y - uPulseY) * 1.9;
  float da = (abs(mod(ang - uOrbit + AU_PI, AU_TAU) - AU_PI)) * 1.8;
  float b = uPulseAmp * exp(-dy * dy) + uOrbitAmp * exp(-da * da);

  // a whisper of haze inside the ring so he stands IN light rather than in a
  // hole cut out of it
  float haze = (1.0 - smoothstep(0.0, rad, r)) * 0.07;

  float t = clamp(vP.y * 0.5 + 0.5, 0.0, 1.0);
  float hot = clamp(uEnergy * 0.30 * band + b * 0.45, 0.0, 0.38);
  vec3 col = mix(ramp(t), uHot, hot);
  float a = uAlpha * (band * (1.0 + b * 1.4) + haze);
  a *= 1.0 - smoothstep(0.90, 1.0, r);   // never let it reach the quad's edge
  if (a <= 0.002) discard;
  gl_FragColor = vec4(col, a);
}
`;

const FUZZ_VERT = `${SNOISE}${COMMON}${FIELD}${RAMP}
attribute float aSeed;
attribute float aBand;
uniform float uGap;
uniform float uDpr;
varying vec3 vCol;
varying float vA;

void main() {
  vec3 dir = normalize(position);
  vec3 up = abs(dir.y) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
  vec3 t1 = normalize(cross(dir, up));
  vec3 t2 = cross(dir, t1);
  float ph = aSeed * 63.0;
  // swim slowly across the shell so the fuzz never looks like a fixed lattice
  vec3 d = normalize(dir + t1 * sin(uFlow * 0.45 + ph) * 0.06
                         + t2 * cos(uFlow * 0.37 + ph * 1.7) * 0.06);
  float b = uB[int(aBand)];
  float gap = uGap + aSeed * 0.05 + (0.02 + 0.16 * uEnergy) * b;
  vec3 p = d * (1.0 + field(d) + gap) * uRadii * uScale;
  float tw = 0.35 + 0.65 * pow(abs(sin(uFlow * 1.25 + ph)), 3.0);
  float lit = clamp(uEnergy * 0.55 + b * 0.35, 0.0, 0.75);
  vCol = mix(ramp(clamp(d.y * 0.5 + 0.5, 0.0, 1.0)), uHot, lit);
  // the fuzz carries its own weight: the shell is a rim now, and "it fuzzes"
  // is the part of the brief these points ARE
  vA = uFuzz * (0.35 + 0.85 * uEnergy) * tw * (0.30 + 0.70 * b) * safeFade(p);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = (1.5 + 1.3 * uEnergy + 1.0 * b) * uDpr
                 * clamp(2.35 / -mv.z, 0.7, 1.5);
  gl_Position = projectionMatrix * mv;
}
`;

const FUZZ_FRAG = `
varying vec3 vCol;
varying float vA;

void main() {
  // soft round dot — no texture, and cheaper than one
  float a = vA * (1.0 - smoothstep(0.08, 0.5, length(gl_PointCoord - 0.5)));
  if (a <= 0.002) discard;
  gl_FragColor = vec4(vCol, a);
}
`;

const RING_VERT = `
varying float vB;
varying float vAng;

void main() {
  vB = (length(position.xy) - 1.0) / 0.30;
  vAng = atan(position.y, position.x);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const RING_FRAG = `
uniform vec3 uColor;
uniform float uAlpha;
uniform float uPhase;
varying float vB;
varying float vAng;

void main() {
  float band = smoothstep(0.0, 0.45, vB) * (1.0 - smoothstep(0.55, 1.0, vB));
  float a = uAlpha * band * (0.72 + 0.28 * sin(vAng * 3.0 + uPhase));
  if (a <= 0.002) discard;
  gl_FragColor = vec4(uColor, a);
}
`;

interface Ring {
  mesh: THREE.Mesh;
  mat: THREE.ShaderMaterial;
  age: number;
  from: number;
  to: number;
  gain: number;
  alive: boolean;
}

export function createAura(theme: HoloTheme = 'dark'): VoiceAura {
  const look = LOOKS[theme];
  const group = new THREE.Group();
  group.position.y = CENTER_Y;

  // one uniforms object, shared by shell and fuzz — the cheapest possible
  // guarantee that the two never disagree about the field
  const U = {
    uFlow: { value: 0 },
    uEnergy: { value: 0 },
    uAmp: { value: 0.03 },
    uOct: { value: new THREE.Vector3(0.55, 0.28, 0.12) },
    uScale: { value: 1 },
    uRadii: { value: new THREE.Vector3(RADII[0], RADII[1], RADII[2]) },
    uSafe: { value: new THREE.Vector3(SAFE[0], SAFE[1], SAFE[2]) },
    uPulseY: { value: 0 },
    uPulseAmp: { value: 0 },
    uOrbit: { value: 0 },
    uOrbitAmp: { value: 0 },
    uB: { value: [0, 0, 0, 0, 0, 0, 0, 0] },
    uColLow: { value: look.low.clone() },
    uColMid: { value: look.mid.clone() },
    uColHigh: { value: look.high.clone() },
    uHot: { value: look.hot.clone() },
    uAlpha: { value: 0 },
    uFuzz: { value: 0 },
    uTint: { value: 0 },
    uHaloR: { value: 0.50 },
    uHaloW: { value: 0.16 },
    uWobble: { value: 0.05 },
    uGap: { value: 0.03 },
    uDpr: { value: 1 },
  };

  // ---- corona -----------------------------------------------------------
  // 1.9 x 2.2 units: r = 1 lands at 0.95 out sideways and 1.1 up, so an
  // isotropic radius in quad space is already the taller-than-wide ellipse
  // the body wants. Billboarded every frame in update().
  const haloGeom = new THREE.PlaneGeometry(1.9, 2.2);
  const haloMat = new THREE.ShaderMaterial({
    uniforms: U,
    vertexShader: HALO_VERT,
    fragmentShader: HALO_FRAG,
    transparent: true,
    blending: look.blending,
    depthWrite: false,
    depthTest: false,
    side: THREE.DoubleSide,
  });
  const halo = new THREE.Mesh(haloGeom, haloMat);
  halo.frustumCulled = false;
  halo.renderOrder = -1;              // behind the body's own additive layers
  group.add(halo);

  // ---- fuzz -------------------------------------------------------------
  const dirs = new Float32Array(FUZZ * 3);
  const seeds = new Float32Array(FUZZ);
  const bandOf = new Float32Array(FUZZ);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < FUZZ; i++) {
    const y = 1 - ((i + 0.5) / FUZZ) * 2;          // Fibonacci sphere
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = golden * i;
    dirs[i * 3] = Math.cos(th) * r;
    dirs[i * 3 + 1] = y;
    dirs[i * 3 + 2] = Math.sin(th) * r;
    seeds[i] = Math.random();
    // the spectrum wraps the body: bass at the waist, air around the head
    bandOf[i] = Math.min(7, Math.floor((y * 0.5 + 0.5) * 8));
  }
  const fuzzGeom = new THREE.BufferGeometry();
  fuzzGeom.setAttribute('position', new THREE.BufferAttribute(dirs, 3));
  fuzzGeom.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
  fuzzGeom.setAttribute('aBand', new THREE.BufferAttribute(bandOf, 1));
  const fuzzMat = new THREE.ShaderMaterial({
    uniforms: U,
    vertexShader: FUZZ_VERT,
    fragmentShader: FUZZ_FRAG,
    transparent: true,
    blending: look.blending,
    depthWrite: false,
  });
  const fuzz = new THREE.Points(fuzzGeom, fuzzMat);
  fuzz.frustumCulled = false;
  group.add(fuzz);

  // ---- rings ------------------------------------------------------------
  const ringGeom = new THREE.RingGeometry(1, 1.3, 96, 1);
  const rings: Ring[] = [];
  for (let i = 0; i < RING_COUNT; i++) {
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: look.mid.clone() },
        uAlpha: { value: 0 },
        uPhase: { value: 0 },
      },
      vertexShader: RING_VERT,
      fragmentShader: RING_FRAG,
      transparent: true,
      blending: look.blending,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(ringGeom, mat);
    mesh.visible = false;
    mesh.frustumCulled = false;
    group.add(mesh);
    rings.push({ mesh, mat, age: 0, from: 0.3, to: 0.9, gain: 0, alive: false });
  }

  // ---- state ------------------------------------------------------------
  let phase: VoicePhase = 'listening';
  let rawOut = 0;
  let rawIn = 0;
  const rawBands = [0, 0, 0, 0, 0, 0, 0, 0];

  const W = [0, 0, 1, 0, 0, 0];            // phase weights, always summing to 1
  const bands = [0, 0, 0, 0, 0, 0, 0, 0];
  let level = 0;
  let drive = 0;
  let flow = 0;
  let orbit = 0;
  let pulseAmp = 0;
  let pulseY = 0;
  let prevLevel = 0;
  let sinceOnset = 9;
  const scratch = new THREE.Color();
  const camPos = new THREE.Vector3();   // reused: no allocation in the loop

  function spawnRing(inward: boolean, gain: number): void {
    let slot = rings[0];
    for (const r of rings) {
      if (!r.alive) { slot = r; break; }
      if (r.age > slot.age) slot = r;         // steal the oldest if all are busy
    }
    slot.alive = true;
    slot.age = 0;
    slot.gain = gain;
    // sized against the shell (0.42 wide), not against the frame — rings that
    // expand to twice the field detach from it and read as loose scanlines
    slot.from = inward ? 0.56 : 0.20;
    slot.to = inward ? 0.18 : 0.60;
    // The camera sits almost level with the chest, so a horizontal ring there
    // projects to a straight line and reads as a stray scanline. Spawn them
    // low and tilt them hard: seen from above, they come back as ellipses.
    const y = lerp(-0.24, 0.16, Math.random() * Math.random());
    slot.mesh.position.y = y;
    slot.mesh.rotation.set(-Math.PI / 2 + (Math.random() - 0.5) * 0.9, 0,
                           (Math.random() - 0.5) * 0.9);
    slot.mat.uniforms.uPhase.value = Math.random() * TAU;
    rampAt(look, clamp01(y / RADII[1] * 0.5 + 0.5), scratch);
    (slot.mat.uniforms.uColor.value as THREE.Color).copy(scratch);
  }

  function updateRings(dt: number): void {
    for (const r of rings) {
      if (!r.alive) continue;
      r.age += dt;
      const u = r.age / RING_LIFE;
      if (u >= 1) {
        r.alive = false;
        r.mesh.visible = false;
        continue;
      }
      const rad = lerp(r.from, r.to, easeOutQuart(u));
      r.mesh.scale.set(rad, rad, 1);
      const env = Math.min(1, u / 0.10) * Math.pow(1 - u, 1.5);
      // Gone by 0.58, where the ring mesh's outer edge (1.3x) still clears the
      // narrow half of the stage — the deck pane is far tighter than the
      // full-width harness, and a ring meeting the frame is a straight line.
      const edge = 1 - clamp01((rad - 0.36) / 0.22);
      // W[0] is 'off': a ring in flight when the session ends fades with the
      // rest of the field instead of hanging there
      r.mat.uniforms.uAlpha.value = look.gain * 0.5 * r.gain * env * edge * (1 - W[0]);
      r.mesh.visible = true;
    }
  }

  return {
    group,

    get energy(): number {
      return drive;
    },

    get closed(): boolean {
      return W[0] > 0.995;
    },

    setVoice(v: HoloVoice): void {
      phase = v.phase;
      rawOut = v.out;
      rawIn = v.in;
      for (let i = 0; i < 8; i++) rawBands[i] = v.bands[i] ?? 0;
    },

    close(): void {
      phase = 'off';
      rawOut = 0;
      rawIn = 0;
      for (let i = 0; i < 8; i++) rawBands[i] = 0;
    },

    setPixelRatio(dpr: number): void {
      U.uDpr.value = dpr;
    },

    update(dt: number, time: number, camera: THREE.Camera): void {
      halo.lookAt(camera.getWorldPosition(camPos));

      // ---- phase cross-fade: every look below is a weighted sum -----------
      const target = PHASES.indexOf(phase);
      const k = 1 - Math.exp(-dt / PHASE_TAU);
      for (let i = 0; i < W.length; i++) W[i] += ((i === target ? 1 : 0) - W[i]) * k;
      const wConn = W[1];   // W[0] is 'off' — it contributes nothing, by design
      const wIdle = W[2];
      const wHear = W[3];
      const wThink = W[4];
      const wSpeak = W[5];

      // ---- levels: his voice, or the room's while he is hearing -----------
      level = follow(level, clamp01(lerp(rawOut, rawIn, wHear)), dt, ATTACK, RELEASE);
      drive = level * (wSpeak + 0.75 * wHear + 0.5 * wThink);
      for (let i = 0; i < 8; i++) {
        bands[i] = follow(bands[i], clamp01(rawBands[i]), dt, B_ATTACK, B_RELEASE);
        U.uB.value[i] = bands[i];
      }
      const low = (bands[0] + bands[1]) * 0.5;
      const mid = (bands[2] + bands[3] + bands[4]) / 3;
      const high = (bands[5] + bands[6] + bands[7]) / 3;

      // ---- one clock for the whole field, faster the louder he is ---------
      flow += dt * (0.28 + 1.30 * drive);
      orbit += dt * (TAU / 2.5);
      if (orbit > TAU) orbit -= TAU;

      // ---- syllable onsets: a ring outward and a pulse up the body --------
      sinceOnset += dt;
      if (wSpeak + wHear > 0.5 && level > ONSET_LEVEL && prevLevel <= ONSET_LEVEL
          && sinceOnset > ONSET_GAP) {
        spawnRing(wHear > wSpeak, 0.45 + 0.55 * level);
        sinceOnset = 0;
        pulseAmp = 0.30 + 0.40 * level;
        pulseY = -1.05;
      }
      prevLevel = level;
      pulseY = Math.min(pulseY + dt * 2.4, 2);   // parked above the head between syllables
      pulseAmp *= Math.exp(-dt / 0.45);
      updateRings(dt);

      // ---- the field's shape ---------------------------------------------
      const breath = Math.sin(time * TAU * 0.16) * 0.03 * (0.45 + 0.55 * (wIdle + wConn));
      U.uFlow.value = flow;
      // ±40 % of the radius at full voice. ±55 % read as an explosion, ±12 %
      // read as a balloon; the shape has to move enough to be the message.
      U.uAmp.value = 0.03 + 0.17 * drive;
      U.uOct.value.set(0.55 + 0.75 * low, 0.28 + 0.55 * mid, 0.12 + 0.30 * high);
      U.uScale.value = (1 + 0.16 * drive) * (1 - 0.15 * wHear) * (1 + breath);
      U.uEnergy.value = drive;
      U.uGap.value = 0.03 + 0.10 * drive;
      U.uPulseY.value = pulseY;
      U.uPulseAmp.value = pulseAmp * (wSpeak + wHear);
      U.uOrbit.value = orbit;
      U.uOrbitAmp.value = 0.45 * wThink;
      U.uTint.value = wHear;
      // The corona: it swells and thickens with his voice, and draws in when
      // he is the one listening. The radius is kept well inside the frame —
      // a band that reaches the edge stops being a halo around him and turns
      // into a vignette flooding in from the borders.
      U.uHaloR.value = (0.40 + 0.10 * drive) * (1 - 0.13 * wHear) * (1 + breath);
      U.uHaloW.value = 0.070 + 0.090 * drive;
      U.uWobble.value = 0.030 + 0.090 * drive;

      // ---- and its brightness ---------------------------------------------
      // Tuned by eye against the real robot on a dark stage. The ceiling
      // matters more than the floor: additive light over an already-additive
      // body blows out long before the number looks big, and a field that
      // hides the robot has defeated itself.
      const connPulse = 0.45 + 0.55 * Math.sin(time * TAU * 0.55);
      U.uAlpha.value = look.gain * (
        wIdle * 0.055
        + wConn * 0.070 * connPulse
        + wHear * (0.050 + 0.135 * level)
        + wThink * (0.070 + 0.090 * level)
        + wSpeak * (0.055 + 0.185 * level));
      U.uFuzz.value = look.gain * (
        wIdle * 0.055
        + wConn * 0.065 * connPulse
        + wHear * (0.055 + 0.175 * level)
        + wThink * (0.070 + 0.110 * level)
        + wSpeak * (0.060 + 0.210 * level));
    },

    dispose(): void {
      haloGeom.dispose();
      haloMat.dispose();
      fuzzGeom.dispose();
      fuzzMat.dispose();
      ringGeom.dispose();
      for (const r of rings) r.mat.dispose();
      group.clear();
    },
  };
}
