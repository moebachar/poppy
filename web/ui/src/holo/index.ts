// POPPY/DECK hologram stage — public module per CONTRACT.md §4.
// Framework-free: three.js only, no React, no imports from outside src/holo/.
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { CAL } from './calibration';
import { buildRobot } from './robot';
import { createAura } from './aura';
import type { HoloVoice, VoiceAura } from './aura';
import { makeSharedMats, disposeSharedMats, PALETTES } from './materials';
import type { HoloTheme } from './materials';
import { clamp, clamp01, easeInOutCubic, easeOutQuart, lerp, smoothDampTo } from './easing';

export { CAL } from './calibration';
export type { HoloVoice, VoicePhase } from './aura';
export type { HoloTheme } from './materials';

export type HoloMode = 'dormant' | 'awakening' | 'live';
export interface HoloMotor { id: number; ok: boolean; present: boolean;
                             picked?: boolean; hover?: boolean; }
export interface Holo {
  setMode(m: HoloMode): void;      // 'awakening' runs the choreography then fires onAwakened
  setMotors(m: HoloMotor[]): void;
  setPose(deg: Record<string, number>): void;   // RAW degrees, keys = motor ids
  /** Live re-zero: use this raw pose as "the robot is at its neutral stance". */
  setZero(raw: Record<string, number> | null): void;
  /** Smoothly return the user's wheel-orbit to front-facing. */
  resetYaw(): void;
  /** Camera viewpoint: front (default), overhead, or the robot's right side. */
  setView(v: 'front' | 'top' | 'side'): void;
  /** Debug: a node's world position and world direction of its local +Y. */
  probe(nodeName: string): { pos: number[]; yDir: number[] } | null;
  setPickable(on: boolean): void;  // teach mode: markers clickable
  onMotorPick(cb: (id: number) => void): void;
  onMotorHover(cb: (id: number | null) => void): void;
  setHighlight(id: number | null): void;        // register-row hover -> marker ring
  /** Voice aura: null (or phase 'off') removes it from the scene entirely. */
  setVoice(v: HoloVoice | null): void;
  onAwakened(cb: () => void): void;
  resize(): void;
  dispose(): void;
}

const TAU = Math.PI * 2;
const DEG = Math.PI / 180;
const ANGLE_CLAMP = 170 * DEG;      // sanity clamp on applied joint angles
const SPIN_SPEED = TAU / 14;        // dormant turntable: one rev / 14 s
const AWAKEN_TOTAL = 2.1;           // full choreography length
const AWAKEN_SPIN = 0.9;            // (a) turntable decel
const AWAKEN_FADE = 0.6;            // (b)+(c) grid/glow fade + pose blend (last 0.6 s)
const SLEEP_TOTAL = 1.15;           // live -> dormant wind-down
const WAKE_FAST = 0.5;              // direct dormant -> live (no choreography)
const POSE_TAU = 0.12;              // live pose smoothing, critically damped

type Phase = 'dormant' | 'awaken' | 'live' | 'sleep' | 'wakefast';

// updateLook() opacity ranges, dormant -> live. Dark is the deck's, verbatim;
// light is ink on paper, so the lines carry the drawing and the fill is faint.
interface Look { fill: [number, number]; edge: [number, number];
                 rim: [number, number]; accent: [number, number]; grid: number; }
const LOOKS: Record<HoloTheme, Look> = {
  dark: { fill: [0.032, 0.040], edge: [0.30, 0.45], rim: [0.010, 0.020], accent: [0.25, 0.5], grid: 0.3 },
  light: { fill: [0.13, 0.17], edge: [0.48, 0.66], rim: [0.09, 0.15], accent: [0.55, 0.85], grid: 0.35 },
};

export interface HoloOptions {
  /** 'dark' (default) is the deck's stage; 'light' the kiosk's paper (KIOSK.md §2). */
  theme?: HoloTheme;
  /** Keep the printed parts below a dead motor on screen. The deck hides them
   *  (a dead motor cannot move its limb — do not show what cannot act); the
   *  kiosk shows a visitor the whole robot and lets the marker tell the truth. */
  keepDeadParts?: boolean;
}

interface JointState { target: number; from: number; v: number; vel: number; }

export function createHolo(canvas: HTMLCanvasElement, opts: HoloOptions = {}): Holo {
  const theme: HoloTheme = opts.theme ?? 'dark';
  const palette = PALETTES[theme];
  const look = LOOKS[theme];

  // ---- renderer / scene -------------------------------------------------
  const renderer = new THREE.WebGLRenderer({
    canvas, alpha: true, antialias: true, powerPreference: 'high-performance',
  });
  renderer.setClearColor(0x000000, 0);          // transparent — CSS --bg shows through

  const scene = new THREE.Scene();
  scene.background = null;

  const camera = new THREE.PerspectiveCamera(33, 1, 0.1, 10);
  const CAMS = {
    front: new THREE.Vector3(0, 0.5, 2.35),
    top: new THREE.Vector3(0, 2.45, 0.3),
    side: new THREE.Vector3(-2.35, 0.5, 0.15),   // the robot's right side
  } as const;
  const CAM_LOOK = new THREE.Vector3(0, 0.4, 0);
  camera.position.copy(CAMS.front);
  camera.lookAt(CAM_LOOK);
  let view: keyof typeof CAMS = 'front';

  const mats = makeSharedMats(theme);
  const robot = buildRobot(mats);
  // robot.ts builds its markers dark (it is the deck's file); re-skin after
  if (theme !== 'dark') for (const m of robot.markers.values()) m.setTheme(theme);

  // rig carries translate/scale; spin carries the turntable rotation
  const rig = new THREE.Group();
  const spinGroup = new THREE.Group();
  spinGroup.add(robot.root);
  rig.add(spinGroup);
  scene.add(rig);       // fixed center of its pane — the hologram never travels

  // ground grid, 12x12, live mode only
  const grid = new THREE.GridHelper(1.44, 12, palette.gridCenter, palette.gridLine);
  grid.position.y = 0.001;
  const gridMat = grid.material as THREE.LineBasicMaterial;
  gridMat.transparent = true;
  gridMat.opacity = 0;
  gridMat.depthWrite = false;
  grid.visible = false;
  scene.add(grid);

  // ---- post: restrained bloom ------------------------------------------
  // Dark only. Bloom on a light page is a wash, so the light stage renders
  // straight and there is no composer to size or dispose.
  interface Post { composer: EffectComposer; renderPass: RenderPass;
                   bloom: UnrealBloomPass; output: OutputPass; }
  let post: Post | null = null;
  if (theme === 'dark') {
    const composer = new EffectComposer(renderer);
    const renderPass = new RenderPass(scene, camera);
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.35, 0.2);
    const output = new OutputPass();
    composer.addPass(renderPass);
    composer.addPass(bloom);
    composer.addPass(output);
    post = { composer, renderPass, bloom, output };
  }

  // ---- state ------------------------------------------------------------
  let phase: Phase = 'dormant';
  let t = 0;                 // time inside current transition
  let time = 0;              // global clock
  let spin = Math.random() * TAU;
  let glow = 0;              // 0 = dormant look, 1 = live look
  let glowFrom = 0;
  let spinFrom = 0;
  let spinTo = 0;
  let blend = 0;             // awakening pose blend factor
  let pickable = false;
  let zero: Record<string, number> | null = null;   // live-captured stance offsets
  let userYaw = 0;               // wheel-orbit around the vertical, live mode
  let yawResetting = false;
  let highlightId: number | null = null;
  let hoverId: number | null = null;
  let pointerIn = false;
  let disposed = false;
  let aura: VoiceAura | null = null;   // built on the first voice frame, freed on 'off'
  let dpr = 1;

  const joints = new Map<number, JointState>();
  for (const idStr of Object.keys(CAL)) {
    joints.set(Number(idStr), { target: 0, from: 0, v: 0, vel: 0 });
  }

  const pickCbs: Array<(id: number) => void> = [];
  const hoverCbs: Array<(id: number | null) => void> = [];
  const awakenedCbs: Array<() => void> = [];

  // ---- picking ----------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();

  const onPointerMove = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    pointerIn = true;
  };
  const onPointerLeave = () => {
    pointerIn = false;
    setHover(null);
  };
  const onPointerDown = () => {
    if (pickable && hoverId !== null) {
      const id = hoverId;
      for (const cb of pickCbs) cb(id);
    }
  };
  const onWheel = (e: WheelEvent) => {
    if (phase !== 'live') return;
    e.preventDefault();
    userYaw += e.deltaY * 0.0035;
    yawResetting = false;
  };
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerleave', onPointerLeave);
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('wheel', onWheel, { passive: false });

  function setHover(id: number | null): void {
    if (id === hoverId) return;
    hoverId = id;
    canvas.style.cursor = pickable && id !== null ? 'pointer' : '';
    for (const cb of hoverCbs) cb(id);
  }

  function updateRaycast(): void {
    if (!pointerIn) return;
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObjects(robot.proxies, false);
    const id = hits.length > 0 ? (hits[0].object.userData.motorId as number) : null;
    setHover(id);
  }

  // ---- mode transitions -------------------------------------------------
  const normSpin = () => { spin = ((spin % TAU) + TAU) % TAU; };

  function startAwaken(): void {
    phase = 'awaken';
    t = 0;
    glowFrom = glow;
    normSpin();
    spinFrom = spin;
    spinTo = spinFrom < 0.03 ? spinFrom : TAU;   // decelerate forward to front-facing
    blend = 0;
    for (const j of joints.values()) { j.from = j.v; j.vel = 0; }
  }

  function startSleep(): void {
    phase = 'sleep';
    t = 0;
    glowFrom = glow;
    userYaw = 0;
    yawResetting = false;
    normSpin();
  }

  function startWakeFast(): void {
    phase = 'wakefast';
    t = 0;
    glowFrom = glow;
    normSpin();
    spinFrom = spin > Math.PI ? spin - TAU : spin;  // unwind by the short way
  }

  function finishAwaken(): void {
    phase = 'live';
    spin = 0;
    glow = 1;
    for (const j of joints.values()) { j.v = j.target; j.vel = 0; }
    for (const cb of awakenedCbs) cb();
  }

  // ---- per-frame update -------------------------------------------------
  function updatePhase(dt: number): void {
    switch (phase) {
      case 'dormant': {
        spin += dt * SPIN_SPEED;
        glow = Math.max(0, glow - dt * 2);
        break;
      }
      case 'sleep': {
        t += dt;
        const u = clamp01(t / SLEEP_TOTAL);
        glow = glowFrom * (1 - clamp01(t / 0.55));       // glow dims first
        spin += dt * SPIN_SPEED * u;                     // turntable spins back up
        if (u >= 1) phase = 'dormant';
        break;
      }
      case 'awaken': {
        t += dt;
        // (a) turntable decelerates to front-facing, ease-out quartic
        spin = lerp(spinFrom, spinTo, easeOutQuart(clamp01(t / AWAKEN_SPIN)));
        // (b) grid + rim glow fade in over the last 0.6 s
        glow = Math.max(
          clamp01((t - (AWAKEN_TOTAL - AWAKEN_FADE)) / AWAKEN_FADE),
          glowFrom * (1 - clamp01(t / 0.4)),
        );
        // (c) neutral -> live pose blend, ease-in-out, last 0.6 s
        blend = easeInOutCubic(clamp01((t - (AWAKEN_TOTAL - AWAKEN_FADE)) / AWAKEN_FADE));
        if (t >= AWAKEN_TOTAL) finishAwaken();
        break;
      }
      case 'wakefast': {
        t += dt;
        const u = clamp01(t / WAKE_FAST);
        spin = spinFrom * (1 - easeInOutCubic(u));
        glow = lerp(glowFrom, 1, u);
        if (u >= 1) { phase = 'live'; spin = 0; }
        break;
      }
      case 'live':
        break;
    }
    if (yawResetting) {
      userYaw *= Math.exp(-dt * 9);
      if (Math.abs(userYaw) < 0.004) {
        userYaw = 0;
        yawResetting = false;
      }
    }
    spinGroup.rotation.y = phase === 'live' ? userYaw : spin;

    // camera glides toward the selected viewpoint
    camera.position.lerp(CAMS[view], Math.min(1, dt * 6));
    camera.lookAt(CAM_LOOK);
  }

  function updateJoints(dt: number): void {
    for (const j of joints.values()) {
      switch (phase) {
        case 'live':
          smoothDampTo(j, j.target, POSE_TAU, dt);
          break;
        case 'awaken':
          j.v = lerp(j.from, j.target, blend);
          j.vel = 0;
          break;
        case 'wakefast':
          smoothDampTo(j, j.target, 0.18, dt);
          break;
        default: // dormant / sleep -> settle back to the neutral stand
          smoothDampTo(j, 0, 0.25, dt);
          break;
      }
    }
    for (const idStr of Object.keys(CAL)) {
      const id = Number(idStr);
      const c = CAL[id];
      const j = joints.get(id);
      const node = robot.nodes[c.node];
      if (j && node) node.rotation[c.axis] = clamp(j.v, -ANGLE_CLAMP, ANGLE_CLAMP);
    }
  }

  function updateLook(): void {
    mats.fill.opacity = lerp(look.fill[0], look.fill[1], glow);
    mats.fillZ.opacity = mats.fill.opacity;
    mats.edge.opacity = lerp(look.edge[0], look.edge[1], glow);
    mats.rim.opacity = lerp(look.rim[0], look.rim[1], glow);
    mats.accent.opacity = lerp(look.accent[0], look.accent[1], glow);
    // the screen itself brightens when he talks — that is the "shining"
    if (post) post.bloom.strength = lerp(0.35, 0.42, glow) + (aura ? 0.12 * aura.energy : 0);
    gridMat.opacity = look.grid * glow;
    grid.visible = glow > 0.01;
  }

  function updateMarkers(dt: number): void {
    const dim = lerp(0.8, 1, glow);
    for (const [id, marker] of robot.markers) {
      const hovered = hoverId === id || highlightId === id || marker.state.extHover;
      marker.update(dt, time, hovered, dim);
    }
  }

  // ---- loop -------------------------------------------------------------
  const clock = new THREE.Clock();
  let raf = 0;
  let lastTickAt = 0;
  function step(): void {
    const dt = Math.min(clock.getDelta(), 0.05);
    time += dt;
    lastTickAt = performance.now();
    updatePhase(dt);
    updateJoints(dt);
    if (aura) {
      aura.update(dt, time, camera);      // before updateLook: it feeds the bloom
      if (aura.closed) {                  // faded out after the session ended
        rig.remove(aura.group);
        aura.dispose();
        aura = null;
      }
    }
    updateLook();
    updateMarkers(dt);
    if (post) post.composer.render();
    else renderer.render(scene, camera);
  }
  function tick(): void {
    if (disposed) return;
    raf = requestAnimationFrame(tick);
    step();
    updateRaycast();      // after render: world matrices are fresh
  }
  // background tabs get no animation frames — keep the twin moving anyway
  const bgTicker = window.setInterval(() => {
    if (!disposed && performance.now() - lastTickAt > 280) step();
  }, 250);

  // ---- sizing -----------------------------------------------------------
  function resize(): void {
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (aura) aura.setPixelRatio(dpr);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    if (post) {
      post.composer.setPixelRatio(dpr);
      post.composer.setSize(w, h);
    }
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(() => resize());
  ro.observe(canvas);
  resize();
  tick();

  // ---- public interface -------------------------------------------------
  return {
    setMode(m: HoloMode): void {
      if (m === 'dormant') {
        if (phase !== 'dormant' && phase !== 'sleep') startSleep();
      } else if (m === 'awakening') {
        if (phase !== 'awaken') startAwaken();
      } else {
        // 'live': mid-awakening we let the choreography finish (it lands in
        // live and fires onAwakened); otherwise glide straight in.
        if (phase !== 'live' && phase !== 'awaken' && phase !== 'wakefast') startWakeFast();
      }
    },
    setMotors(list: HoloMotor[]): void {
      for (const m of list) {
        const marker = robot.markers.get(m.id);
        if (!marker) continue;
        marker.state = {
          ok: m.ok,
          present: m.present,
          picked: m.picked === true,
          extHover: m.hover === true,
        };
      }
      // a dead motor can't move its limb — don't show what can't act.
      // (only once the bus is known; an all-absent offline list keeps the body)
      if (opts.keepDeadParts) return;          // the kiosk: whole, always
      const anyPresent = list.some((m) => m.present);
      const deadNodes = anyPresent
        ? list.filter((m) => !m.present || !m.ok)
              .map((m) => CAL[m.id]?.node)
              .filter((n): n is string => typeof n === 'string')
        : [];
      robot.applyDeadParts(deadNodes);
    },
    setPose(deg: Record<string, number>): void {
      for (const key of Object.keys(deg)) {
        const id = Number(key);
        const c = CAL[id];
        const j = joints.get(id);
        const raw = deg[key];
        if (!c || !j || !Number.isFinite(raw)) continue;
        // wrap to (-180,180]: the seam motors' multi-turn counter can sit a
        // whole turn away from the recorded stand pose between sessions
        let d = raw - (zero?.[key] ?? c.offset);
        d -= 360 * Math.round(d / 360);
        j.target = clamp(c.sign * d * DEG, -ANGLE_CLAMP, ANGLE_CLAMP);
      }
    },
    setZero(raw: Record<string, number> | null): void {
      zero = raw ? { ...raw } : null;
    },
    resetYaw(): void {
      yawResetting = true;
    },
    setView(v: 'front' | 'top' | 'side'): void {
      view = v;
    },
    probe(nodeName: string): { pos: number[]; yDir: number[] } | null {
      const node = robot.nodes[nodeName];
      if (!node) return null;
      scene.updateMatrixWorld(true);
      const p = new THREE.Vector3();
      node.getWorldPosition(p);
      const q = new THREE.Quaternion();
      node.getWorldQuaternion(q);
      const y = new THREE.Vector3(0, 1, 0).applyQuaternion(q);
      const r = (v: THREE.Vector3) => [v.x, v.y, v.z].map((n) => Math.round(n * 100) / 100);
      return { pos: r(p), yDir: r(y) };
    },
    setPickable(on: boolean): void {
      pickable = on;
      canvas.style.cursor = pickable && hoverId !== null ? 'pointer' : '';
    },
    onMotorPick(cb: (id: number) => void): void { pickCbs.push(cb); },
    onMotorHover(cb: (id: number | null) => void): void { hoverCbs.push(cb); },
    setHighlight(id: number | null): void { highlightId = id; },
    setVoice(v: HoloVoice | null): void {
      // No session, no aura: it hangs on `rig` (not `spinGroup`) because it is
      // his voice, not his body — it must not turntable-spin while dormant.
      if (v === null || v.phase === 'off') {
        if (aura) aura.close();      // fades out, then step() reaps it
        return;
      }
      if (!aura) {
        aura = createAura(theme);
        aura.setPixelRatio(dpr);
        rig.add(aura.group);
      }
      aura.setVoice(v);
    },
    onAwakened(cb: () => void): void { awakenedCbs.push(cb); },
    resize,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(raf);
      window.clearInterval(bgTicker);
      ro.disconnect();
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerleave', onPointerLeave);
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('wheel', onWheel);
      canvas.style.cursor = '';
      if (aura) {
        rig.remove(aura.group);
        aura.dispose();
        aura = null;
      }
      robot.dispose();
      grid.geometry.dispose();
      gridMat.dispose();
      disposeSharedMats(mats);
      if (post) {
        post.bloom.dispose();
        post.output.dispose();
        post.renderPass.dispose();
        post.composer.dispose();
      }
      renderer.dispose();
    },
  };
}
