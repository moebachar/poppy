# POPPY/DECK — interface contract

Single source of truth for the seams between the four build tracks. If a
builder needs something not written here, it picks the most conservative
reading — it does NOT invent new endpoints/fields.

## Topology
```
browser (web/ui, Vite+React+TS, three.js)
   │  REST + WebSocket, same origin :8000
web/server.py (FastAPI + uvicorn, runs on the machine that has the USB2AX)
   │  spawns as child process, line protocol over stdin/stdout
scripts/motion/10_motion_server.py --port COM7 --telemetry
   │  pypot over serial (sole owner of the bus while running)
robot
```
- Launch: `.venv\Scripts\python.exe web\server.py [--robot-port COM7] [--http-port 8000]`
  robot-port default: auto-detect via `serial.tools.list_ports` (prefer a
  device whose description contains "USB" and is not Bluetooth; on Linux
  prefer /dev/ttyACM*). server.py serves `web/ui/dist` statically at `/`.
- Only ONE process may own the serial port. server.py never opens the port
  while the child is alive; the offline scan opens it briefly and closes it.

## 1. Motion-server protocol extension (track A, edits 10_motion_server.py)
All existing behavior unchanged. New `--telemetry` flag adds **unsolicited
lines** (voice_agent ignores unknown prefixes; it is never launched with the
flag, so zero risk):
- `MOTORS {"present":[33,34,...],"expected":[33,...,54]}` — once, after scan.
- `POS {"33":-41.8,"34":21.1,...}` — 10 Hz, raw degrees (seam motors via
  present_deg, i.e. already continuous/unwrapped).
- `HEALTH {"maxtemp":45,"holding":true,"motors":{"33":{"t":34,"v":11.4},...}}`
  — every 2 s.
All prints go through one lock so lines never interleave.
Telemetry reads run in a daemon thread; pypot DxlIO calls are already
serialized internally, but keep telemetry reads OUT of the 0.08s-critical
play() frame path (thread does its own reads; drop a beat if the bus is busy).

New commands (available with or without --telemetry):
- `record_start {"41":20,"42":0}` → `RECORD_START` or `RECORD_FAIL <reason>`.
  Body: from the current holding stance, keep every motor rigid at 100% with
  fixed goals; each listed motor goes loose exactly like 07_record_replay
  do_record: pct<=0 → disable_torque; else moving_speed 150, torque_limit pct,
  and goal:=present every tick (20 Hz). Frames accumulate in 07's exact file
  format ({"t":…,"pos":{"33":…}} with ALL present motors, rounded 2dp).
  Refuses when not holding, when already recording/playing.
- `record_stop <name>` → saves to scripts/motion/moves/recorded/<name>.json
  (07 format: name/space:"raw"/hz/ids/frames), restores torque ceilings,
  re-stiffens, travels back to stance → `RECORD_SAVED <name> <frames> <secs>`.
  <name>: [a-z0-9_-]{1,32}; invalid → RECORD_FAIL. <5 frames → RECORD_FAIL.
- `record_abort` → same restore path, nothing written → `RECORD_ABORTED`.
- While recording, `status` still answers; `play`/`look`/`hold` →
  `*_FAIL … recording`; `release` aborts the recording then releases.
- Recording ticks poll the command queue non-blockingly (so record_stop is
  seen); temp watchdog stays active during recording (>=52C → abort + release
  + `TEMP_RELEASE …`).

## 2. REST API (track B, web/server.py)
JSON in/out. Errors: `{"error":"<human sentence>"}` with 4xx/5xx.
- `GET  /api/state` → FullState (below).
- `POST /api/power {"on":true|false}` — on: spawn child (`--telemetry`,
  unbuffered), wait until READY line (timeout 120s → error state, kill child).
  off: send `quit`, wait ≤8s for BYE, then terminate. Idempotent.
- `POST /api/cmd {"cmd":"hold"|"release"|"look"|"stop"}` — writes the line.
- `POST /api/play {"name":"wave"}` — refuses (409) unless state ready.
- `POST /api/record/start {"loose":{"41":20}}` (409 unless ready)
- `POST /api/record/stop {"name":"my_move"}` / `POST /api/record/abort`
- `GET  /api/moves` → `[{"name":"wave","seconds":6.2,"frames":124}, …]`
  (reads scripts/motion/moves/recorded/*.json; sorted newest first)
- `POST /api/scan` — ONLY when power off (else 409). Opens DxlIO briefly,
  per-ID ping with 2 retries over EXPECTED ids (00_read_only's map), reads
  temp+volt+pos of responders, closes port. Returns updated FullState.

## 3. WebSocket `/ws` (server → client only; client sends nothing)
- on connect: `{"t":"hello","state":FullState}`
- `{"t":"pos","pos":{"33":-41.8,…}}` (forwarded POS)
- `{"t":"health","maxtemp":45,"holding":true,"motors":{"33":{"t":34,"v":11.4},…}}`
- `{"t":"state","state":FullState}` on every phase transition
- `{"t":"event","ts":"14:02:11","line":"PLAY_DONE wave 12.1s"}` — every
  non-telemetry child line, verbatim.

## FullState
```json
{
  "power": "off|starting|ready|playing|recording|released|cooling|error",
  "port": "COM7",
  "error": null,
  "playing": null,
  "recording": null,            // or {"loose":{"41":20},"started":"14:01:59"}
  "moves": [{"name":"wave","seconds":6.2,"frames":124}],
  "motors": [ {"id":33,"name":"abs_z","model":"MX-28","present":true,
               "ok":true,"pos":-41.8,"temp":34,"volt":11.4}, … 13 entries,
              always all 13 EXPECTED ids; unseen → present:false, ok:false,
              null pos/temp/volt ]
}
```
Phase mapping from child lines: spawn→starting; READY→ready; PLAY_START→
playing; PLAY_DONE/PLAY_FAIL→ready; RECORD_START→recording; RECORD_SAVED/
RECORD_ABORTED→ready; RELEASED→released; HOLDING→ready; TEMP_RELEASE→cooling;
HOLDING (after cooling)→ready; BYE/child exit→off; FATAL→error.
EXPECTED names/ids: the map in 00_read_only.py (33…53 + 54 r_elbow_y).

## 4. Hologram module (track D, web/ui/src/holo/, NO React imports)
```ts
export type HoloMode = 'dormant' | 'awakening' | 'live';
export interface HoloMotor { id: number; ok: boolean; present: boolean;
                             picked?: boolean; hover?: boolean; }
export interface Holo {
  setMode(m: HoloMode): void;      // 'awakening' runs the choreography then fires onAwakened
  setMotors(m: HoloMotor[]): void;
  setPose(deg: Record<string, number>): void;   // RAW degrees, keys = motor ids
  setPickable(on: boolean): void;  // teach mode: markers clickable
  onMotorPick(cb: (id: number) => void): void;
  onMotorHover(cb: (id: number | null) => void): void;
  setHighlight(id: number | null): void;        // register-row hover → marker ring
  onAwakened(cb: () => void): void;
  resize(): void;
  dispose(): void;
}
export function createHolo(canvas: HTMLCanvasElement): Holo;
```
Also deliver `web/ui/holo-harness.html` + `src/holo/harness.ts` (a second Vite
entry) that mounts the module full-screen with keyboard controls: `1/2/3`
modes, `p` pickable, `f` toggles motor 54 ok/fault, and a fake POS generator
(slow sinusoid sweep of all joints) — so the hologram is testable alone via
`npx vite --open /holo-harness.html`.

### Calibration (holo/calibration.ts)
`modelAngleRad = sign * (rawDeg − offset) * π/180` applied to the named node
around its local axis. Offsets = the stand pose; **model zero == stand**:
sculpt the robot's neutral geometry as standing (arms hanging slightly out,
head level, facing +Z). Signs are best guesses, expected to be re-tuned live:
```ts
export const CAL: Record<number,{node:string;axis:'x'|'y'|'z';sign:1|-1;offset:number}> = {
  33:{node:'absZ',      axis:'y',sign: 1,offset:  18.07},
  34:{node:'bustY',     axis:'x',sign: 1,offset:  89.63},
  35:{node:'bustX',     axis:'z',sign: 1,offset:  -1.27},
  36:{node:'headZ',     axis:'y',sign: 1,offset:  -1.03},
  37:{node:'headY',     axis:'x',sign: 1,offset: -33.87},
  41:{node:'lShoulderY',axis:'x',sign: 1,offset:-108.44},
  42:{node:'lShoulderX',axis:'z',sign: 1,offset: 178.07},
  43:{node:'lArmZ',     axis:'y',sign: 1,offset:  -6.11},
  44:{node:'lElbowY',   axis:'x',sign: 1,offset:-161.19},
  51:{node:'rShoulderY',axis:'x',sign:-1,offset:  75.74},
  52:{node:'rShoulderX',axis:'z',sign:-1,offset:  20.70},
  53:{node:'rArmZ',     axis:'y',sign:-1,offset: -77.14},
  54:{node:'rElbowY',   axis:'x',sign:-1,offset: -90.0},
};
```
(54 never moves — dead — its marker just exists on the right elbow.)
Node tree: root→absZ→bustY→bustX→(chest)→headZ→headY(head);
bustX also parents both shoulder chains: lShoulderY→lShoulderX→lArmZ→lElbowY,
mirrored for r*. Clamp applied angles to ±120° for sanity.

## 5. Frontend app (track C, web/ui/src/ except holo/)
- Deps allowed: react, react-dom, zustand, three (only holo/ touches three),
  @fontsource/ibm-plex-mono, @fontsource/space-grotesk. Nothing else.
- `src/state.ts`: one zustand store mirroring FullState + `latestPos` +
  events ring (max 40) + ui state (teach picking map, hovered motor id,
  ws connected). `src/api.ts`: REST helpers + WS client with auto-reconnect
  (1s → 2s → 5s backoff, forever), feeding the store.
- App wires store → holo module via a thin `HoloStage` component (creates
  module once, pushes setPose/setMotors/setMode on store changes; power
  ready+playing+recording+released ⇒ 'live', starting ⇒ 'awakening',
  off/error ⇒ 'dormant').
- Vite: `server.proxy` `/api`→`http://127.0.0.1:8000`, `/ws`→ ws proxy; build
  outDir `dist` with the harness as extra rollup input.
- TS strict; `npm run build` must pass clean — that is each track's
  definition of done.

## Non-negotiables for every track
- Never open COM7 / run robot scripts — code only, integration is done by the
  orchestrator afterward.
- Follow web/DESIGN.md for anything visual; when in doubt, plainer wins.
- Python code style: match the existing scripts (stdlib argparse, no type
  hints, short docstrings). TS: strict, no `any` unless three.js forces it.
