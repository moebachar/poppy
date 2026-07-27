# POPPY TORSO REVIVAL — Mission Brief for Claude Code

**Operator:** Jalaleddin (hands-on at the Fab Lab, Windows 11 laptop + WSL2, where you run)
**Your role:** Project lead, systems engineer, and remote operator. Jalaleddin is your hands and eyes on the hardware. You plan, verify, generate checklists/scripts, and — once SSH is up — execute directly on the robot's Raspberry Pi.
**Read this entire file before doing anything.**

---

## 0. TL;DR

A Poppy Torso robot (open-source humanoid torso, Inria Flowers project) has been sitting in a Fab Lab since ~2013, never powered on in years. Its head is empty — the single-board computer is missing. We are bringing it back to life in stages:

1. **Diagnose & inventory** the hardware (motors possibly damaged — unconfirmed).
2. **Bench-test the Dynamixel motor bus from the laptop** before involving any Raspberry Pi.
3. **Install a Raspberry Pi in the head**, flash software, wire everything.
4. **Get SSH access** so you can operate the robot directly.
5. **Write motion scripts** (simple poses → choreographies).
6. **Voice control** via Whisper (speech-to-text on the laptop → commands to the robot).
7. **Imitation** via MediaPipe pose estimation (laptop webcam → robot mirrors human arm/head movements).

**Golden rule:** the laptop does perception (Whisper, MediaPipe), the Pi does motor control. They talk over the network. A Pi 3/4 cannot run Whisper or MediaPipe at useful speed — do not try.

---

## 1. Known facts about THIS robot (from the Fab Lab)

- Acquired **~2013**, reportedly never moved since. Expect: dust, brittle cables, old motor firmware, possibly seized gears.
- **Head was opened: no Raspberry Pi inside** (documentation says there should be one — the official Poppy Torso head houses a Raspberry Pi 3). The Fab Lab has **spare Raspberry Pis** we can use. ⚠️ Exact models unknown — this matters a lot (see §3.2).
- Colleagues mention a missing **"switch / connecting device"** between the robot and the Pi. This is almost certainly the **USB2AX** (USB→Dynamixel TTL adapter) and/or the **SMPS2Dynamixel** (12V power injector). See §3.1 — identifying/replacing these is a Phase-1 priority.
- Rumor of **"burned motor drivers"** — unconfirmed. Note: Dynamixel servos have *integrated* drivers, so "burned driver" = a dead/damaged servo unit. Phase 2 will settle this with evidence, motor by motor.
- One robot, one operator, a Fab Lab with 3D printers, spare Pis, basic tools, and (assume) a multimeter and bench PSU — confirm in Phase 1.

**A caveat for you:** a 2013 unit may predate the current documentation (the very first Poppy units used an Odroid, not a Pi, and slightly different parts). Treat the official docs as the target state, not necessarily the as-found state. Verify everything physically before assuming.

---

## 2. Hardware dossier — what a Poppy Torso is

- **13 Dynamixel servos** on a single half-duplex TTL 3-pin daisy-chain bus:
  - Torso: `abs_z`, `bust_y`, `bust_x` — MX-28AT
  - Head: `head_z`, `head_y` — AX-12A (one may be AX-18)
  - Left arm: `l_shoulder_y`, `l_shoulder_x`, `l_arm_z`, `l_elbow_y` — MX-28AT
  - Right arm: `r_shoulder_y`, `r_shoulder_x`, `r_arm_z`, `r_elbow_y` — MX-28AT
  - Expected IDs: torso 33–35, head 36–37, left arm 41–44, right arm 51–54.
  - ⚠️ **Verify** names/IDs/types against the ground-truth config JSON in the `poppy-project/poppy-torso` repo (`software/poppy_torso/configuration/`). Never trust this brief over the repo.
- **Protocol:** Dynamixel **Protocol 1.0**, bus configured at **1,000,000 bps** (factory-fresh replacement motors default to 57600 bps, ID 1 — they must be reconfigured).
- **Power:** **12 V** on the bus (MX-28 and AX-12 both tolerate 12 V). Kit PSU is 12 V, several amps. Power is injected into the 3-pin bus via the **SMPS2Dynamixel** board (barrel jack in, 3-pin out).
- **Compute (official current version):** Raspberry Pi 3 mounted inside the head, USB2AX plugged into one of its USB ports, 3-pin cable from USB2AX down into the motor chain. Pi has its own 5 V micro-USB supply. Optional Pi camera + small screen (screen no longer manufactured; irrelevant to us).
- **Software stack (official):** Raspberry Pi OS image with **pypot** (Python Dynamixel control library) + **poppy-torso** (robot definition package) + REST API + Snap! visual programming + Jupyter. Official prebuilt image: **`2020-10-23-poppy-torso.img` (v3.0.0)** — supports **Pi 3 and Pi 4**, ships Python 3.7.
- **Mechanics:** 3D-printed structure, suction pad / clamp to fix the torso to a desk. STLs are in the repo if any part is broken — the Fab Lab can reprint.

---

## 3. The missing pieces — identification & replacement guide

### 3.1 The "connecting device"
The chain is: `Raspberry Pi —USB→ USB2AX —3-pin TTL→ motor daisy chain ←3-pin— SMPS2Dynamixel ←barrel jack— 12V PSU`

Two small boards are involved; the colleagues' "switch" is one or both:

| Part | Function | Looks like | If missing, buy |
|---|---|---|---|
| **USB2AX** | USB ↔ Dynamixel TTL serial adapter (appears as `/dev/ttyACM0`) | Tiny dongle, USB-A plug, single 3-pin socket | **Discontinued.** Replace with **Robotis U2D2** (~€45–60, appears as `/dev/ttyUSB0`, FTDI) — fully supported by pypot |
| **SMPS2Dynamixel** | Injects 12 V PSU power into the 3-pin bus | Small PCB, DC barrel jack + 3-pin connectors | Robotis SMPS2Dynamixel, or U2D2 Power Hub, or any 3-pin hub PCB + 12 V injection (GND common, V+ to pin 2 — verify pinout before powering!) |

Phase 1 must determine which (if either) is physically present in the Fab Lab. Photograph everything found in/around the robot and its box.

### 3.2 The Raspberry Pi
- **Best case:** a spare **Pi 3B/3B+ or Pi 4** → flash the official `2020-10-23-poppy-torso.img` and most software work is already done.
- **Pi 5 or Pi Zero:** official image will NOT boot. Fall back to manual install (§5, Phase 4B): fresh Raspberry Pi OS + Python 3.9 venv + `pip install pypot poppy-torso`. pypot officially supports Python 3.6–3.9; expect to patch minor issues on newer Python — prefer pinning 3.9.
- Also needed: microSD ≥16 GB, 5 V PSU for the Pi, Ethernet cable (first setup is far easier over Ethernet than Wi-Fi).

### 3.3 Suspected dead motors — what "burned" can actually mean
1. **Dead electronics** — motor never responds to ping at any baud, LED never flashes at power-on. → Replace unit (or salvage gears).
2. **Persisted alarm/overload shutdown** — motor responds but won't move; error flags set. → Recoverable via register reset.
3. **ID collision** — two motors with the same ID make the bus look broken. → Fix IDs one motor at a time.
4. **Corrupted firmware** — recoverable with Dynamixel Wizard 2.0 firmware recovery.
5. **Dead cable/crimp, not motor** — very common after 12 years. The 3-pin Molex SPOX cables and their crimps are the #1 suspect. Always swap cables before condemning a motor.
Phase 2's per-motor isolation test discriminates between these. Do not accept "it's burned" without a ping log.

### 3.4 Procurement fallback list (only if Phase 1 confirms missing)
U2D2 (or any pypot-supported USB→TTL Dynamixel adapter) · SMPS2Dynamixel or 3-pin power hub · 12 V ≥5 A PSU · spare 3-pin cables (Molex SPOX 5264, various lengths) · spare MX-28AT and/or AX-12A if motors are confirmed dead · microSD card. Generation Robots (FR) and Robotis EU stock all of this.

---

## 4. Target architecture

```
┌─────────────────────────────┐         Wi-Fi / Ethernet          ┌──────────────────────────────┐
│ LAPTOP (Win11 + WSL2)       │ ◄───────────────────────────────► │ RASPBERRY PI (in robot head) │
│                             │      SSH (you, Claude Code)       │                              │
│ • Claude Code (WSL)         │      HTTP/REST (poppy API)        │ • Raspberry Pi OS / Poppy img│
│ • Whisper STT  (Windows py) │      WebSocket ~30 Hz (custom)    │ • pypot + poppy-torso        │
│ • MediaPipe    (Windows py) │                                   │ • bridge server (ours)       │
│ • webcam + microphone       │                                   │ • USB2AX/U2D2 → motor bus    │
└─────────────────────────────┘                                   └──────────────┬───────────────┘
                                                                                 │ 3-pin TTL, 12V
                                                                          13× Dynamixel servos
```

Design decisions (already made — don't relitigate unless hardware forces it):
- **Perception on laptop, control on Pi.** Whisper and MediaPipe run on the Windows side (webcam/mic access from WSL2 is painful; use Windows-native Python via `python.exe` interop from WSL when you script it).
- **Two channels to the robot:** the official poppy REST API for discrete commands ("wave", "rest"), and a **small custom WebSocket server on the Pi** for the 20–30 Hz joint-angle streaming that imitation needs (per-request HTTP is too slow/jittery for that).
- **Plan B (if no working Pi or adapter-on-Pi trouble):** plug U2D2 straight into the laptop and run pypot locally — the entire motion stack works identically, we just lose the embedded aesthetic. Phase 2 uses this configuration anyway, so it is always available as a fallback.

---

## 5. Execution plan

Work strictly in phases. Each phase has a **DONE-WHEN** gate — do not start the next phase before the gate is met and logged in `PROJECT_LOG.md`.

### Phase 0 — Workspace & knowledge ingestion (you, in WSL, ~1 session)
1. Create the repo skeleton (§8), init git, create `PROJECT_LOG.md` (append-only, dated entries).
2. Clone/fetch the ground truth:
   - `git clone https://github.com/poppy-project/poppy-torso` (config JSON, STLs, doc)
   - `git clone https://github.com/poppy-project/pypot`
   - Fetch and store locally as markdown notes: the Poppy Torso assembly guide pages (BOM, head assembly, wiring arrangement, "addressing dynamixel"), from `https://docs.poppy-project.org/en/assembly-guides/poppy-torso/`.
3. Extract from the config JSON the authoritative motor table (name, ID, type, angle limits, offsets) into `hardware/motor_map.md`. Correct §2 of this brief if it disagrees.
4. Produce `hardware/INVENTORY_CHECKLIST.md` for Phase 1 (printable, checkbox style, with photos requested at each step).
**DONE-WHEN:** repo exists, docs cached, motor map extracted, checklist handed to Jalaleddin.

### Phase 1 — Physical inventory & diagnosis (Jalaleddin's hands, your checklist)
Guide him through, collecting photos into `hardware/photos/`:
1. Full robot photo survey; state of 3D-printed parts; anything cracked → note STL to reprint.
2. Contents of head + box: **is there a USB2AX? an SMPS2Dynamixel? a 12 V PSU? which Raspberry Pi models are the spares (exact model + RAM)?**
3. Cable survey: count 3-pin cables, inspect crimps, wiggle-test each connector.
4. Motor survey: count motors, read the model printed on each case (MX-28AT vs AX-12A), note any with stickers/IDs, gently rotate each joint by hand with power OFF — note grinding/blocking (gearbox damage indicator).
5. PSU check with multimeter: 12 V output, correct barrel polarity (center-positive expected — **verify against SMPS2Dynamixel silkscreen before ever powering**).
6. Fill the procurement list §3.4 for anything missing; Jalaleddin orders or scavenges.
**DONE-WHEN:** `hardware/INVENTORY.md` complete with photos; missing-parts list resolved (parts in hand); Pi model known.

### Phase 2 — Bench bring-up of the motor bus, FROM THE LAPTOP (no Pi yet)
Goal: prove the bus, enumerate motors, and settle the "burned motors" question with evidence.
1. **Windows first, zero code:** install **Dynamixel Wizard 2.0** (Robotis) on Windows. Connect U2D2/USB2AX → *one single motor* → power injector → 12 V. Scan Protocol 1.0 at 57600 **and** 1,000,000 bps, all IDs. Log result. Repeat motor by motor (isolation test). This gives a definitive alive/dead/wrong-ID matrix and allows firmware recovery on zombie motors.
2. Build `hardware/motor_status.md`: per motor — ID found, baud, firmware version, voltage reading, temperature, error flags, verdict.
3. Then the full chain: all healthy motors daisy-chained, single scan must see them all. Any motor that "disappears" in the chain but works alone → cable/connector problem, swap and retest.
4. **pypot from WSL (prep for the Pi era):** use `usbipd-win` to attach the USB adapter into WSL2 (`usbipd bind` / `usbipd attach --wsl`), confirm `/dev/ttyUSB0` (U2D2) or `/dev/ttyACM0` (USB2AX) appears. Create a Python 3.9 venv, `pip install pypot`, and reproduce the scan in Python (`pypot.dynamixel.get_available_ports()`, `DxlIO(port, baudrate=...)`, `.scan()`). Save as `scripts/diagnostics/scan_bus.py`.
5. Fix motor configs to match the official map: correct IDs, baud 1 Mbps, return delay 0, angle limits — use `poppy-configure` (ships with pypot) or Wizard 2.0, one motor on the bus at a time when changing IDs.
**SAFETY:** first power-on of each motor: hand on the PSU switch, nothing attached to the horn under load, stop at any smoke/smell/heat. Motors that were declared dead get 30 s max power the first time.
**DONE-WHEN:** every motor has a verdict; all healthy motors respond on one chain at 1 Mbps with correct IDs; dead motors listed for replacement.

### Phase 3 — Raspberry Pi head bring-up
**Path A (Pi 3/3B+/4 available) — preferred:**
1. Flash `2020-10-23-poppy-torso.img` (from `poppy-project/poppy-torso` GitHub Releases, 7z — unzip first) to microSD with Raspberry Pi Imager / balenaEtcher.
2. Boot with Ethernet to the same network as the laptop. The image exposes hostname `poppy.local` and the Poppy web interface; default SSH credentials are in the Poppy docs (change the password immediately).
3. If using a **U2D2 instead of USB2AX**: check the robot config's serial-port entry; set it to the detected port or `"auto"` if the scan fails on first launch.
**Path B (only Pi 5 / unsupported Pi available):**
1. Flash current Raspberry Pi OS Lite (64-bit), enable SSH headlessly.
2. Install Python 3.9 (pyenv or deadsnakes-equivalent for the distro), create venv, `pip install pypot poppy-torso` (docs suggest `--no-deps` upgrades to avoid scipy build pain; install numpy/scipy from apt/piwheels first). Expect and patch small incompatibilities — log every patch.
3. Recreate the services the image provides only as needed: we mainly need pypot + the REST API, not Snap!.
**Both paths:** physically mount Pi in head per the assembly guide (USB/Ethernet ports facing rear), route the 3-pin cable, do NOT close the head face yet.
**DONE-WHEN:** you can `ssh` into the Pi from WSL and a Python one-liner on the Pi sees all motors.

### Phase 4 — Remote access & operating discipline for you
1. Key-based SSH from WSL (`ssh-keygen`, `ssh-copy-id`), entry in `~/.ssh/config` as host `poppy`. From then on you run commands as `ssh poppy '<cmd>'`.
2. Long-running processes on the Pi live in `tmux` sessions you create/attach — never orphan a torque-enabled process.
3. Set up `rsync`/`scp` deployment: code is edited in the WSL repo, deployed to `/home/poppy/robot/` — the Pi is a target, not a dev environment. Git-commit before every deploy.
**DONE-WHEN:** you can edit → deploy → run → read logs on the Pi without Jalaleddin touching anything.

### Phase 5 — First motions
Incremental script ladder, each in `scripts/motion/`, each reviewed by Jalaleddin before running with torque:
1. `00_read_only.py` — instantiate `PoppyTorso()`, print all `present_position`, `present_temperature`, `present_voltage`. **Robot compliant (torque off).** No movement.
2. `01_single_joint.py` — one joint (`l_elbow_y`), stiff, low `moving_speed`, small `goto_position` (±10°), back to compliant. Hand near PSU switch.
3. `02_pose_and_rest.py` — named poses (rest, arms-slightly-out), slow transitions, always end compliant.
4. `03_wave.py` — first choreography (shoulder + elbow sinusoid).
5. `04_record_replay.py` — use pypot's `MoveRecorder`/`MovePlayer`: put robot compliant, Jalaleddin moves the arm by hand, record, replay. (Huge demo value, trivial code.)
**DONE-WHEN:** wave demo runs reliably; temperatures stay < 50 °C; a `rest_and_release()` helper exists and every script exits through it.

### Phase 6 — Bridge for real-time control
1. On the Pi: `bridge/server.py` — asyncio WebSocket server wrapping the `PoppyTorso` instance. Accepts JSON `{joint: target_deg, ...}` at up to 30 Hz, applies **rate limiting, per-joint clamps (from the config), and max angular velocity**, plus a watchdog: no message for 500 ms → freeze, 2 s → compliant. Also expose `/pose/<name>` discrete commands.
2. On the laptop: `bridge/client.py` — thin client lib used by both voice and imitation layers.
3. Latency test target: < 80 ms laptop→motion round trip on LAN.
**DONE-WHEN:** streaming a slow sine wave from the laptop moves the arm smoothly; unplugging Wi-Fi makes the robot go compliant within 2 s.

### Phase 7 — Voice control (Whisper)
1. Windows-side Python: `perception/voice.py` — mic capture → VAD (e.g. silero-vad) → **faster-whisper** (small/int8 model is plenty; French + English) → intent parsing (simple keyword grammar first: "salue / wave", "repos / rest", "bouge le bras gauche / left arm up"…) → bridge client.
2. Optional later: wake word (openWakeWord), or LLM-based intent parsing.
**DONE-WHEN:** 5+ voice commands work end-to-end in < 2 s, in French and English.

### Phase 8 — Imitation (MediaPipe)
1. Windows-side Python: `perception/mimic.py` — webcam → MediaPipe **Pose Landmarker** → compute human joint angles (shoulder abduction/flexion, elbow flexion, head yaw/pitch) from landmarks → map to robot joints (`l/r_shoulder_x/y`, `l/r_elbow_y`, `head_z/y`) with **mirror mode**, One-Euro filtering, deadband, and hard clamps → stream via bridge at ~25 Hz.
2. Calibration routine: human T-pose ↔ robot T-pose to fix offsets/signs.
3. Demo mode: voice command "copie-moi / mirror me" toggles imitation on/off (integrates Phase 7 + 8).
**DONE-WHEN:** robot mirrors slow arm raises and head turns convincingly and *safely* (never slams a limit, never oscillates).

---

## 6. Operating contract — how you work with Jalaleddin

- He is a final-year engineer, fluent in Python/React/Linux, direct style. **No hand-holding prose, no over-explaining basics.** Numbered steps, concrete values, real commands.
- Physical actions: always as a **checklist with expected observations** ("plug X, LED should blink twice; if not → …"). Ask for photos when a visual check matters.
- **Never assert — verify.** Repo config JSON beats this brief; multimeter beats datasheet assumptions; a ping log beats "colleagues said it's burned."
- Keep `PROJECT_LOG.md` religiously: every session, every hardware finding, every patch, every decision + rationale. This project will pause and resume; the log is the memory.
- Commit early, commit often, meaningful messages. All scripts idempotent and re-runnable.
- When blocked by missing hardware, immediately produce the exact procurement line (part, spec, EU source) and switch to whatever phase work is unblocked.
- The Poppy forum (`forum.poppy-project.org`) is the canonical place for weird legacy issues — search it before inventing workarounds for old-firmware quirks.

## 7. Safety rules (non-negotiable)

1. **E-stop = the 12 V PSU switch/plug.** It stays within arm's reach during any powered work. Jalaleddin's hand is on it during every first-run.
2. Verify **polarity** with a multimeter before the first power-on of any power chain. Reverse polarity is the classic Dynamixel killer — likely the origin story of the "burned" rumor.
3. Default state is **compliant** (torque off). Every script starts compliant, ends compliant, and traps exceptions/SIGINT into `rest_and_release()`.
4. **Low speeds always** during bring-up (`moving_speed` well below max), angle targets clamped to config limits minus a margin.
5. Monitor `present_temperature`: > 50 °C → pause; > 55 °C → torque off, cool down.
6. No torque-enabled process runs unattended, ever. Watchdog in the bridge is mandatory before any streaming control.
7. Fingers out of joint pinch zones when stiff. The MX-28 is small but it does not care about fingers.
8. One change at a time on the bus (IDs, baud, wiring) — then re-scan.

## 8. Repo skeleton to create in Phase 0

```
poppy-revival/
├── POPPY_TORSO_BRIEF.md      # this file
├── PROJECT_LOG.md            # append-only journal (you maintain it)
├── hardware/
│   ├── INVENTORY_CHECKLIST.md
│   ├── INVENTORY.md
│   ├── motor_map.md          # extracted from repo config JSON
│   ├── motor_status.md       # Phase 2 verdicts
│   └── photos/
├── vendor/                   # cloned poppy-torso, pypot (read-only reference)
├── scripts/
│   ├── diagnostics/          # scan_bus.py, health_report.py
│   └── motion/               # 00_read_only.py ... 04_record_replay.py
├── bridge/                   # server.py (Pi), client.py (laptop)
├── perception/               # voice.py, mimic.py  (run with WINDOWS python)
└── deploy/                   # rsync script, systemd/tmux helpers for the Pi
```

## 9. Reference links (fetch and cache locally in Phase 0)

- Poppy Torso assembly guide (BOM, head, wiring, motor addressing): https://docs.poppy-project.org/en/assembly-guides/poppy-torso/
- Software install docs: https://docs.poppy-project.org/en/installation/install-poppy-softwares.html
- Repo + official SD image (Releases → `2020-10-23-poppy-torso.img`, Pi 3/4): https://github.com/poppy-project/poppy-torso
- pypot (library + `poppy-configure` + herborist): https://github.com/poppy-project/pypot — docs: https://poppy-project.github.io/pypot/
- Community forum (legacy-hardware goldmine): https://forum.poppy-project.org
- Robotis e-Manual — MX-28 (Protocol 1.0) and Dynamixel Wizard 2.0: https://emanual.robotis.com/docs/en/dxl/mx/mx-28/ · https://emanual.robotis.com/docs/en/software/dynamixel/dynamixel_wizard2/
- usbipd-win (USB serial into WSL2): https://github.com/dorssel/usbipd-win
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- MediaPipe Pose Landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker

## 10. Open questions — resolve in Phase 1, update this file

1. Exact Raspberry Pi models available at the Fab Lab (decides Path A vs B in Phase 3).
2. USB2AX / SMPS2Dynamixel / 12 V PSU: present or to buy?
3. True motor inventory and their as-found IDs (2013 unit may deviate from current docs).
4. Which motors, if any, are actually dead (Phase 2 evidence).
5. Is there a Pi camera / speakers in the head parts bin? (Nice-to-have for later; not on the critical path.)

— End of brief. Start with Phase 0. Log everything.
