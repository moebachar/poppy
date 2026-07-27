# PROJECT LOG — Poppy Torso Revival

Append-only. Newest entry at the BOTTOM. Every session, hardware finding, patch, decision + rationale goes here (brief §6).

---

## 2026-07-27 — Session 1 (Claude) — Phase 0: workspace & knowledge ingestion

**Environment reality check** (deviations from brief §0/§5 assumptions):
- Claude Code runs **natively on Windows 11** (PowerShell + Git Bash), not inside WSL2. WSL2 (Ubuntu 22.04) exists and stays available as fallback.
- Consequence for Phase 2: bench work can use **Windows-native Python + COM port** directly — `usbipd`-into-WSL is demoted to fallback. (Dynamixel Wizard 2.0 is Windows-native anyway, so the whole bench phase lives on Windows.) Brief §5 Phase-2 step 4 retargeted accordingly.
- Python on PATH: **3.13.9 only** (no `py` launcher). pypot officially supports ≤3.9 → Phase 2 decision: install 3.9 (python.org or pyenv-win) into a venv per brief §3.2, or trial pypot on 3.13 and patch. Default: pin 3.9.
- git 2.51.2; commit identity from machine-global config: Mohamed BACHAR <moebachar@users.noreply.github.com>.

**Done:**
- Repo skeleton per brief §8, plus `docs/` for cached documentation. `git init` (branch `main`), `core.autocrlf false`.
- Vendor clones (gitignored; re-clone commands below):
  - `poppy-torso` @ `8073e69` (full history — useful for 2013-era config archaeology)
  - `pypot` @ `1326395` (full history)
  - `poppy-docs` @ `1ab374f` (shallow)
- ⚠️ poppy-torso clone warned "17 files should have been pointers" (git-lfs, `hardware/URDF/meshes/*.STL`) — the URDF meshes may be broken LFS pointers. Irrelevant now; **if a printed part ever needs reprinting, verify the STL source first** (assembly STLs from the docs/website, not only this repo).
- **Motor map extracted** → `hardware/motor_map.md` from `software/poppy_torso/configuration/poppy_torso.json`. Cross-check vs brief §2: **full match** — names, IDs (torso 33–35, head 36–37, L arm 41–44, R arm 51–54), types (11× MX-28, 2× AX-12). No brief correction needed. Config also declares a **camera** sensor (OpenCVCamera, index −1) → §10 Q5 stays relevant for Phase 1.
- Verified in code: pypot `DxlIO` default baud = **1,000,000 bps** (`vendor/pypot/pypot/dynamixel/io/abstract_io.py:49`) — confirms brief §2.
- **Docs cached** → `docs/` (committed, ~11 MB incl. images), source poppy-docs @ `1ab374f`:
  - `docs/assembly-guides/poppy-torso/` — BOM, trunk/arms/head assembly, wiring arrangement, dynamixel hardware, addressing_dynamixel, warnings
  - `docs/installation/` — install-poppy-softwares, burn-an-image-file, install-a-poppy-board, drivers, zeroconf, vrep
  - `docs/img/torso/`, `docs/img/humanoid/torso-{motors,wires}.png`
- **Phase 1 checklist** → `hardware/INVENTORY_CHECKLIST.md` (printable, sections A–I, photo naming `hardware/photos/phase1/<sec><nn>_<desc>.jpg`). `hardware/INVENTORY.md` created as fill-in template.

**Vendor re-clone (if ever needed):**

    git clone https://github.com/poppy-project/poppy-torso vendor/poppy-torso   # pin: 8073e69
    git clone https://github.com/poppy-project/pypot vendor/pypot               # pin: 1326395
    git clone --depth 1 https://github.com/poppy-project/poppy-docs vendor/poppy-docs

**Phase 0 gate: MET** (repo ✓ · docs cached ✓ · motor map extracted ✓ · checklist ready ✓).

**Next:** Phase 1 — Jalaleddin runs `hardware/INVENTORY_CHECKLIST.md` at the Fab Lab (photos → `hardware/photos/phase1/`), then we fill `INVENTORY.md`, resolve brief §10 Q1–Q3/Q5, and settle procurement. Nothing gets powered except the PSU open-circuit test (checklist §F).

---

## 2026-07-27 — Session 1 (continued) — Operating contract amendment: operator is a hardware novice

- Jalaleddin flagged himself as a **robotics/electronics novice** (software fluency per brief §6 unchanged). Brief §6 "no hand-holding" now applies to **software topics only**; every physical/hardware procedure must assume zero prior experience.
- `INVENTORY_CHECKLIST.md` rewritten to **v2**: picture gallery of what each part looks like (each linked image verified by actually viewing it), mini-glossary (crimp, barrel jack, PSU…), beginner multimeter walkthrough for the PSU test, and the universal rule — *unsure → photo front+back → move on; Claude identifies from photos*. Live photo-by-photo inventory offered as a workflow (photos land in `hardware/photos/phase1/`, Claude reads them directly).
- Image verification bonus: the cached official photos confirm brief §1's caveat about early units — the 2013-era kit used an **Odroid U3 + eMMC + UBEC** (`parts_electronics.JPG`), and `head_odroid.JPG` shows a populated 2013-era head interior — likely what our (now empty) head once held. If an Odroid/eMMC turns up in the box: photograph, keep (archaeology; we still go the Raspberry Pi route).
- Saved to Claude's persistent memory so this survives across sessions.
- **No phone camera available** → photo workflow retargeted to the **laptop webcam** (verified present + working: "Integrated Webcam", Windows Camera app installed; shots land in `Pictures\Camera Roll`, Claude moves/renames them into the repo). Printed text (motor models, PSU label, multimeter reading) is typed, not photographed — more reliable anyway. Checklist updated. Side-note: Phase 8 (MediaPipe imitation) depends on this same webcam — its existence is now confirmed.

---

## 2026-07-27 — Session 2 (Jalaleddin at the lab + Claude) — Phase 1 COMPLETE · acceleration decision · bench prep

**Phase 1 executed by Jalaleddin** (morning; 8 webcam + 4 borrowed-phone photos, each verified by Claude, renamed A01…B04 in `hardware/photos/phase1/`). Full write-up: `hardware/INVENTORY.md`. Headlines:
- **All critical electronics FOUND**: USB2AX ×2, SMPS2Dynamixel-type injector (≥1), 12 V PSU (works per colleague; label+polarity verify pending), full cable set. Spares: AX-12A (orange gripper), loose motor TBD, Pi 3 free + likely official RPi PSU.
- Robot structurally complete; **all 13 joints backdrive smoothly**; models map-consistent (MX-28AT + AX-12A neck); original ID sticker "37" on head_y. "Burned motors" rumor: zero physical evidence so far.
- Head contains camera + speakers + screen; SBC bay empty (as known).
- ⚠️ **Ergo Jr stash on same table** (XL-320 ×~8, small-3P cables, Dexter sensors, 3P Extension PCBs, Pi 3 + SD on the Ergo Jr arm): NOT Torso-compatible / off-limits. New "Robot Cable-3P" 10-pc bags may be standard 3P = usable spares → 10-s connector-fit check pending.
- ⚠️ **Several look-alike black PSUs on one table** → hard rule: only the label+meter-verified 12 V brick ever touches the bus (19 V laptop brick = servo killer).
- Procurement: **nothing needed** for bench + first motion. Later: microSD ≥16 GB, Ethernet cable (Phase 3).
- Brief §10 updated in place. **Phase 1 gate: MET** (PSU polarity check folded into Phase 2 step 0 — it is a bench-day action by nature).

**DECISION — schedule acceleration (operator wants first motion TODAY):**
- Phase 2 compressed: toolchain validated on a **spare motor first** (never the robot), then **full-chain scan as-wired** at 1 M + 57600 bps. Per-motor isolation only for motors that misbehave — justified: mechanics test clean, and the isolation step's purpose (settle the "burned" rumor with evidence) is met by chain scan + targeted follow-up.
- First motion TODAY via **Plan B (brief §4)**: laptop-direct (USB2AX on Windows + pypot venv). Phases 3–4 (Pi head) deferred to next session. Today's motion scripts talk DxlIO-level (the `PoppyTorso` object arrives with the Pi).
- Safety §7 fully in force; e-stop = mains plug/strip switch of the verified PSU.

**Software/bench prep (Claude):**
- `.venv` Python 3.13 + **pypot 5.0.2 — import OK** (no 3.9 fallback needed 🎉).
- Scripts ready: `scripts/diagnostics/scan_bus.py` (read-only multi-baud scanner vs map), `scripts/motion/00_read_only.py`, `scripts/motion/01_single_joint.py` (voltage/temp guards, EEPROM-limit clamps, always ends compliant).
- Dynamixel Wizard 2.0: robotis.com refuses CLI download (404/site shell) → Jalaleddin downloads by browser (emanual → Windows X64, no=1670); fake `.exe` (HTML) deleted from Downloads. Wizard is comfort/rescue tooling — pypot suffices for today.
- **Protocol amendment 2 (operator request): ONE step at a time during hands-on work** — each instruction is a single action + expected outcome; next step decided from the reported result. No multi-step runbooks in chat (plans live in this log instead). *(Note: this line first landed in a stray `hardware/photos/phase1/PROJECT_LOG.md` due to a shell cwd drift — stray deleted, lesson: absolute paths only.)*

---

## 2026-07-27 — Session 3 (bench, live) — Phase 2 essentially DONE · ⭐ FIRST ROBOT MOTION in ~12 years ⭐

Step-by-step live session (one-step protocol). Chronology + evidence:

1. USB2AX plugged into laptop → **genuine Xevelabs USB2AX** (VID 16D0 PID 06A7) on **COM7**; pypot sees it.
2. PSU label `OUTPUT: +12V ⎓ 5A`; multimeter **+12.26 V center-positive** → the one authorized bus PSU.
3. Bench chain (per reference photo): USB2AX → injector → motor. First test motor (the loose MX-28AT from the table) never blinked → probably a long-dead spare. Swapped for the **boxed MX-28AT**: boot blink OK → **factory ID 1 @ 57600, fw 41** → commanded moves (15°/25° @ ≤20 °/s) OK. **Full toolchain proven before touching the robot.**
4. Robot chain first power-up: **12 of 13 motors boot-blink**; non-blinker = end of right arm. Operator isolation-tested it (injector fed directly into it): still no boot, neighbors fine.
5. Whole-chain scans garbled at both bauds (garbage byte on every ping) **while the dead motor was connected**; unplugging it restored a perfectly clean bus → the dead unit actively corrupts the data line (transceiver failure).
6. Clean scan: **12/12 at 1 Mbps, IDs exactly per the official map** (33–35, 36–37 AX-12, 41–44, 51–53). **Missing: 54 = r_elbow_y → the single true "burned motor".** Twelve years of rumor reduced to one unit; as-found config = current docs, zero legacy deviation.
7. Replacement surgery started (friend + operator) — blocked: need a **precision Phillips PH0/PH1**. Dead 54 to be labeled and kept (firmware-recovery candidate; gear donor).
8. **FIRST MOTION:** robot upright on suction base, left elbow ID 44: 12° then 20° slow bends (15 °/s), ends compliant, ≤29 °C, visually confirmed by operator. **Day goal achieved.**

Artifacts: `hardware/motor_status.md` (all verdicts) · scanner patched to ignore USB2AX's virtual ID 253.

**Remaining to close Phase 2 fully:** physical swap of 54 (needs PH0/PH1) → software rename of the spare (ID 1→54, baud→1 M, return-delay 0) → 13/13 rescan. Proper zero-calibration + EEPROM-limit audit of the replacement lands with Phase 3 (poppy-configure on the Pi era).

---

## 2026-07-27 — Session 3 (continued) — Stiffness saga solved · robot STANDS · pose record/replay

- Operator: full-body stiffness "did not work" twice. Investigation detours (both preserved as lessons): (a) multi-id broadcast writes suspected mangled → switched to **per-motor writes, kept as house rule** (cheap, provably delivered); (b) PID gains suspected soft → false alarm: pypot returns unit-converted gains, raw P=32 = factory default.
- **Real cause: UX/timing.** The holds auto-released after 45 s; the operator push-tested after release, both times. Standing lesson: every stiffness claim must carry a live `is_torque_enabled` read-back AND overlap the human verification window.
- `03_stand_still.py`: long hold (minutes-scale) with torque read-back, 30 s status prints, temp watchdog (52 °C hard release). Verified live: 12/12 stiff, operator confirmed **RIGID by push test**. ⭐ The robot stands.
- "Stand from any messy position": config-math absolute posing **rejected for now** — 2013 offsets untrustworthy until calibration (horn re-indexing risk). Chosen instead: **sculpt-by-hand → record → replay**: `04_pose.py save/goto/release`, stance stored in `scripts/motion/poses/stand.json` (12 joints). `goto` = freeze-at-current, then slow travel (20 °/s), 100° max-travel guard, always releases via finally.
- Robot ended the day holding the operator-sculpted stance (30-min supervised window). Wave demo (02, elbow-only) functional; the shoulder-roll "invisible motion" was geometry (arm-axis twist), not a fault.

---

## 2026-07-27 — Session 4 (evening) — Simulation pipeline online · sim-authored move executed · sign & assembly discoveries

- **Operator direction change:** no hand-built tooling — install an established sim. Chosen: **CoppeliaSim EDU** (official Poppy simulator; docs cached). Pipeline verified end-to-end: CoppeliaSim 4.x + legacy remote API (port 19997; duplicate-instance kills the bind — one instance only!) + pypot 5.0.2 + poppy-torso pkg. `PoppyTorso(simulator='vrep')` connected first try; sim head wiggle confirmed.
- `sim/keyframer.py`: interactive authoring on the sim robot (set joints / capture / play / export). Operator authored an **8-frame wave (8.5 s)** and exported it. `hardware/JOINT_CHEATSHEET.md` written (names, motions, ranges, mirror warning).
- `scripts/motion/06_execute_move.py` = THE robot script: stand → execute exported move (pypot-Move or keyframes JSON) → hold → release. Applies moves as **deltas from frame 1 anchored to the recorded stance** (cancels stale offsets); clamps to official joint limits (5° margin) after the wave was found commanding 119° on a 110°-limit shoulder.
- ⚠️→✅ **Sign inversion found and fixed empirically:** first hardware run, arm moved INTO the body (operator e-stopped — textbook). Evidence (l_shoulder_x + earlier l_elbow observations) → **this 2013 unit runs the NEGATION of the config's orientation flags on every tested joint**; global flip applied in 06, verified with a dedicated 3-s `sigtest` move (arm out = matches sim). Wave then executed fully and safely.
- **Aesthetic gap + root cause:** waving hand pointed down — the stance anchor ≠ sim rest pose. Attempting to sculpt the real robot into the sim rest revealed it **cannot physically reach it: probable 2013 assembly error** (horns mounted off-spline — consistent with the ~90° shoulder offset measured at noon). → **Tomorrow's lead: proper per-motor zero calibration** per the cached official assembly guide (horn alignment + poppy-configure), which would make absolute sim posing exact and retire the delta-anchor workaround.
- End-of-day state: all motors compliant, hottest 45 °C, powered down. ⚠️ final scan saw only 10/12 motors — likely a connector nudged during sculpting; re-seat and rescan tomorrow. Motor 54 swap still pending (needs PH0/PH1 precision screwdriver).
- **Day scorecard, from 12 years of dust: bus revived · 12/13 motors healthy · the one burned motor identified · first motion · standing · pose record/replay · full sim-to-robot authoring pipeline.**
