// Standalone harness for the hologram module (second Vite entry).
//   npx vite --open /holo-harness.html
// Keys: 1/2/3 = dormant/awakening/live · p = toggle pickable ·
//       f = toggle motor 54 ok/fault · v = cycle the voice phases (a synthetic
//       syllable train drives the aura). A slow sinusoid fakes the POS stream.
// ?theme=light builds the kiosk's light theme on a paper page so it can be
// tuned alone:  npx vite --open "/holo-harness.html?theme=light"
import { createHolo } from './index';
import type { HoloMode, HoloMotor, HoloTheme, VoicePhase } from './index';
import { CAL, MOTOR_IDS } from './calibration';

// ?mode=live&voice=speaking&freeze=1 set the starting state, so a headless
// screenshot (no keyboard) can land on any look the keys would reach.
const params = new URLSearchParams(location.search);
const theme: HoloTheme = params.get('theme') === 'light' ? 'light' : 'dark';
// HUD colours: the deck's on black, the kiosk's ink on paper
const HUD = theme === 'light'
  ? { text: '#16212B', dim: '#64758A', accent: '#2B7FE8', ok: '#1FA463', fault: '#D64545', bg: '#F4F6F9' }
  : { text: '#C9D6DD', dim: '#5C7280', accent: '#4FC3FF', ok: '#43FF9E', fault: '#FF4B3B', bg: '' };
// both: the html file paints html AND body dark, and the body covers the page
if (HUD.bg) {
  document.documentElement.style.background = HUD.bg;
  document.body.style.background = HUD.bg;
}

const canvas = document.getElementById('stage') as HTMLCanvasElement;
const holo = createHolo(canvas, { theme });
(window as unknown as { __holo: typeof holo }).__holo = holo;   // debug probe access

// ---- state --------------------------------------------------------------
const MODES: HoloMode[] = ['dormant', 'awakening', 'live'];
const VOICE: VoicePhase[] = ['off', 'connecting', 'listening', 'hearing', 'thinking', 'speaking'];
const startMode = params.get('mode') as HoloMode | null;
let mode: HoloMode = startMode && MODES.includes(startMode) ? startMode : 'dormant';
let pickable = false;
let m54ok = params.get('m54') === 'ok';   // the real 54 is dead — start faulted
const picked = new Set<number>();
let hovered: number | null = null;
let lastEvent = '—';
let vIdx = Math.max(0, VOICE.indexOf(params.get('voice') as VoicePhase));

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
  `color:${HUD.dim}`, 'letter-spacing:0.08em', 'text-transform:uppercase',
  'white-space:pre', 'pointer-events:none', 'user-select:none',
].join(';');
document.body.appendChild(hud);

function drawHud(): void {
  const pickedList = picked.size > 0 ? [...picked].sort((a, b) => a - b).join(',') : '—';
  hud.innerHTML =
    `<span style="color:${HUD.text}">POPPY/DECK · HOLO HARNESS${theme === 'light' ? ' · LIGHT' : ''}</span>\n` +
    `MODE <span style="color:${HUD.accent}">${mode}</span>` +
    `   PICK <span style="color:${HUD.accent}">${pickable ? 'on' : 'off'}</span>` +
    `   M54 <span style="color:${m54ok ? HUD.ok : HUD.fault}">${m54ok ? 'ok' : 'fault'}</span>\n` +
    `HOVER ${hovered === null ? '—' : hovered}   PICKED ${pickedList}\n` +
    `VOICE <span style="color:${HUD.accent}">${VOICE[vIdx]}</span>\n` +
    `EVENT ${lastEvent}\n` +
    `1 DORMANT · 2 AWAKEN · 3 LIVE · P PICKABLE · F M54 · V VOICE`;
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
    case 'v': case 'V': vIdx = (vIdx + 1) % VOICE.length; break;
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
let frozen = params.get('freeze') === '1';
window.setInterval(() => {
  const t = (performance.now() - t0) / 1000;
  const pose: Record<string, number> = {};
  MOTOR_IDS.forEach((id, i) => {
    const amp = frozen ? 0 : (AMP[id] ?? 20);
    pose[String(id)] = CAL[id].offset + amp * Math.sin(t * 0.4 + i * 0.7);
  });
  holo.setPose(pose);
}, 100);

// ---- fake voice driver: a syllable train at 30 Hz, like @lvl -------------
const TAU = Math.PI * 2;
const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
window.setInterval(() => {
  const phase = VOICE[vIdx];
  const t = (performance.now() - t0) / 1000;
  // phrases of a few words, syllables inside them, and real gaps between
  const talking = phase === 'speaking' || phase === 'hearing';
  const phrase = Math.max(0, Math.sin(t * 0.42) - 0.15) / 0.85;
  const syl = Math.pow(Math.max(0, Math.sin(t * TAU * 1.7)), 0.55);
  const lvl = talking ? clamp01(phrase * syl * (0.6 + 0.4 * Math.sin(t * 3.1))) : 0;
  const bands = [0, 1, 2, 3, 4, 5, 6, 7].map((i) =>
    clamp01(lvl * (1 - i * 0.07) * (0.55 + 0.55 * Math.sin(t * (1.3 + i * 0.7) + i))));
  holo.setVoice({
    phase,
    out: phase === 'hearing' ? 0 : lvl,
    in: phase === 'hearing' ? lvl : 0,
    bands,
  });
}, 33);

window.addEventListener('resize', () => holo.resize());
// the harness exists to poke the module by hand — let the console do it too
(window as unknown as { HOLO: typeof holo }).HOLO = holo;
pushMotors();
if (mode !== 'dormant') holo.setMode(mode);   // ?mode= — the module starts dormant
drawHud();
