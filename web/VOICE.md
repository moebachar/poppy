# POPPY/DECK — voice contract

Extension of `web/CONTRACT.md` covering **Poppy Live** in the deck: launching
the realtime speech agent from the browser, the people/voiceprint surface, and
the voice-driven aura on the hologram. Same rules as CONTRACT.md — a builder
that needs something not written here picks the most conservative reading and
does NOT invent endpoints.

## Topology

```
browser (web/ui)
   │  REST + /ws (same origin :8000)
web/server.py ── imports ──> web/voicelink.py     supervisor + people REST
   │                              │
   │  stdin/stdout line protocol  │  stdin/stdout "@" line protocol
   ▼                              ▼
scripts/motion/10_motion_server.py     perception/live_agent.py --deck
   │  pypot, SOLE owner of the serial bus       │  OpenAI realtime websocket
   ▼                                            │  laptop mic + speakers
 robot  <───────── moves routed through the bridge ─┘
```

**The one hard rule:** `live_agent.py --deck` NEVER spawns a motion server and
never opens the serial port. Every body move it wants goes up the pipe to the
bridge, which forwards it to the motion server it already owns. This is what
lets the hologram stay live while Poppy talks.

The agent runs on the machine with the mic and speakers — the same laptop as
the bridge. Audio never crosses the network; only levels and text do.

---

## 1. `perception/live_agent.py --deck` (track A)

New flag `--deck`. Everything without it is unchanged: the terminal use
(`python perception\live_agent.py`) must keep working exactly as today.

`--deck` changes three things and nothing else:

1. **Motion goes over the pipe.** `Motion` is replaced by `DeckMotion` with the
   same blocking API (`start`, `alive`, `ready`, `play`, `stop_moving`, `look`,
   `close`). No subprocess, no `--port`/`--pi*` use, no `serial` import path.
2. **stdout gains `@` lines** (below). Existing human prints stay — the bridge
   forwards any non-`@` line to the deck's event log verbatim, which is useful.
   Never print a line starting with `@` for anything else.
3. **stdin gains `@` commands** (below), read by the same reader that already
   exists for nothing else today (add one). `--ptt` under `--deck` is driven by
   `@ptt down|up` instead of the `keyboard` package.

### 1.1 stdout — child → bridge

One JSON object per line, `@<verb> <json>`. Verbs:

| line | when | payload |
|---|---|---|
| `@ready {...}` | session.updated, once per connect | `{"voice","model","vad","identify":bool,"people":int,"moves":int,"duplex":"full"\|"gate"\|"ptt"}` |
| `@phase {"p":"..."}` | on change only | `p` ∈ `connecting` `listening` `hearing` `thinking` `speaking` |
| `@lvl {...}` | 30 Hz while connected | `{"o":0.00-1.00,"i":0.00-1.00,"b":[8 floats 0-1]}` — see §1.3 |
| `@say {"text":"..."}` | Poppy's transcript is done | what he said |
| `@heard {...}` | user transcript completed | `{"text":"...","who":null\|"Mohamed","score":0.0,"verdict":"confident\|tentative\|unknown\|nobody-enrolled"}` |
| `@tool {...}` | a tool runs | `{"name":"play_wave","phase":"start"\|"done"\|"fail","detail":"..."}` |
| `@person {...}` | enroll / remember succeeded | `{"name":"Karim","event":"enrolled"\|"noted","detail":"..."}` |
| `@prof {...}` | each completed turn | `{"resp":0.62,"n":14}` rolling mean of first-sound latency |
| `@err {"m":"..."}` | anything the operator should see | short sentence |
| `@move <token> <name>` | a move tool wants the body | RPC — the bridge answers on stdin with the same token (§1.2) |
| `@stopmove` | `stop_moving` tool | fire and forget |
| `@look` | the wake-up glance | fire and forget |
| `@bye` | clean shutdown, last line | `{}` |

`@bye` means a CLEAN shutdown and nothing else. A crash never prints it: the
agent prints `@err` with the reason, repeats that reason as its last plain
line, and exits. The bridge reads an exit without `@bye` as a death and turns
it into phase `error` carrying the sentence (§2.1) — a session that just goes
dark with `error: null` is the bug this rule exists to prevent.

`@phase` derivation:
- `connecting` — from launch until the first `session.updated`.
- `hearing` — between `input_audio_buffer.speech_started` and `speech_stopped`
  (or, in PTT, while the button is held).
- `thinking` — from speech stop / commit until the first output audio delta.
- `speaking` — while the output buffer has audio (falls back to `listening`
  ~250 ms after the last sample).
- `listening` — otherwise.

### 1.2 stdin — bridge → child

| line | meaning |
|---|---|
| `@move_result <token> ok` | that move finished; the `play` waiting on `<token>` returns success |
| `@move_result <token> fail <reason...>` | that move did not happen |
| `@interrupt` | shut up now: flush playback, truncate the item, cancel the response |
| `@nudge` | say something unprompted right now (same instruction text as `idle_task`) |
| `@enroll <name>` | run `tool_enroll(name)` on the voice that spoke last; reply with `@person` or `@err` |
| `@ptt down` / `@ptt up` | PTT from the browser (only meaningful with `--ptt`) |
| `@quit` | close the session, run the end-of-session fact mining, print `@bye`, exit |

**The move token.** `<token>` is a decimal integer, monotonically increasing
per agent process, starting at 1. The bridge echoes back verbatim the token it
was given and never invents one. The child IGNORES any `@move_result` whose
token is not the one it is currently waiting on — that is the whole point: a
late answer to a request that already timed out must never be mistaken for the
answer to the current one. An `@move` whose first word is not a decimal token
is therefore *unanswerable*: the bridge logs it to the event log and stays
silent rather than guess (a wrong token would resolve somebody else's move). An
`@move <token>` with no name after it does get answered — `fail no move name`.

`@quit` releases the move the deck still owes before anything else: the pending
`play` returns a `FAILED` string at once, so the shutdown is not held for the
90 s timeout and the fact mining actually runs. The agent keeps reading stdin
to EOF afterwards (answering nothing) so a late `@move_result` never lands in
a pipe with no reader. The bridge losing the pipe (EOF at the child) is the
same shutdown, for the same reason.

Unknown `@` lines are ignored silently. Non-`@` stdin lines are ignored.

### 1.3 Levels — the aura's fuel

Computed from the PCM actually handed to the output device (so it is what the
room hears) and from the mic blocks going upstream. Do the FFT on a worker
thread, never inside the sounddevice callback.

- `o` — outgoing envelope. RMS of the last ~32 ms of played audio, normalised
  against int16 full scale, then `min(1, rms / 0.18)` so ordinary speech peaks
  near 0.8. Fast attack, slow release is applied in the BROWSER, not here — send
  the raw envelope.
- `i` — mic envelope, same scaling. Report it even while gated/PTT-closed so the
  aura can react to the person in the room.
- `b` — 8 bands from a 1024-sample rfft of the outgoing audio (Hann window,
  24 kHz), log-spaced edges `[80, 180, 360, 700, 1300, 2400, 4200, 7000, 11000]`
  Hz, each band's mean magnitude normalised the same way and clipped to 1.

Emit at 30 Hz whenever the websocket is up, zeros included. Round to 3 decimals
so the lines stay small.

### 1.4 `DeckMotion`

```
play(name, seconds) -> str   # blocking; takes the next token, prints
                             # "@move <token> <name>", waits for
                             # "@move_result <token> ...", 90 s hard timeout.
                             # Answers carrying any other token are dropped.
                             # Returns EXACTLY the same shaped strings as
                             # Motion.play ("Move 'x' performed; ..." /
                             # "FAILED: ...") so the model's prompt still holds.
stop_moving() -> str         # prints "@stopmove", returns the stock sentence
look()                       # prints "@look"
alive()/ready                # True whenever the pipe is open — the bridge is
                             # the authority on whether the body can move, and
                             # says so in the failure reason.
close()                      # shutdown: the waiting play returns FAILED now,
                             # and the next one fails instead of waiting 90 s.
```

The bridge always answers, including "fail robot is off" — so `play` never
hangs waiting for hardware that is not there. One move at a time: a token is
handed out and retired under the same lock, so exactly one request is ever
outstanding.

**The 90 s is a backstop, not a budget.** The bridge's own worst case for one
`@move` is `HOLD_TIMEOUT` (25 s, standing a released body back up) plus
`PLAY_TIMEOUT` (60 s, the move and the travel back to the stance) plus its poll
overshoot — about 85.5 s, and it answers on every path in between: the body
going off mid-move, the motion server dying without a completion line, an
overheating body it refuses to re-stiffen. `HOLD_TIMEOUT` and `PLAY_TIMEOUT`
live in `web/voicelink.py`, the 90 s ceiling is `DeckMotion.TIMEOUT` in
`perception/live_agent.py`, and each of the three carries a comment pointing at
the other two — moving one alone is how `play` starts timing out on moves that
were about to succeed. 90 s firing at all means the DECK went away, not the
robot.

---

## 2. `web/voicelink.py` (track B)

New module, imported by `server.py`. Owns: the `live_agent` child process, the
`@` protocol, the people/voiceprint REST surface, and the guided enrolment.

`server.py` wires it once at import time:

```python
import voicelink
voicelink.wire(broadcast=broadcast, send_motion=send_line,
               power=lambda: STATE["power"], python=venv_python, root=ROOT)
```

and calls `voicelink.on_motion_event(word, line)` from `handle_event`,
`voicelink.on_motion_exit()` from `child_exited`, and `voicelink.stop()` from
the lifespan shutdown. Beyond the new routes delegating into the module, the
only other change to `server.py` is the motion-bus claim below.

**voicelink is the single arbiter of the motion bus.** `STATE["power"]` only
becomes `playing` when `PLAY_START` comes *back* from the motion server — up to
a couple of seconds later — so "is the robot free?" cannot be answered by
reading it. Both plays go through one claim/release in voicelink instead:
`POST /api/play` calls `claim_motion(name)` before `send_line` (409 "a move is
already playing" when it comes back None; `release_motion(claim)` if the line
never went out), and the `@move` RPC claims the same bus for the whole stand-up
plus play. Every `PLAY_DONE`/`PLAY_FAIL` therefore belongs to exactly one
request. `/api/play` stays fire-and-forget for the UI: its claim is released by
the completion line, by `on_motion_exit()`, or by its own deadline.

voicelink acquires **no** server lock — not `STATE_LOCK`, not `POWER_LOCK`: the
callables it is handed read `STATE["power"]` unlocked, write the motion server's
stdin under `STDIN_LOCK` alone, and fan the websocket out. Server does call the
other way while holding its own locks (`set_phase` → `full_state()` →
`voice_state()` runs inside `STATE_LOCK`, and inside `POWER_LOCK` on a power
cycle), so the order is always server-lock → voicelink-lock and never the
reverse. That one direction is what keeps the two from inverting, and it is a
property to preserve, not a coincidence — a voicelink function that reached for
a server lock would close the cycle.

### 2.1 VoiceState

```json
{
  "on": false,
  "phase": "off|starting|connecting|listening|hearing|thinking|speaking|error",
  "error": null,
  "started": null,
  "voice": "cedar",
  "model": "gpt-realtime-2.1",
  "vad": "semantic",
  "fx": 0.25,
  "nudge": 0,
  "duplex": "full",
  "identify": true,
  "input": null,
  "output": null,
  "people": 3,
  "moves": 4,
  "resp": null,
  "enroll": null
}
```

- `phase` is `off` when the child is not running, `starting` from spawn until
  the first `@ready`, then whatever the child last reported, `error` if it died
  badly (`error` carries the sentence).
- `voice`/`model`/`vad`/`fx`/`nudge`/`duplex`/`identify`/`input`/`output` are the
  **preferences**, persisted to `web/voice_prefs.json` and echoed back whether or
  not a session is running. They only take effect at the next start.
- `resp` — `{"avg":0.62,"n":14}` from `@prof`, or null.
- `enroll` — null, or the guided-enrolment session (§2.5).

### 2.2 Chat rows

The bridge keeps the last **80** rows in memory (cleared when a session starts)
so a browser reload does not lose the conversation.

```json
{"n": 41, "ts": "14:02:11", "kind": "say|heard|tool|note",
 "who": "poppy|Mohamed|null", "text": "Bof. Le bureau est trop haut.",
 "score": null, "verdict": null, "ok": null}
```

- `kind:"say"` — Poppy. `who:"poppy"`.
- `kind:"heard"` — a person. `who` is the matched name or null for a stranger;
  `score`/`verdict` from `@heard`.
- `kind:"tool"` — `text` is the tool name, `ok` true/false/null (running),
  `verdict` unused.
- `kind:"note"` — `@person` events and bridge notes ("session ended, 2 new
  memories"). `who` is the subject when there is one.

### 2.3 REST — voice

- `GET  /api/voice` → VoiceState
- `POST /api/voice {"on":true}` — persist any preference keys also present in
  the body (`voice`,`model`,`vad`,`fx`,`nudge`,`duplex`,`identify`,`input`,
  `output`), then spawn. 409 if already on. 503 if `OPENAI_API_KEY` is missing
  (say so in the sentence — that is a real failure mode).
  `{"on":false}` — send `@interrupt`, then `@quit`, wait ≤ 45 s for `@bye`,
  then terminate. If the child printed that it is mining the transcript, wait
  20 s longer: `identity.extract_facts` sits on a 25 s `urlopen`, and killing it
  there loses the new memories while the deck reports a clean "session ended".
  Idempotent. Preference-only writes are allowed with `on` omitted.
- `POST /api/voice/cmd {"cmd":"interrupt"|"nudge"}` — 409 when off.
- `POST /api/voice/ptt {"down":true|false}` — 409 unless `duplex=="ptt"`.
- `POST /api/voice/tag {"name":"Karim"}` — `@enroll` on the voice that spoke
  last. 409 when off.
- `GET  /api/voice/chat` → `{"rows":[…]}`

Validation: `voice` ∈ the 10 realtime voices; `model` ∈ `gpt-realtime-2.1`,
`gpt-realtime-2.1-mini`; `vad` ∈ `semantic`,`server`; `fx` 0–1; `nudge` 0–600;
`duplex` ∈ `full`,`gate`,`ptt`; `input`/`output` null or an int device index.

### 2.4 REST — people

Reads `perception/identity.py` fresh on every request (the running agent holds
its own copy; deck edits land in the agent at its next session — say so in the
UI only if it is ever confusing, do not try to sync).

- `GET  /api/people` →
  ```json
  {"people":[{"name":"Mohamed","slug":"mohamed","prints":8,"adaptive":6,
              "encounters":7,"created":"…","last_seen":"2026-08-21 10:53",
              "facts":[{"t":"2026-08-21","text":"…"}]}],
   "model":"cached|missing","voice_on":false}
  ```
  Sorted by `last_seen` descending.
- `POST /api/people/fact {"name":"Karim","fact":"…"}` — 300 chars max.
- `POST /api/people/fact/delete {"name":"Karim","index":2}`
- `POST /api/people/rename {"from":"Sara 2","to":"Sara B"}` — rewrites the file
  under the new slug; 409 if the target slug exists **on disk** (an in-memory
  roster misses a person whose file failed to parse, and a rename that
  overwrites a merely unreadable person is a deletion).
- `POST /api/people/forget {"name":"Karim"}` — deletes the person file. The UI
  demands a typed confirmation, the API does not.

All of these broadcast `{"t":"people"}` so open decks refresh.

Every write here is read-modify-write on a file the running agent may also be
writing, so all four (and the enrolment's own save) are serialised behind one
lock in voicelink. `index` in `fact/delete` counts the facts `GET /api/people`
actually sent — entries the roster drops are dropped by both, or the deck
deletes the fact below the one it meant.

### 2.5 Guided enrolment

Server-side, using the laptop mic — the same channel Poppy will hear the person
on, which is the whole point (see the note in `identity.py`). Requires the voice
session to be **off** (409 otherwise) because both want the mic.

- `POST /api/people/enroll/start {"name":"Karim"}` → VoiceState with
  `enroll = {"name":"Karim","step":0,"of":4,"status":"loading|ready",
             "prompt":"Tell Poppy what you did this morning — just talk.",
             "note":null,"clips":0}`
  `status:"loading"` while torch/speechbrain come up (seconds, first run
  downloads ~80 MB); the module flips it to `ready` and broadcasts.
- `POST /api/people/enroll/record` → records 8 s (`status:"recording"` while it
  runs, broadcast at the start), embeds, advances `step`, sets `note` to a plain
  sentence when the clip was weak ("that was almost silence — do it again" /
  "only 1.2 s of actual speech in there"). A weak clip does NOT advance the
  step. While recording, `{"t":"lvl"}` messages carry the mic envelope in `i`
  so the aura and the meter react.
- `POST /api/people/enroll/finish` → enrols the collected clips, sets
  `enroll = {"status":"done","note":"saved — self-consistency 0.41..0.68"}`,
  broadcasts `{"t":"people"}`. Refuses with 409 under 2 clips. Idempotent: a
  second SAVE on a finished enrolment returns the same state and writes
  nothing, and a `record` arriving during the write is refused — enrolling the
  same clips twice drags the centroid onto the duplicates and evicts the
  genuinely diverse older prints, with no undo.
- `POST /api/people/enroll/cancel` → `enroll = null`, nothing written.

Prompts come from `identity.ENROLL_PROMPTS` verbatim.

A clip is 8 s of blocking mic capture, so it lands long after the request that
asked for it. The session carries a generation that a `start` or a `cancel`
bumps, and a clip whose generation no longer matches is **discarded** — one
cancelled clip written into the next person's voiceprint is Poppy calling Alice
"Bob" permanently. For the same reason no failure may leave `status` on
`recording`: an unreachable microphone answers 503 and puts the flow back on
`ready` with the reason in `note`. An enrolment that sat in `loading` or
`recording` far past its own budget stops counting as owner of the mic, so a
worker that died taking torch with it cannot block the voice session for ever.

### 2.6 REST — audio devices & sessions

- `GET /api/audio/devices` →
  ```json
  {"input":[{"i":1,"name":"Microphone (Realtek)"}],
   "output":[{"i":3,"name":"Speakers"}],
   "default":{"input":1,"output":3}}
  ```
  Never opens a stream; `sounddevice.query_devices()` only. On failure return
  empty lists rather than an error.
- `GET /api/sessions` → `[{"file":"20260821-104900.jsonl","when":"2026-08-21 10:49",
  "lines":42,"who":["Mohamed","poppy"]}]`, newest first, 30 max.
- `GET /api/sessions/{file}` → `{"rows":[{"t":"…","who":"…","text":"…"}]}`,
  400 unless `file` matches `^[0-9]{8}-[0-9]{6}\.jsonl$`.

### 2.7 WebSocket additions

- `{"t":"voice","voice":VoiceState}` — every phase / preference / enrol change.
- `{"t":"lvl","o":0.41,"i":0.02,"b":[…8…]}` — 30 Hz, forwarded straight through.
  Fire-and-forget: never queue, never buffer, drop if a client is slow.
- `{"t":"chat","row":ChatRow}` — one per new row.
- `{"t":"people"}` — the roster changed; clients re-`GET /api/people`.

`lvl` is the ONE message a client may miss, and "drop if a client is slow" needs
teeth: a raised exception is not the signal. A suspended laptop leaves its socket
open and zero-windowed, `send_text` never returns and never raises, and one task
per client per message piles up 30 times a second until TCP gives up (two hours,
on Windows). So the fan-out keeps a per-client in-flight flag for `lvl` and skips
a client that still owes the previous one — the next level is 33 ms away.
`state`/`event`/`chat`/`voice` are never dropped, and a client whose send does
raise is discarded *and* its socket closed.

`o`, `i` and the 8 `b` values are validated before they leave the bridge:
non-numbers, NaN and out-of-range clamp to 0..1, and `b` is replaced wholesale
unless it is exactly 8 long. A short `b` reaches the aura's shader as an
undefined uniform and collapses its shell; a malformed high-frequency line must
never storm the event log either, so parse failures are counted and reported at
most once every few seconds.

`FullState` gains `"voice": VoiceState` so a reload restores everything in one
round trip, and that snapshot is taken **last** in `full_state()` — after the
move files are read off disk. Taken any earlier it is already tens of
milliseconds stale by the time it goes out, and overwrites the newer
`{"t":"voice"}` the deck received while the bridge was reading. The
high-frequency `voice`/`lvl` messages exist so phase changes do not re-broadcast
all 13 motors.

---

## 3. Hologram — the voice aura (track C)

`web/ui/src/holo/` stays framework-free and imports nothing from outside itself.
One new file `holo/aura.ts`; `holo/index.ts` gains one method and one hook.

```ts
export type VoicePhase =
  'off' | 'connecting' | 'listening' | 'hearing' | 'thinking' | 'speaking';

export interface HoloVoice {
  phase: VoicePhase;
  out: number;        // 0..1 raw outgoing envelope   (smoothing lives here)
  in: number;         // 0..1 raw mic envelope
  bands: number[];    // 8 values 0..1, low -> high
}

// on the Holo interface:
setVoice(v: HoloVoice | null): void;   // null = no session, aura absent
```

Called at up to 30 Hz from `HoloStage`; it must be a cheap setter that only
stores the values — all smoothing and animation happen in the render loop.

### 3.1 What it has to feel like

A living field of light around the body that **breathes with his voice**: it
blooms and frays outward when he speaks, draws inward and settles when he is
listening, and drifts in slow thought between the two. Not a progress bar, not
a ring of equaliser sticks — an *entity*. Every parameter below is a starting
point to be tuned by eye; the target is "beautiful", not "spec-compliant".

### 3.2 Construction

Attach one `THREE.Group` to `rig` (NOT to `spinGroup` — the aura is his voice,
not his body, so it does not turntable-spin with the dormant robot), centred at
`(0, 0.32, 0)`. Everything additive, `depthWrite:false`, so the body stays
readable through it.

1. **Corona** — a camera-facing `PlaneGeometry(1.9, 2.2)`, billboarded every
   frame, `ShaderMaterial`, additive, `depthTest:false`, `renderOrder -1`.
   In quad space (`-1..1`) it draws a gaussian ring at radius `uHaloR` with
   thickness `uHaloW`, whose radius per angle is pushed around by three
   octaves of simplex noise weighted by the band groups (`b[0..1]` → slow
   swells, `b[2..4]` → mid ripples, `b[5..7]` → fine fray). Colour is a
   vertical ramp `#1E5C99 → #4FC3FF → #CFF3FF`; a whisper of haze fills inside
   the ring so the body stands in light rather than in a hole.
   `uHaloR = (0.40 + 0.10·drive)`, `uHaloW = 0.070 + 0.090·drive`,
   wobble `0.030 + 0.090·drive`; peak alpha ≈ 0.24.

   **This started as a displaced sphere and must not go back to being one.**
   A lit closed surface reads as a container the robot is sitting inside — the
   eye locks onto the silhouette, and a fresnel is brightest exactly there.
   Tried it double-sided, back-face-only, with the rim killed before the edge,
   and with the outline torn open by the noise: soap bubble every time. A halo
   drawn in the plane of the screen cannot enclose anything, because its
   middle is transparent by construction. The displacement that used to bend
   the shell now bends the halo's radius, which says the same thing about his
   voice and says it far more legibly.
2. **Fuzz** — `THREE.Points`, ~2000 points on a Fibonacci sphere around the
   body (radii `(0.42, 0.52, 0.42)`), swimming slowly across it, radius
   jittered by the band each point is mapped to (bass at the waist, air around
   the head), additive, ~2–4 px. This is the literal "fuzz", and it carries
   its own alpha (`uFuzz`) rather than the corona's — it is the only part of
   the field with real depth, so it must not dim when the corona does.
3. **Rings** — a pool of 6 thin rings, spawned on **syllable onsets** (`out`
   rising through ~0.18 with a 120 ms refractory), expanding 0.20 → 0.60 over
   ~1.3 s and faded out by 0.58. Spawned low and tilted hard (±0.45 rad): the
   camera sits almost level with the chest, so an untilted ring there projects
   to a straight line and reads as a stray scanline. While `hearing` they run
   the other way — spawn wide, collapse inward.

Sizes are set against **the deck's stage pane, not the harness**: that pane is
roughly half the window, so the horizontal half-extent at the subject plane is
about 0.78 stage units against 0.70 vertical. Anything that looks contained in
the full-width harness can still clip in the deck.
4. **Bloom coupling** — expose the smoothed level so `index.ts` can add
   `0.25 * out` to `bloom.strength`. The screen genuinely brightens when he
   talks; that is the "shining" the brief asks for.

### 3.3 Phase behaviour

| phase | the field does |
|---|---|
| `speaking` | full effect: bloom, frayed shell, rings outward, brightest gradient |
| `hearing` | contracts to ~0.85, dims to a deep blue, rings collapse inward, driven by `in` instead of `out` |
| `thinking` | small amplitude, a slow bright band orbiting the shell once every ~2.5 s |
| `listening` | idle breath — a ±3 % sine at ~0.16 Hz, alpha ~0.1, no rings |
| `connecting` | same as listening but the alpha itself pulses |
| `off`/null | fully removed from the scene; no per-frame cost |

Smoothing in the render loop: `out`/`in` attack ≈ 25 ms, release ≈ 180 ms;
bands attack 30 ms, release 220 ms. Phase changes cross-fade over ~350 ms —
nothing may snap.

The aura renders in **every** hologram mode, including `dormant`: voice mode
does not require the robot's power to be on.

`dispose()` must free the geometries, materials and the points buffer.

---

## 4. Frontend (track D)

Deps unchanged — react, zustand, three (holo only), the two fontsources.
Nothing new. `npm run build` clean is the definition of done.

### 4.1 Level bus — never through React

30 Hz store writes would re-render the tree. `src/audioBus.ts`:

```ts
export interface Levels { out: number; in: number; bands: number[]; at: number }
export function pushLevels(o: number, i: number, b: number[]): void
export function readLevels(): Levels          // latest, decayed if stale
export function subscribeLevels(cb: (l: Levels) => void): () => void
```

`api.ts` routes `{"t":"lvl"}` straight into `pushLevels` — it never touches the
store. `HoloStage` subscribes and forwards into `holo.setVoice(...)`; the panel
meter reads it from its own `requestAnimationFrame`.

### 4.2 Layout

The side column (`grid-column: 2`) becomes **tabbed**. One row of hairline tabs
at the top: `SEQUENCES` · `VOICE` · `PEOPLE`. `TEACH / RECORD` and `EVENT LOG`
stay pinned below, unchanged — they are always reachable.

Tabs are 10px mono, uppercase, `letter-spacing: .14em`, `--ink-dim`, the active
one `--ink` with a 1px `--accent` underline. When a voice session is live and
the VOICE tab is not selected, its label carries a small `--accent` dot; when
Poppy is speaking the dot pulses. Same rule as everything else: no rounding, no
gradient, no emoji, no icons beyond the existing hand-drawn SVG set (one new
path is allowed for the voice key — a three-bar level glyph, nothing cute).

The command deck gains a **`VOICE`** key next to `POWER`: it toggles the
session and lights its bottom edge `--accent` when live. It also selects the
VOICE tab on the way on. It is enabled with the robot powered **off** — the
agent does not need the body.

### 4.3 VOICE tab

```
┌ status strip ────────────────────────────────────────────┐
│ ● SPEAKING   cedar · gpt-realtime-2.1 · full   RESP 0.62s│
├ transcript (fills, newest at the bottom, auto-scrolls) ──┤
│ 14:02:04  MOHAMED       salut, ça va ?                   │
│ 14:02:05  POPPY         Bof. Ce bureau est trop haut.    │
│ 14:02:06  ▸ PLAY_WAVE   ok                               │
│ 14:02:20  ?             (unknown voice)  0.21            │
├ meter ───────────────────────────────────────────────────┤
│ IN  ▁▂▅▇▅▂▁            OUT ▁▃▆█▆▃▁                       │
├ keys ────────────────────────────────────────────────────┤
│ [START VOICE] [INTERRUPT] [NUDGE] [TAG VOICE…] [CONFIG]  │
└──────────────────────────────────────────────────────────┘
```

- Rows: `heard` shows the speaker name in `--ink` (`?` in `--ink-dim` for a
  stranger) and the match score in `--ink-dim`, `tentative` in `--warn`;
  `say` shows `POPPY` in `--accent`; `tool` shows `▸ NAME` with `ok` in
  `--ok` / the reason in `--fault`; `note` is `--ink-dim` italic-free.
- The meter is two 7-segment bar strips fed from `audioBus`, rAF-driven.
- `TAG VOICE…` opens a one-field inline input (the name), posts
  `/api/voice/tag` — this is how you enrol whoever is talking without
  interrupting the conversation.
- `CONFIG` expands an inline block (no modal, no drawer): voice (a row of 10
  selectable names), model, VAD, duplex (`FULL` / `GATE` / `PTT`), robot-fx
  slider 0–1, nudge seconds stepper, and the mic/speaker device pickers from
  `/api/audio/devices`. Changing anything while a session is live shows the
  one allowed sentence: `TAKES EFFECT AT THE NEXT SESSION`.
- With `duplex == "ptt"` and a session live, a wide `HOLD TO TALK` key appears
  above the transcript; pointer-down/up and the `V` key both drive
  `/api/voice/ptt`.

### 4.4 PEOPLE tab

```
┌──────────────────────────────────────────────────────────┐
│ MOHAMED          8+6 PRINTS   7 FACTS   21/08 10:53   ×  │
│   is a PhD student at CESI LINEACT                    ×  │
│   defends in October                                  ×  │
│   [+ FACT ____________________________]                  │
├──────────────────────────────────────────────────────────┤
│ [ENROL A VOICE]                                          │
├ SESSIONS ────────────────────────────────────────────────┤
│ 21/08 10:49   42 lines   Mohamed, poppy                  │
└──────────────────────────────────────────────────────────┘
```

- `×` on a person requires typing `forget` (same pattern as move delete).
- `×` on a fact deletes it straight away — facts are cheap.
- Clicking a person's name lets you retype it (rename).
- `ENROL A VOICE` runs the guided flow inline: name field → `START` → the
  prompt sentence, an 8 s countdown, the live mic meter, `RECORD`/`REDO`,
  `1/4 … 4/4`, then `SAVE` (or `CANCEL` at any point). While it runs, the
  hologram's aura reacts to the mic — that is the point of doing it here
  instead of in a terminal.
- Sessions are read-only: clicking one expands its transcript in place.

### 4.5 Store

`state.ts` gains `voice: VoiceState | null`, `chat: ChatRow[]` (last 80),
`people: Person[]`, `sideTab: 'seq'|'voice'|'people'`, and the actions to set
them. `api.ts` gains the REST helpers and routes the four new WS messages.
`lvl` messages must NOT go through the store.

---

## 5. Non-negotiables

- Only ONE process owns the serial bus, ever. The voice agent gets its moves
  through the bridge or not at all.
- Nothing in `holo/` imports React or anything outside `holo/`.
- `web/DESIGN.md` governs anything visible: radius 0, no gradients on UI
  surfaces (the aura is inside the hologram, which is the one luminous thing
  and is explicitly exempt), no emoji, no drop shadows, labels ≤ 2 words.
- Python style matches the existing scripts: stdlib argparse, no type hints,
  short docstrings, comments that say *why*.
- All JSON read/written with `encoding="utf-8"` explicitly — the Windows
  default mangles the accents these files carry.
- `npm run build` must pass clean; `python -m py_compile` on every touched
  Python file.
