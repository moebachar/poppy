# POPPY/DECK — design bible

Control console for the 2013 Poppy Torso. One screen, no navigation. The
aesthetic target is a **flight-test instrument**, not a website: think Braun
lab equipment crossed with a phosphor CRT console. Every pixel should look
drawn by an engineer who cares, none of it "generated".

## Hard NOs (anti-slop rules)
- NO color gradients on UI surfaces (the hologram's own glow is the only
  luminous thing on screen).
- NO rounded corners anywhere. Radius 0. Buttons are rectangles with 1px rules.
- NO emoji, NO icon fonts, NO stock icon sets. The only glyphs are 5 hand-drawn
  inline SVG paths (power arc, play triangle, stop square, record dot, camera).
- NO decorative text. Labels are ≤ 2 words. No explainer sentences in the UI.
- NO drop shadows, NO glassmorphism, NO cards floating on blurred blobs.

## Surface & color tokens (CSS custom properties in `tokens.css`)
```
--bg:        #0B0F13;   /* the one background. near-black, blue-leaning     */
--panel:     #0E141A;   /* register/side panels, 1 step up                  */
--rule:      #1E2A33;   /* 1px hairlines that structure the whole layout    */
--rule-hi:   #2E4152;   /* hovered/active hairline                          */
--ink:       #C9D6DD;   /* primary text                                     */
--ink-dim:   #5C7280;   /* secondary text, units, dead rows                 */
--accent:    #4FC3FF;   /* THE accent. live data, focus, link status        */
--ok:        #43FF9E;   /* motor healthy                                    */
--fault:     #FF4B3B;   /* motor dead / errors                              */
--warn:      #FFB03A;   /* temperatures 45–51°C, record-selection amber     */
--rec:       #FF3B70;   /* recording state                                  */
```
Dark only. `body { background: var(--bg) }`, never white anywhere.

## Type
- Data, numerals, labels: **IBM Plex Mono** (`@fontsource/ibm-plex-mono`,
  400 + 500). Tabular feel; sizes 11px (labels), 12px (rows), 13px (buttons).
- Wordmark + state words (READY, RECORDING…): **Space Grotesk** 500,
  uppercase, letter-spacing 0.08em.
- Labels style: 10px mono, uppercase, letter-spacing 0.14em, color --ink-dim.
  e.g. `MOTOR REGISTER`, `SEQUENCES`, `EVENT LOG`.

## Layout (desktop, min-width 1100, 100vh, no page scroll)
```
┌────────────────────────────────────────────────────────────────────┐
│ POPPY/DECK   TORSO·2013        LINK ●COM7    T.MAX 38°C   12:04:11 │ 44px
├──────────────┬───────────────────────────────────┬─────────────────┤
│ MOTOR        │                                   │ SEQUENCES       │
│ REGISTER     │        HOLOGRAM STAGE             │  wave      6.2s │
│ 13 rows      │        (three.js canvas,          │  dab       9.6s │
│              │         fills the cell)           │  secret…  12.0s │
│ id name      │                                   │ ───────────     │
│ pos° temp    │                                   │ TEACH / RECORD  │
│ bar volt     │                                   │ panel           │
├──────────────┴───────────────────────────────────┴─────────────────┤
│ [⏻ POWER]  [STAND] [RELEASE] [LOOK] [■ STOP]   │ EVENT LOG (tail) │ 92px
└────────────────────────────────────────────────────────────────────┘
```
- Grid: `44px / 1fr / 92px` rows; columns `260px / 1fr / 280px`.
- Every cell separated by 1px `--rule`. The hairlines ARE the design.
- The stage cell is pure `--bg`; the canvas is the hero and gets ~55% of the
  screen. Behind the canvas, at 4% opacity, a huge Space Grotesk "POPPY"
  watermark, clipped by the cell.

## Panels
**Top bar** — wordmark left; right side is a strip of live readouts separated
by hairlines: `LINK` dot (accent when WS open, --fault when lost), robot port,
`T.MAX` hottest motor, a per-session uptime clock. Numbers tick, mono.

**Motor register (left)** — 13 fixed rows (33,34,35,36,37,41,42,43,44,51,52,
53,54), one per motor, even when powered off. Row: id (accent), name,
live position in degrees (right-aligned, 1 decimal), temp as a number plus a
28px horizontal tick-bar (fills toward 52°C; --warn ≥45, --fault ≥50), volt.
Absent/dead motor (54): whole row --ink-dim, tag `FAULT` in --fault instead of
numbers. Rows update at telemetry rate without layout shift (tabular numbers).
Hovering a row highlights the matching motor marker in the hologram (and
vice-versa on marker hover).

**Sequences (right top)** — list of recorded moves: name, duration, frame
count, a play triangle on the row's right edge that appears on hover. During
playback the active row shows a thin progress rule crawling under it and the
triangle becomes a stop square. Rows disabled (dim) when power is off.

**Teach/record (right bottom)** — flow: press `TEACH` → picking state: hint
line `SELECT JOINTS ON HOLOGRAM` (only UI sentence allowed, 10px, dim) — user
clicks motor markers; each picked motor appears as a row `41 L.SHOULDER.Y  20%`
with `-`/`+` steppers (5% steps, 0–60, default 20). `ARM` starts the recording
(robot goes rigid, picked joints go soft): elapsed `00:07.4` counter in --rec,
`SAVE AS [name____]` input + `SAVE` / `DISCARD`. State word `RECORDING` pulses
in top bar. After save, the sequence list refreshes with the new move on top.

**Command deck (bottom left)** — 5 flat rectangular keys, 1px rules, mono
13px: `POWER` (toggles motion server; shows `SPINNING UP…` while starting),
`STAND` (hold), `RELEASE`, `LOOK`, `STOP` (always enabled while playing;
--fault text). Keys light their bottom edge (2px accent underline) when the
matching state is active. Disabled = 35% opacity, no cursor. Keyboard:
space = STOP. No tooltips.

**Event log (bottom right)** — last ~6 protocol lines (`READY 12 motors…`,
`PLAY_DONE wave 12.1s`, `TEMP_RELEASE 52C…`), newest on top, 11px mono,
timestamps HH:MM:SS in --ink-dim. This is the console's "truth channel".

## Hologram stage — the centerpiece
Stylized Poppy Torso assembled from primitives (no mesh files): pelvis mount →
spine column → chest plate (Poppy's wide chest silhouette, slightly convex) →
head (rounded-edge box + one camera eye ring) + two arms (shoulder block,
tapered upper-arm prism, forearm prism, flat paddle hand). Proportions matter
more than detail — get the torso-to-arm ratio from the photos in
hardware/photos if needed. ~1.1m of robot mapped to fit the stage with air.

**Look**: three-layer hologram —
1. fill: `MeshBasicMaterial`, color #79C4FF, additive blending, opacity 0.10;
2. structure: `EdgesGeometry` line segments, #9FD8FF, opacity 0.45;
3. rim: slightly scaled back-face shell for a fresnel-ish rim, opacity 0.06.
Subtle `UnrealBloomPass` (strength ~0.55, threshold ~0.2) sells the glow.
A 12×12 ground grid fades in only in live mode. Two scanline effects allowed:
a slow vertical shimmer band over the body (dormant), and marker pulses.
Background of the scene = transparent (CSS --bg shows through).

**Motor markers**: at each joint, a small octahedron + point glow, colored
--ok / --fault; dead motor 54 flickers irregularly (4–7Hz jitter, like a dying
neon tube) — intentional, it should feel *wrong*. In teach-picking mode,
markers are pickable: hover = white ring, picked = --warn ring + marker turns
--warn. Marker hover ↔ register row highlight is two-way.

**Modes / choreography** (the transition is the money shot — tune the easing):
- `dormant` (power off): robot parked right-of-center at 0.62 scale,
  turntable rotation, one revolution / 14s, faint shimmer. Health colors live
  (from offline scans). Feels like an exhibit in storage.
- `awakening` (power pressed → READY received): 2.1s choreography —
  (a) turntable decelerates to front-facing over 0.9s (ease-out quartic);
  (b) simultaneously translate to center + scale to 1.0 with
  `cubic-bezier(.16,1,.3,1)` and a 1.035 overshoot settling at 1.0;
  (c) grid floor + rim glow fade in the last 0.6s;
  (d) then joints blend from the neutral stand pose into live telemetry over
  0.6s (ease-in-out). Emits `onAwakened` when done → UI switches state word to
  `READY`.
- `live` (digital twin): no idle spin. Joints driven by telemetry (POS @10Hz),
  smoothed with critically-damped interpolation (~120ms). The user should be
  able to push the real robot's arm (when released) and see the ghost follow.
- power off reverses: glow dims, robot drifts back to the parked orbit.

**Kinematics**: chain per CONTRACT.md §calibration — model-space zero = the
`stand` pose; apply `sign * (raw − offset)` per joint around its axis. Signs
live in one editable table (`holo/calibration.ts`) since they'll be tuned
against the real robot.

## Motion & interaction rules
- UI transitions: 140ms, `cubic-bezier(.2,.8,.2,1)`; nothing bounces except
  the hologram's single overshoot.
- Hover states change hairline color / underline only — no background washes.
- Every dangerous action is one press, no confirm dialogs — the STOP key and
  the 12V plug are the safety story (matches lab practice).
- If the WS drops: top-bar LINK dot goes --fault, stage keeps last pose,
  a thin --fault rule appears under the top bar until reconnect.

## Poppy Live (voice mode)
The side column is tabbed — `SEQUENCES` · `VOICE` · `PEOPLE` — with TEACH and
EVENT LOG pinned below, and the command deck carries a sixth key, `VOICE`.
The hologram gains a voice-driven aura. All of it is specified in
`web/VOICE.md` §3–4; the rules on this page still govern every pixel of it,
with the single standing exception that the hologram is the one luminous
thing on screen and the aura lives inside it.

## Files this spec governs
`web/ui/src/styles/tokens.css`, `base.css`, `panels.css`, `voice.css`; all
components in `web/ui/src/ui/`; the hologram module in `web/ui/src/holo/`.
