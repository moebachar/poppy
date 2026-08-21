# Poppy Torso — daily runbook

Every command below runs from a terminal on this laptop. `python` means the project's
Python: `C:\Users\mbachar\poppy\.venv\Scripts\python.exe` (VS Code terminals in this
folder usually pick it up automatically — if a command says "no module named pypot",
use the full path). The robot's port is **COM7**.

**Emergency stop, always:** pull the 12 V plug from the wall. Software stop: `Ctrl+C`
in the terminal running a script — every script releases the motors (goes soft) on exit.

## 1. Power up + health check

1. Plug the 12 V brick into the wall (green light on the injector board).
2. Plug the USB2AX into the laptop.
3. Scan (read-only, moves nothing):

   ```
   python scripts\diagnostics\scan_bus.py --port COM7
   ```

   Good = `found 12 motor(s)`, only `54 (r_elbow_y)` missing (dead, swap pending),
   temperatures under ~40 °C.

## 2. Make it stand still (from any messy position)

```
python scripts\motion\03_stand_still.py --port COM7
```

Freezes where it is, then travels slowly to the recorded `stand` pose and holds
30 min (change with `--minutes 60`). `--freeze-only` = stiffen in place, no travel.
`Ctrl+C` to release early.

## 3. Record a move by teaching (THE workflow for the move library)

```
python scripts\motion\07_record_replay.py --port COM7 record wave2 --m41 20 --m42 20 --m43 20 --m44 20
```

What happens: the robot stiffens, settles into the `stand` pose, then holds it
**rigid** — except the motors you named with `--m<ID> <stiffness>`, which go
loose and follow your hand (what you move, stays). Sculpt the move at the speed
you want it replayed; press **Enter** to stop and save. Recording is raw motor
space @ 20 Hz — what you taught is exactly what replays.

Motor ids for the `--m` flags:

| id | joint | id | joint |
|---|---|---|---|
| 41 | left shoulder swing | 51 | right shoulder swing |
| 42 | left shoulder lift | 52 | right shoulder lift |
| 43 | left upper-arm twist | 53 | right upper-arm twist |
| 44 | left elbow | 54 | right elbow (DEAD, pending swap) |
| 33 | waist turn | 34 / 35 | chest lean / tilt |
| 36 | head turn | 37 | head nod |

Stiffness guide: `0` = completely free (torque off — no hold at all, only gear
friction; the limb FALLS if you let go), `10` ≈ floppy, `20` ≈ easy to move
(default choice), `30` ≈ noticeable resistance. A loosened joint sinks under
gravity if you let go mid-air — keep a hand on raised limbs, or the sag becomes
part of the move.

Replay and library:

```
python scripts\motion\07_record_replay.py --port COM7 replay wave2
python scripts\motion\07_record_replay.py --port COM7 list
```

Replay = full-strength: freeze → travel slowly to the move's start → play →
hold 10 s → release. Ctrl+C = instant soft, always.

Library conventions (goal: 12–15 named moves):
- One short, meaningful name per move (`high_five`, `nod_yes`, `wave2`…).
- Start AND end every move at the stand pose — replays chain cleanly.
- Re-record under the same name to replace a move; git history keeps old takes.
- Recordings live in `scripts\motion\moves\recorded\` — commit after each session.

### Tell Poppy what a move MEANS (so he uses it on his own)

Each recorded move JSON may carry two extra top-level fields. The voice agent
turns them into the tool description, which is how Poppy decides when to move
without being asked:

```json
{
  "name": "wave",
  "description": "A big left-arm hello: the shoulder lifts the arm up and the elbow swings the hand side to side.",
  "when": [
    "someone walks in, or you notice a face you know",
    "someone is leaving — a goodbye",
    "punctuating a joke, or being deliberately theatrical"
  ],
  "frames": [ ... ]
}
```

- `description` — what the move physically is, in plain words.
- `when` — example situations. They are examples, NOT a whitelist: he is told
  to use the move anywhere it feels right.
- Both are optional; a move without them still works, it just gets a bare
  "your recorded move 'x'" description and he will rarely reach for it.
- The motion scripts ignore these fields entirely — only `ids`/`hz`/`frames`
  matter for playback, so adding them is safe.

Check what he sees: `python perception\live_agent.py --check`

## 3-alt. Author a move in the simulator (no hardware touched)

1. Launch CoppeliaSim — **exactly one instance**, and it must be started with this
   command (a plain double-click won't open the robot port):

   ```
   & "C:\Program Files\CoppeliaRobotics\CoppeliaSimEdu\coppeliaSim.exe" -gREMOTEAPISERVERSERVICE_19997_FALSE_TRUE "C:\Users\mbachar\poppy\vendor\poppy-torso\software\poppy_torso\vrep-scene\poppy_torso.ttt"
   ```

2. In a second terminal, start the keyframer:

   ```
   python sim\keyframer.py
   ```

3. Type commands at the `kf>` prompt:

   | command | what it does |
   |---|---|
   | `l_shoulder_x 40` | move that sim joint to 40° (any joint from the cheatsheet) |
   | `get` | print all current joint angles |
   | `capture` | save the current sim pose as the next keyframe (`capture 2.5` = 2.5 s to reach it) |
   | `list` / `undo` | show frames / delete the last one |
   | `play` | preview the whole move in the sim |
   | `rest` | all joints back to 0 |
   | `export wave2` | write `scripts\motion\moves\wave2.json` |
   | `quit` | exit (export first — nothing is auto-saved) |

   Joint names, directions and safe ranges: **`hardware/JOINT_CHEATSHEET.md`**.
   Rules: start the move from rest (frame 1 is captured there automatically),
   ideally end at rest, stay inside the cheatsheet ranges.

## 4. Execute a move on the real robot

Stand clear of the arms, then:

```
python scripts\motion\06_execute_move.py --port COM7 --move wave2
```

It stands still, travels to the move's first frame, plays the move, then holds
30 min (`--hold-minutes 5` to shorten). It clamps to joint limits, skips the dead
motor, watches temperature, and refuses moves that reach >120° from stance.
`Ctrl+C` at any time = stop and go soft.

## 5. Poses (freeze-frame, no motion file)

```
python scripts\motion\04_pose.py --port COM7 save cool_pose    # record current physical pose
python scripts\motion\04_pose.py --port COM7 goto cool_pose    # go there and hold
python scripts\motion\04_pose.py --port COM7 release           # everything soft
```

To re-record the stance that anchors all moves: sculpt the robot by hand, then
`save stand`.

## 5b. Teach Poppy who people are (voice identity)

The live agent (`perception\live_agent.py`) recognizes people by voice and
keeps per-person memories in `perception\people\` (gitignored — personal data).

```
.venv\Scripts\python.exe perception\identity.py enroll Mohamed   # talk to it for ~1 min (4 prompts)
.venv\Scripts\python.exe perception\identity.py list             # who Poppy knows + facts
.venv\Scripts\python.exe perception\identity.py test             # live "who am I?" check
.venv\Scripts\python.exe perception\identity.py forget <name>    # delete someone entirely
.venv\Scripts\python.exe perception\identity.py fact <name> "…"  # add a memory by hand
```

- Enrolling from the CLI is best, and it asks you to TALK rather than read:
  a reading voice scores badly against the voice you actually converse in.
  Strangers can also just tell Poppy their name mid-conversation — he saves
  their voice himself, from a shorter sample.
- During chat he's told who spoke, greets people he knows, and quietly calls
  remember_person for things worth keeping; on exit the whole conversation is
  mined once more for memories (facts land in `identity.py list`).
- Needs `pip install torch torchaudio speechbrain` (one-time, ~200 MB; the
  ~90 MB voice model auto-downloads to `perception\models\` on first run).
  Without them — or with `--no-id` — the agent runs voice-blind as before.
- Recognition is per-utterance and wants ≥1–2 s of speech; very short "yes/no"
  replies keep the previous speaker. Same mic for enroll + chat matters.

## 6. Shutdown

1. `Ctrl+C` any running script (motors go soft), or run the `release` command above.
2. Pull the 12 V brick from the wall.
3. Close CoppeliaSim (don't save the scene if it asks).
4. Unplug the USB2AX.

## Known quirks (this 2013 unit)

- `r_elbow_y` (motor 54) is dead — sim moves may use it; hardware skips it.
- Left-arm motors **41, 42, 44 run in multi-turn mode** (fix for the encoder-seam
  assembly problem; check with `python scripts\motion\dxl_multiturn.py --port COM7 status`).
  Record/replay (07), stand-still (03) and poses (04) handle this automatically.
  The sim-execute script (06) skips these three motors until it's updated —
  use record/replay for left-arm moves.
- If CoppeliaSim says `failed starting a remote API server on port 19997`: another
  CoppeliaSim instance is running — close ALL of them and relaunch with the command above.
