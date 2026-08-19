// Standalone harness for the hologram module (second Vite entry).
//   npx vite --open /holo-harness.html
// Keys: 1/2/3 = dormant/awakening/live · p = toggle pickable ·
//       f = toggle motor 54 ok/fault. A slow sinusoid fakes the POS stream.
import { createHolo } from './index';
import type { HoloMode, HoloMotor } from './index';
import { CAL, MOTOR_IDS } from './calibration';

const canvas = document.getElementById('stage') as HTMLCanvasElement;
const holo = createHolo(canvas);
(window as unknown as { __holo: typeof holo }).__holo = holo;   // debug probe access

// ---- state --------------------------------------------------------------
let mode: HoloMode = 'dormant';
let pickable = false;
let m54ok = false;                 // the real 54 is dead — start faulted
const picked = new Set<number>();
let hovered: number | null = null;
let lastEvent = '—';

function pushMotors(): void {
  const motors: HoloMotor[] = MOTOR_IDS.map((id) => ({
    id,
    ok: id === 54 ? m54ok : true,
    present: true,
    picked: picked.has(id),
  }));
  holo.setMotors(motors);
}

// ---- HUD ----------------------------------------------------------------
const hud = document.createElement('div');
hud.style.cssText = [
  'position:fixed', 'left:14px', 'top:12px', 'z-index:10',
  "font:11px/1.7 'IBM Plex Mono',ui-monospace,Consolas,monospace",
  'color:#5C7280', 'letter-spacing:0.08em', 'text-transform:uppercase',
  'white-space:pre', 'pointer-events:none', 'user-select:none',
].join(';');
document.body.appendChild(hud);

function drawHud(): void {
  const pickedList = picked.size > 0 ? [...picked].sort((a, b) => a - b).join(',') : '—';
  hud.innerHTML =
    `<span style="color:#C9D6DD">POPPY/DECK · HOLO HARNESS</span>\n` +
    `MODE <span style="color:#4FC3FF">${mode}</span>` +
    `   PICK <span style="color:#4FC3FF">${pickable ? 'on' : 'off'}</span>` +
    `   M54 <span style="color:${m54ok ? '#43FF9E' : '#FF4B3B'}">${m54ok ? 'ok' : 'fault'}</span>\n` +
    `HOVER ${hovered === null ? '—' : hovered}   PICKED ${pickedList}\n` +
    `EVENT ${lastEvent}\n` +
    `1 DORMANT · 2 AWAKEN · 3 LIVE · P PICKABLE · F M54`;
}

// ---- module wiring ------------------------------------------------------
holo.onAwakened(() => {
  lastEvent = 'awakened';
  drawHud();
});
holo.onMotorHover((id) => {
  hovered = id;
  drawHud();
});
holo.onMotorPick((id) => {
  if (picked.has(id)) picked.delete(id); else picked.add(id);
  lastEvent = `pick ${id}`;
  pushMotors();
  drawHud();
});

// ---- keys ---------------------------------------------------------------
window.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.repeat) return;
  switch (e.key) {
    case '1': mode = 'dormant'; holo.setMode(mode); break;
    case '2': mode = 'awakening'; holo.setMode(mode); break;
    case '3': mode = 'live'; holo.setMode(mode); break;
    case '0': {                       // freeze: neutral pose, front-facing
      mode = 'live';
      holo.setMode(mode);
      frozen = !frozen;
      lastEvent = frozen ? 'frozen neutral' : 'sweep resumed';
      break;
    }
    case 'p': case 'P': pickable = !pickable; holo.setPickable(pickable); break;
    case 'f': case 'F': m54ok = !m54ok; pushMotors(); break;
    default: return;
  }
  drawHud();
});

// ---- fake POS driver: slow sinusoid sweep of all joints, 10 Hz ----------
const AMP: Record<number, number> = {
  33: 30, 34: 12, 35: 10, 36: 35, 37: 16,
  41: 38, 42: 24, 43: 30, 44: 42,
  51: 38, 52: 24, 53: 30, 54: 0,
};
const t0 = performance.now();
let frozen = false;
window.setInterval(() => {
  const t = (performance.now() - t0) / 1000;
  const pose: Record<string, number> = {};
  MOTOR_IDS.forEach((id, i) => {
    const amp = frozen ? 0 : (AMP[id] ?? 20);
    pose[String(id)] = CAL[id].offset + amp * Math.sin(t * 0.4 + i * 0.7);
  });
  holo.setPose(pose);
}, 100);

window.addEventListener('resize', () => holo.resize());
pushMotors();
drawHud();
