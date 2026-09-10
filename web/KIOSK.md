# POPPY — the user interface (the "kiosk")

The deck (`web/server.py`, port 8000, `web/ui/index.html`) is the maker's
console: it monitors everything, teaches moves, edits the knowledge base and
configures the agent. This document specifies the OTHER interface — the one a
visitor stands in front of. It is a separate server on a separate port with
its own page, and it can do exactly four things: watch the twin, read the
conversation, and press POWER, STAND or VOICE.

```
┌──────────────────────────────────────┬──────────────────────────────┐
│                                      │  [lab logo]   Poppy          │  header
│                                      │  ● Listening                 │
│          digital twin                ├──────────────────────────────┤
│          (light stage,               │                              │
│           same hologram module,      │  chat                        │
│           light theme)               │  (Poppy / people / moves)    │
│                                      │                              │
│                                      ├──────────────────────────────┤
│                                      │  [Power]  [Stand]  [Voice]   │  controls
└──────────────────────────────────────┴──────────────────────────────┘
```

Light mode, simple, intuitive. A tablet on the lab table is the target
device: big targets, few words, nothing to configure.

As of the fair build the page speaks **French**: every visitor-facing string
(status phrases, chat labels, buttons, toasts — `src/kiosk/` plus `link.ts`)
is French. The deck stays English; it is the maker's console.

## Topology

```
browser ──http/ws──► web/kiosk.py :8080 ──http/ws──► web/server.py :8000 ──► robot, voice agent
                     (static kiosk.html,           (the deck — unchanged)
                      REST allowlist,
                      ONE upstream socket,
                      fan-out to N browsers)
```

- The kiosk never touches the serial port, the mic, the agent or any file
  under `perception/`. Everything it does, it does by asking the deck.
- The deck is unchanged by this track. Its origin rule already admits the
  kiosk: a server-side request carries no `Origin`, and "no Origin" is
  allowed (`server.own_origin`). `websockets.connect` sends none either.
- One upstream `/ws` connection per kiosk process, however many browsers are
  on it. The deck sees one client.
- If the deck is not running the kiosk still serves its page and says so
  ("Poppy's deck is not running"); it reconnects on its own, forever.

Launch, from `C:\Users\mbachar\poppy`, two terminals:

```
.venv\Scripts\python.exe web\server.py           # the deck, :8000
.venv\Scripts\python.exe web\kiosk.py            # the kiosk, :8080
```

then open `http://127.0.0.1:8080`. `--port` changes the kiosk port, `--deck`
the deck URL (default `http://127.0.0.1:8000`), `--host` the bind address
(default `127.0.0.1`; `0.0.0.0` puts it on the lab network — anyone on that
network can then power the robot and start a paid voice session).

The kiosk page is also reachable straight from the deck at
`http://127.0.0.1:8000/kiosk.html` (same bundle, no proxy) — handy on the
laptop; the separate server is for the table.

## 1. `web/kiosk.py` (track S)

FastAPI + uvicorn, like the deck. `httpx` for REST upstream, `websockets`
for the socket upstream — both already in `.venv`. No new dependency. It
imports NOTHING from `server.py`, `voicelink.py` or `admin.py` (importing
`server` would wire a second voice supervisor and a second serial detector).

```
.venv\Scripts\python.exe web\kiosk.py [--port 8080] [--deck http://127.0.0.1:8000] [--host 127.0.0.1]
```

### 1.1 REST — the allowlist

Everything under `/api/` that is not listed here answers
`404 {"error": "no such endpoint"}`. The allowlist IS the security model:
`/api/admin/*`, `/api/people/*`, `/api/sessions*`, `/api/record/*`,
`/api/moves/*`, `/api/play`, `/api/scan`, `/api/voice/cmd|ptt|tag` do not
exist on this port.

| route | method | body the kiosk accepts | forwarded as |
|---|---|---|---|
| `/api/state` | GET | — | `GET {deck}/api/state` |
| `/api/voice` | GET | — | `GET {deck}/api/voice` |
| `/api/voice/chat` | GET | — | `GET {deck}/api/voice/chat` |
| `/api/power` | POST | `{"on": true\|false}` — exactly, a bool | `POST {deck}/api/power {"on": …}` |
| `/api/cmd` | POST | `{"cmd": "hold"}` — the only value | `POST {deck}/api/cmd {"cmd":"hold"}` |
| `/api/voice` | POST | `{"on": true\|false}` — exactly, a bool | `POST {deck}/api/voice {"on": …}` |
| `/api/voice/ptt` | POST | `{"down": true\|false}` — exactly, a bool | `POST {deck}/api/voice/ptt {"down": …}` |

Rules:
- Timeouts follow the deck's own blocking calls: 10 s for a GET and for
  starting a session, 150 s for `/api/power` (power-on waits for READY, up
  to 120 s), 90 s for `/api/voice {"on":false}` (the deck answers once the
  agent has said goodbye and mined the conversation for facts — up to
  45 s + 20 s). A shorter timeout there turned a session ending normally
  into a fault toast.
- Bodies are validated HERE and re-serialised: the raw body is never
  forwarded, no extra key is forwarded, no request header is forwarded. A
  body that fails validation is `400 {"error": sentence}` and never reaches
  the deck. Body cap 4 KB (`413`), must be a JSON object (`400`).
- The deck's answer (status + JSON) is passed back as-is. A deck that cannot
  be reached is `502 {"error": "Poppy's deck is not running — start
  web/server.py"}`; a deck that times out is `504`.
- Same-origin on writes, same rule as the deck: `own_origin(headers)` is a
  copy of `server.own_origin` with the kiosk's own port as the fallback, and
  the `api_gate` middleware refuses any non-GET/HEAD/OPTIONS request that
  fails it with `403`. No token: the kiosk has no gated data.

### 1.2 WebSocket `/ws` — downstream

Origin-checked before `accept()` (close 1008), like the deck. The kiosk
sends; the browser sends nothing.

On connect the kiosk sends:

- `{"t":"deck","up":true}` then `{"t":"hello","state":<the deck's state>}`,
  or
- `{"t":"deck","up":false}` when it holds no deck state.

The hello is NOT fetched from the deck per client. The kiosk keeps the
deck's `FullState` as last seen on the upstream socket (`hello` and `state`
frames replace it, a `voice` frame updates its `voice` block), and a
client's hello is cut from that copy in the same synchronous step that adds
the client to the fan-out. Frames that arrive while the hello is being sent
are held back for that client and sent after it, in order. Asking the deck
for `GET /api/state` instead leaves a window on both sides of the snapshot —
a frame the deck sent just before it overtakes it, a frame sent just after
it is missed — and a browser opening during power-on landed on a stale
`starting` with its Power button disabled.

Then it forwards live frames from the upstream socket. `{"t":"deck","up":…}`
is the one message that does not exist on the deck. `up` means "the kiosk
holds the deck's state": it goes `true` when the upstream `hello` arrives
(and is sent ahead of that forwarded hello, so every browser resyncs), and
`false` when the upstream socket closes.

Fan-out copies the deck's rule: `lvl` is the one droppable message (a client
whose previous `lvl` is still in flight skips this one; a client still
waiting for its hello skips it too); `hello`, `state`, `pos`, `health`,
`event`, `voice`, `chat`, `deck` are never dropped. A send that raises
removes and closes that client.

### 1.3 The upstream socket

One task, started in the lifespan: `websockets.connect(f"{ws_deck}/ws")`,
forward every text frame whose `t` is in
`hello state pos health event voice lvl chat` (drop `people` — the kiosk has
no roster — and drop anything unparseable), keeping the deck-state copy of
§1.2 current on the way. On any error or close: forget the copy, mark down,
broadcast `deck up:false`, wait 1 s → 2 s → 5 s (then 5 s for ever),
reconnect. The task is cancelled cleanly on shutdown.

### 1.4 Static

- `GET /` → `web/ui/dist/kiosk.html`, `Cache-Control: no-store`.
- `GET /lab-logo.png`, `GET /lab-logo.svg` → served from `web/ui/public/`
  FIRST (so dropping the lab's logo there needs no rebuild), then `dist/`.
- `GET /{path}` → `web/ui/dist/{path}` when it is a file inside `dist`
  (resolve + `relative_to`, like the deck), else `kiosk.html` (SPA fallback).
  `index.html` and `holo-harness.html` are NOT served — they are the deck's
  entries and would only 404 their way through the allowlist; the fallback
  answers instead. The exclusion is judged on the resolved, lower-cased
  path: NTFS answers `/INDEX.HTML` and `/./index.html` with the same file.
- `dist` missing → `404 {"error": "ui not built yet (web/ui/dist is missing)"}`.

## 2. The hologram's light theme (track H)

`createHolo(canvas, opts?)` gains `opts.theme: 'dark' | 'light'`, default
`'dark'`. **The dark theme is the deck's, and the deck must not change by a
single number** — every dark constant stays byte-identical; the light theme
is a second set selected once at construction. `HoloTheme` is exported from
`holo/index.ts`.

Why a theme and not a CSS trick: the hologram is built from additive light,
and additive light over white is white. On a light stage every material
switches to `THREE.NormalBlending` and the palette flips from "glow on
black" to "ink on paper": a blue technical drawing of the robot, contour
rings and all, with the aura a soft watercolour halo that deepens in colour
when he speaks instead of brightening.

Per file:

- `materials.ts` — `export type HoloTheme = 'dark' | 'light'`;
  `PALETTES: Record<HoloTheme, Palette>` with `PALETTE = PALETTES.dark` kept
  as-is for existing imports. `makeSharedMats(theme = 'dark')`. Light:
  `NormalBlending` on all five materials; `fill 0x3d7fc4`, `edge 0x1f4e85`,
  `rim 0x2f6fb0` (BackSide — an ink outline), `accent 0x1f4e85`; the contour
  gain (`opacity * 1.1 * line` in `contourize`) becomes a parameter — 1.1
  dark, ≈3.0 light, so the rings read as drawn lines. Light palette:
  `ok 0x1fa463`, `fault 0xd64545`, `warn 0xd9822b`, `ring 0x16212b`,
  `gridCenter 0x8fb8dc`, `gridLine 0xd5dfe8`.
- `markers.ts` — `MotorMarker(id, glowTex, ringTex, theme = 'dark')`. Light:
  `NormalBlending` on the two glow sprites, the palette above, and the glow
  sprite's base opacity lowered (≈0.28 instead of 0.5 — a soft colour dot on
  paper, not a blob). The dying-neon flicker is kept: a dead motor is dead.
- `aura.ts` — `createAura(theme = 'dark')`. Light: `NormalBlending` on halo,
  fuzz and rings; ramp `low 0x1b4f8a`, `mid 0x3b8ee0`, `high 0x8fc6f5`; the
  "hot" colour the shaders mix toward on syllables becomes a uniform `uHot`
  — white for dark (unchanged), deep cobalt `0x1450b8` for light, because
  mixing toward white on a white page is mixing toward nothing; an alpha
  gain (1.0 dark, ≈1.6 light) applied to `uAlpha`, `uFuzz` and the ring
  alpha, since normal blending at the additive numbers is too faint.
- `index.ts` — `createHolo(canvas, { theme })`. Light: no `EffectComposer`
  at all (bloom on a light page is a wash — render straight with
  `renderer.render`), grid colours from the palette, and `updateLook()`
  reads its opacity ranges from a per-theme table: light `fill 0.10→0.14`,
  `edge 0.48→0.66`, `rim 0.08→0.14`, `accent 0.55→0.85`, grid `0.35·glow`.
  Dark keeps its current numbers verbatim. `clearColor` stays transparent;
  the page's CSS is the paper.
- `harness.ts` — `?theme=light` in the URL builds the light theme and paints
  the page `#F4F6F9` with dark HUD text, so the light look can be tuned
  alone: `npx vite --open "/holo-harness.html?theme=light"`.

The tuning numbers above are starting points; they are settled by eye in
the harness, and the settled values are what ships.

## 3. The page (track K)

`web/ui/kiosk.html` + `web/ui/src/kiosk/` — a second Vite entry in the
same project (`vite.config.ts` adds `kiosk` to `rollupOptions.input`). It
shares `src/holo/`, `src/audioBus.ts` and the types in `src/types.ts` with
the deck, and `src/ui/icons.tsx` for the power arc and the level bars. It
does NOT import `src/state.ts`, `src/api.ts` or any `src/styles/*.css`: the
deck's store carries teach and admin state the kiosk must not have, and its
stylesheets force the dark body.

Files:

```
web/ui/kiosk.html            <title>Poppy</title>, html background #F4F6F9, favicon-kiosk.svg
web/ui/public/favicon-kiosk.svg   the deck's mark on paper: #F4F6F9 square, #2B7FE8 strokes
web/ui/src/kiosk/main.tsx    fonts (Space Grotesk 400/500/600, Plex Mono 400/500), kiosk.css, connect(), mount
web/ui/src/kiosk/store.ts    zustand: deckUp, wsUp, power, error, playing, motors, latestPos, voice, chat, toast
web/ui/src/kiosk/link.ts     REST (getState, getChat, setPower, stand, setVoice) + reconnecting WS
web/ui/src/kiosk/KioskApp.tsx  the grid: <Stage/> left, <Header/> <Chat/> <Controls/> right
web/ui/src/kiosk/Stage.tsx   store → createHolo(canvas, {theme:'light'}), aura drive off audioBus
web/ui/src/kiosk/Header.tsx  logo slot + wordmark + status line
web/ui/src/kiosk/Chat.tsx    the conversation
web/ui/src/kiosk/Controls.tsx  the three buttons
web/ui/src/kiosk/kiosk.css   tokens, reset, layout, everything visible
```

### 3.1 Look

Tokens (in `kiosk.css`, on `:root`):

```
--bg:      #F4F6F9   the page and the stage — paper
--panel:   #FFFFFF   the right column
--rule:    #E2E8EF   hairlines
--rule-hi: #C9D4E0   hovered hairline
--ink:     #16212B
--ink-dim: #64758A
--accent:  #2B7FE8   the one accent; buttons that are ON fill with it
--accent-ink: #1C5FB8  accent text on paper (contrast)
--ok:      #1FA463
--fault:   #D64545
--warn:    #D9822B
--poppy:   #EAF3FD   Poppy's bubble
```

- Type: Space Grotesk everywhere (400 body, 500 labels, 600 the wordmark);
  IBM Plex Mono only for timestamps. Base 15px — this is read from a metre
  away.
- Radius 12px on buttons and bubbles, 0 on the layout itself. No shadows, no
  gradients, no emoji, no icon fonts. The two glyphs are the deck's own
  (`IconPower`, `IconLevel`) plus a standing-figure glyph for STAND drawn the
  same way (inline SVG path, `currentColor`).
- Grid: `grid-template-columns: 1fr 420px` (the column never under 360px),
  `100vh`, no page scroll. Under 900px wide the column goes UNDER the stage
  (`grid-template-rows: 55vh 1fr`).
- The stage is `--bg`; the column is `--panel` with a 1px `--rule` on its
  left; header and controls are separated from the chat by hairlines.
- One hint line is allowed at the bottom-left of the stage, 12px
  `--ink-dim`: "Scroll to turn him around · double-click to face front".

### 3.2 Header

```
Poppy            ← Space Grotesk 600, 26px
● Listening      ← the status line, 14px, dot coloured by state
```

- The lab's logo is NOT in the header: it sits over the stage, top-left
  (24 px in, 20 px down), 80 px tall and up to 360 px wide (64 px under the
  900 px breakpoint), `pointer-events: none` so the wheel underneath still
  orbits him. The slot is `<img src="/lab-logo.png">` (falls back to
  `/lab-logo.svg`, then to an 80×80 outlined placeholder that says LOGO in
  11px dim caps). The file at `web/ui/public/lab-logo.png` is the CESI mark
  cropped to its own edges with the white knocked out to transparency (the
  original had a 550×550 white field around a mark a third that size, which
  ate the height); a replacement should be the same: the mark, transparent
  background, no padding. The kiosk serves it without a rebuild (§1.4).
- The status line is ONE phrase, computed in this order:
  1. kiosk socket down → "Connecting…" (dim)
  2. `deckUp === false` → "Poppy's deck is not running" (fault)
  3. `power === 'error'` → "Something went wrong" (fault), the error sentence
     in 12px dim under it
  4. voice on → by phase: `starting|connecting` "Connecting voice…" (warn,
     pulsing), `listening` "Listening" (ok), `hearing` "Listening…" (accent),
     `thinking` "Thinking…" (warn), `speaking` "Speaking" (accent, pulsing),
     `error` "Voice dropped" (fault)
  5. by power: `off` "Asleep" (dim), `starting` "Waking up…" (warn, pulsing),
     `ready` "Awake" (ok), `playing` "Moving" (accent), `recording`
     "Learning a move" (warn), `released` "Relaxed" (dim), `cooling`
     "Cooling down" (warn)

### 3.3 Chat

The same rows the deck's VOICE tab shows (`ChatRow`: `say`, `heard`, `tool`,
`note`), rendered for a reader, not an operator:

- `say` → Poppy's bubble, left, `--poppy` fill, no border; a 12px "Poppy"
  cap above the first of a run.
- `heard` → the person's bubble, right, white with a `--rule` border; the
  name above (the row's `who`, or "Someone" when null). No score, no
  verdict — that is the deck's business.
- `tool` → a centred chip, 12px, dim: the move name, then " · done" when
  `ok === true`, " · failed" (fault) when `false`, nothing while `null`.
- `note` → centred 12px dim text.
- Timestamps: 11px Plex Mono `--ink-dim`, right-aligned under a bubble; a
  run of bubbles from the same speaker shows one, under the last.
- Auto-scroll sticks to the newest row only while the reader is already at
  the bottom (the deck's rule, `< 24px` from the bottom).
- Empty: one sentence centred in dim, "Press Voice and say hello." — except
  while `deckUp === false`, when the header already says what is wrong and
  the advice would be a lie; then nothing.
- The ring is 80 rows, like the bridge's; a row whose `n` goes backwards
  starts a fresh conversation (the deck's `pushChat` rule).

### 3.4 Controls

Three buttons in a row, equal width, 64px tall, icon over label:

| button | enabled | active (filled accent, white text) | label |
|---|---|---|---|
| Power | always, except during `starting` | power not `off`/`error` | "Power" — "Waking up…" while starting |
| Stand | `ready`, `released`, `cooling` | only while its request is out — it is an action, not a state (lit on `ready` it never went dark, since standing IS ready) | "Stand" |
| Voice | not while voice phase is `starting`, not while an enrolment is open on the deck | `voice.on` | "Voice" — "Linking…" while starting, "Busy" while enrolling |

- Power toggles `POST /api/power {on}`; Stand sends `POST /api/cmd
  {cmd:"hold"}`; Voice toggles `POST /api/voice {on}`. Each button is busy
  (disabled) from the click until the answer lands — the deck's broadcast
  arrives after the POST returns, and a second click in that window would
  409.
- Every button is disabled while `deckUp !== true`.
- A refused request (4xx/5xx) shows the server's sentence in a toast strip
  above the buttons, 13px on `--fault`, for 5 s. There is no event log here.
- Disabled = 40 % opacity. Hover = hairline to `--rule-hi`. Keyboard: none
  (space is not STOP here — there is no STOP; Power off is the stop) — except
  the push-to-talk key below.
- **Hold to talk.** While the live session is push-to-talk (`duplex` as it
  was when the session STARTED — latched, like the deck's VoicePanel, because
  the admin page can move the preference mid-session and the agent judges by
  what it was launched with), a full-width 60 px bar sits above the three
  buttons: "Hold to talk" / "Listening…" while held, and under it "or hold
  V" — the key from SPEECH › PTT KEY on the admin page (`VoiceState.ptt_key`,
  a `KeyboardEvent.code`, default `KeyV`; `src/pttKey.ts` is the shared
  label/match logic). Pointer-down/up with pointer capture, or the key held,
  drive `POST /api/voice/ptt {down}`; a refused press lands in the toast, a
  refused release does not; unmount and window blur both release. The key is
  ignored while a modifier other than the chosen one is held.

### 3.5 Stage

The deck's `HoloStage` pattern with the deck-only parts removed: no pick, no
hover, no view buttons, no teach. `createHolo(canvas, { theme: 'light' })`
once; push `setMode` (`starting` → awakening, `off|error` → dormant, else
live), `setPose`, `setZero` 800 ms after every arrival at `ready` (the
deck's auto-zero), and the aura exactly as `HoloStage` drives it: levels off
`audioBus`, the stale-feed timer, `setVoice(null)` on `off`.

`setMotors`: when NO motor is present the bus has simply not been surveyed
yet (the deck scans; the kiosk never does) — pass all thirteen as
`present, ok` so the twin stands whole and calm. Unknown is not dead. Once
any motor is present, pass the real list — the markers tell the truth (the
dead elbow flickers red), but the body stays WHOLE: the module is created
with `keepDeadParts: true`, so it never hides the parts below a dead motor
the way the deck does. A visitor is shown the robot, not the fault tree.

Double-click on the canvas → `resetYaw()`. The wheel already orbits.

### 3.6 Store & link

- `store.ts` — plain zustand, no persistence, no token:
  `deckUp: boolean | null` (null until the first `deck` frame), `wsUp`,
  `power`, `error`, `playing`, `motors`, `latestPos`, `voice`, `chat`,
  `toast: string | null`. `applyState` mirrors the deck's (`voice` rides in
  FullState; `off|error` clears `latestPos`). `pushChat` is the deck's rule.
- `link.ts` — `connect()` opens `ws://{host}/ws`, reconnects 1 s → 2 s →
  5 s for ever, and on `hello` applies the state and pulls
  `GET /api/voice/chat`. REST: `getState`, `getChat`, `setPower`, `stand`,
  `setVoice`, `ptt`. `lvl` goes straight to `pushLevels` on the shared
  `audioBus`, never through the store. REST helpers throw the server's
  sentence; the caller puts it in `toast`.

## 4. Non-negotiables

- The deck is not modified by this track. Not `server.py`, not `voicelink.py`,
  not `admin.py`, not any file under `src/ui/` or `src/styles/`, not
  `state.ts` / `api.ts`. If the kiosk needs something the deck does not
  offer, the kiosk goes without.
- The dark hologram is not modified: with `theme` absent or `'dark'` every
  material, every uniform and every number in `holo/` is what it was. The
  light theme is added beside it, never in place of it.
- Nothing in `holo/` imports React or anything outside `holo/`.
- The kiosk's REST surface is the allowlist in §1.1 and nothing else; the
  raw request body is never forwarded.
- All JSON read/written with `encoding="utf-8"`.
- Python style matches the existing scripts: stdlib argparse, no type hints,
  short docstrings, comments that say *why*.
- `npm run build` passes clean; `python -m py_compile web/kiosk.py` passes.
