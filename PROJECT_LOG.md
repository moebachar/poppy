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

---

## 2026-07-28 — Session 5 — ⭐ ROOT CAUSE FOUND (encoder seam) · multi-turn fix · teach-mode record/replay pipeline DONE ⭐

**Morning:** clean 12/12 scan (yesterday's "10/12" self-resolved — sleepy connector). `RUNBOOK.md` created (daily commands).

**Elbow surgery (operator-led):** operator diagnosed the elbows as assembled inverted (masked by a twisted arm) and physically flipped them. Stance re-captured post-flip; elbow direction re-verified on hardware (`elbowtest` mini-move).

**Sim pipeline hits a wall:** operator's wave moved the arm back, not out. `sim/play_move.py` built (replay any exported move in CoppeliaSim = ground truth); sim playback correct → hardware mapping at fault. `shouldertest` mini-move: real arm moved opposite to sim **under BOTH signs of l_shoulder_y** — physically impossible via the delta path → something deeper than signs.

**⭐ THE ROOT CAUSE (explains 2 days of chaos):** analysis of the first demonstration recording showed motors **41, 42, 44 working arcs cross the MX-28 encoder seam** (±180° register rollover); **42's rest position sits exactly ON it** (readings flicker ±178↔−178 — same physical spot). Joint mode can't be *commanded* across the seam (long-way-around sweeps; pypot clamps writes into one turn). Retroactively explains: the 302°-away replay refusal, the wave's shoulder barely lifting (goals clamped at the seam), the "signs flipped vs config" confusion, and the shouldertest paradox. A 2013 horn-mounting error is the ultimate cause.

**Fix — multi-turn mode (operator vetoed re-horn surgery, software-only):**
- `scripts/motion/dxl_multiturn.py`: raw register IO over pypot's packet layer (pypot converters clamp goals to one turn and misread negative registers). EEPROM CW=CCW=4095 on **41/42/44 only** (originals: cw=0, ccw=4095 — `disable` restores). Multi-turn offset 0, res divider 1. CLI: status/enable/disable/jog/watch.
- **Verified live** (operator moved the arm during a `watch` stream): counter counts continuously across ±180 in both directions. Outward on 42 = raw **decreasing** (my first jog guessed + and gently pressed his ribs — 3° stall, no harm). "Mystery 17° drift" = gear friction holding the soft arm cocked; not a fault.
- Seam-aware updates: `07` (unwrap recorded series + rebase by whole turns to current reading — counter re-bases each power-up), `03`/`04` (raw freeze/read/goto + rebase for seam ids), `06` (skips seam motors; sim pipeline PARKED until seam-aware — record/replay is the primary authoring path now).

**Teach-mode record/replay (the operator's requested workflow, iterated live to final form):**
- `07_record_replay.py record <name>`: whole body **rigid at 100%** holding the stand pose (fixed goals — no gravity ratchet), only motors named `--m<ID> <pct>` go loose (lowered torque ceiling + goal-follows-hand every tick). Enter stops, saves raw@20 Hz JSON to `moves/recorded/`. Iterations that died on the bench: all-soft puppet (body flops), group stiffness + goal-follow (gravity ratchet — goal chased the sag), deadband follow (constant 4° drag), grab-latch (shoulders mushy). Final explicit per-motor design is the operator's spec and **works well**.
- `replay <name>`: full-strength freeze → guarded travel to first frame → 20 Hz stream (frame-drop on lag, temp watchdog) → hold → release. `list` shows the library.
- Library so far: `hello_wave` (8.1 s), `secret_move` (24.6 s), `arms_only`.

**Operator's declared goal:** a library of **12–15 named moves** to choose from and play. **Deferred by operator** until motor 54 is replaced (screwdriver still missing; expected in the coming days). Next mission: operator will announce.

**Open items:** motor 54 swap (then ID 1→54, baud→1M, 13/13 rescan) · sim pipeline revival = optional later (needs seam-aware 06 + per-joint sign verification) · zero calibration only if we ever re-horn.

---

## 2026-07-28 — Session 5 (afternoon) — Phase 3 opened: head/brain bring-up (Pi 3) — flashed & recon done, blocked on 5 V power

**Mission (operator):** Pi 3 into the head; run our motion stack ON the Pi, commanded from the laptop over SSH; then speakers ("mouth"), camera, maybe mic later. 3-hour box — power hunting ate it; ~85% of the software path is done.

**Head recon (photos: `hardware/photos/phase3-head/C01–C09`):**
- Camera = **JDEPC-OV05 USB module** (plain USB webcam → plugs into Pi; zero extra hardware).
- Speakers = **Visaton K 20.40, 8 Ω ×2**, soldered leads ending in **bare stripped wire — the audio amp is MISSING** from this unit (official-style build wants a small 5 V class-D amp, e.g. MAX98306/PAM8403 → procurement).
- "Screen" = **dummy** (official BOM: "Fake manga screen"; no sockets — confirmed by operator). Topic closed.
- Found loose in kit: **Pixl board** — it's the **Ergo Jr's** Pi interface (7.5 V in). Tried as a bench 5 V source for the Pi (in-spec use, correct 7.8 V center-positive adapter verified by meter): input rail live (7.79 V on motor port) but **5 V output to Pi pins 2/6 reads 0 → Pi-power section dead**. Abandoned; bagged & labeled.
- LM324N found by operator = quad op-amp, not a speaker amp (educational moment: signal vs power amp).

**SD card saga:**
- Mystery card in the boxed Pi = standard Raspberry Pi OS 2021-05-07 — but with **UART-at-1M-baud settings in config.txt: someone at the lab attempted a Poppy/Dynamixel brain in 2021** and stopped. Full-disk backup taken before wipe (`C:\Users\mbachar\pi-sd-backup\pi3-sd-2021.img.gz`, 29.5 GB → 3.1 GB, gzip-verified restorable) — operator's call: "it belongs to the lab".
- Flashed **Raspberry Pi OS Lite 64-bit** via Raspberry Pi Imager (winget absent → direct installer): hostname `poppy`, user `poppy`, **SSH public-key-only** (laptop ed25519 key), WiFi = **laptop's Windows mobile hotspot on 2.4 GHz** (org WiFi CESI_Recherche is WPA2-PSK but **5 GHz-only here — invisible to a Pi 3**; phone hotspot unavailable). Mid-course error: card pulled early + Windows format → Imager "Accès refusé" → fixed with admin `Clear-Disk -Number 1 -RemoveData` re-flash.
- First flash DID join the hotspot (ARP `b8-27-eb` at 192.168.137.60, ping OK) but **SSH refused** — likely the Services-tab SSH toggle missed; re-flash includes it (unverified: no boot attempt on the corrected card yet).

**Power saga (the day's real blocker):** Pi 3 wants 5 V ⎓ 2.5 A. Laptop USB (~0.5 A) = red-LED brownouts (but boots headless to WiFi — usable stopgap). Lab findings: 1 A wall wart (too weak), 12 V 1.5 A (VETOED — 5 V only, ever), 7.5 V 2 A (fed the dead Pixl). Official Pi PSU from inventory day: not found today.

**Safety rules taught & enforced:** volts must match exactly / amps are "up to" · never barrel-into-Pi · polarity check by meter before energizing unknown adapters · photo-verify board mounting before power.

**Tomorrow's opening moves:** ① buy/borrow **5 V ⎓ 2.5 A micro-USB PSU** (+ class-D amp; + PH0/PH1 driver for motor 54; optional spare microSD) · ② boot corrected card (laptop USB OK as stopgap), hotspot on, SSH in (`poppy@192.168.137.x`, key auth) · ③ venv + pypot on Pi, copy scripts/poses/moves, USB2AX into Pi, scan → replay a move from the Pi = **the brain milestone** · ④ voice via any powered 3.5 mm speaker until the amp arrives.

---

## 2026-07-29 — Session 6 — ⭐ POPPY TALKS: Pi brain online (parallel thread) + full voice agent ⭐

**Parallel thread (head/brain agent):** Pi 3 online — SSH `poppy@poppy.local` (org network, key-only), venv `~/env` (Python 3.13.5 + pypot 5.0.2), motion stack at `/home/poppy/poppy`, USB2AX on the Pi, clean 12/12 scans from the Pi, head camera capturing (first photos from the Pi in `hardware/photos/phase3-head/`), face tracking (`08_face_track.py`) + browser face-view (`09_face_view.py`, MJPEG + optional YuNet). MAX98306 amp procured, speaker leads attached (head audio unfinished). Pi runs CPU-throttled — proper 5 V ⎓ 2.5 A PSU still missing.

**This thread: the voice agent, end to end** — `perception/voice_agent.py` + `scripts/motion/10_motion_server.py` (architecture map: claude.ai artifact "Poppy Voice Agent").
- All-OpenAI pipeline, key in `.env` (deliberately overrides the machine's corporate Azure OPENAI_* vars): hold-SPACE push-to-talk with live chunked transcription (gpt-4o-mini-transcribe) → gpt-4.1-mini with **one tool per recorded move** (required `say` arg, word budget ≈ 3 × move-seconds, spoken WHILE the body moves; successful moves skip the wrap-up round) → gpt-4o-mini-tts (echo, 1.15×, teenage-robot instructions) streamed as PCM + 30 Hz ring-mod robot effect (measured 1.4 ms per 5 s clip — free).
- Persistent motion server, line protocol over a pipe (local COM7 or ssh to the Pi, auto-picked): awaken → settle ≤150° → head-glance mid-settle → hold stance @ 60 % torque; plays @ 100 %, 40°/s stance hops; temp watchdog 52 °C release → 45 °C auto-resume (bust_x measured at exactly 52.0 °C — the "goes soft" mystery WAS the watchdog); every exit releases.
- Wake-up scene: greeting generated in parallel with boot, plays the instant its audio exists. Persona: Poppy, made by Mohamed Bachar (PhD student, CESI LINEACT), thankful, eager to learn; 2013/Inria lore removed by operator request.
- Teach mode: `--m<ID> 0` = torque fully OFF now (was torque-limit-0 with electromagnetic drag). Library re-recorded: wave 4.1 s · dab 3.2 s · secret_move 4.2 s.
- Profiling built in (`[prof]` line per turn + exit summary). Measured: stt 0.85 · brain 0.86 · tts 1.4 · move 9.6 s. Built at session end but **not re-measured**: streaming TTS (expect ~0.5 s to first sound) and 40°/s travels (expect ~6 s per wave).
- Hardware events: 51→52 shoulder connector went sleepy (re-seat fixed — watch item; swap the cable if it recurs); long torque holds heat the chest motors. USB2AX back on the laptop at session end; the Pi's motion-server copy is stale → re-sync at next Pi power-up.

---

## 2026-08-19 — Session 7 (opening) — snapshot commit + new direction: realtime voice

- 17-day pause (operator vacation). This commit snapshots Session 6 **plus** the in-progress parallel workstream: the motion server grew record-over-protocol (`record_start/stop/abort`) and `--telemetry` (POS @10 Hz / HEALTH JSON) feeding a new `web/` UI (`web/server.py`, CONTRACT.md, DESIGN.md); stance + moves re-recorded 2026-08-19 (`*.bak-*` now gitignored).
- Operator verdict on voice loop v1: works, but the serial STT→brain→TTS chain is too slow — archive as-is, keep running. Next: rebuild on the **OpenAI Realtime API** (speech-to-speech, one WebSocket, server VAD, native tool calls) targeting sub-second responses and human-style interaction. Motion server + line protocol unchanged. Ring-mod cleared as a bottleneck by measurement (1.35 ms / 5 s clip).
- **Built same day: `perception/live_agent.py`** — hands-free speech-to-speech on **gpt-realtime-2.1** (GA websocket, raw `websockets`): semantic VAD + far_field noise reduction, native move tools (announce-then-move in one breath; success stays silent, failure explained aloud; calls from cancelled/barged-in responses are never executed), a voice `stop_moving` tool (12 V plug remains THE e-stop), barge-in with `conversation.item.truncate` so his memory matches what was heard, phase-exact ring-mod, auto-reconnect for the 60-min session cap, adaptive move timeouts, motion-link respawn, unsolicited server lines (TEMP_RELEASE…) printed live, `[prof]` response-latency metric.
- Validated live: selftest (session schema accepted), wiretest (greeting spoke through speakers; mic echo triggered a genuine VAD turn + truncate round-trip) — **measured response latency 1.08 s** vs v1's ~2.6–3.2 s. Reviewed by a 54-agent adversarial workflow: 17 confirmed findings fixed (incl. a deaf-mic regression and a barge-in race that would have executed just-cancelled moves). v1 `voice_agent.py` kept as the typed/push-to-talk fallback. Echo bit immediately in the lab → added `--ptt` (hold SPACE = talk, release = send; `turn_detection: null`, manual commit + response.create; holding SPACE mid-speech barges in) — zero echo, the lab default until the mic lives in the head. `--gate` = VAD-with-muting alternative.

---

## 2026-08-20 — Session 8 — Poppy learns WHO is talking (voice identity + people memory)

Operator ask: in a room full of people, can Poppy tell voices apart, address people by
name, and keep memories about them and their interactions? The Realtime API has no native
diarization (confirmed — `gpt-4o-transcribe-diarize` is REST-only), so this is a
client-side identity sidecar wrapped around the live agent.

- **`perception/identity.py` (new)**: ECAPA-TDNN voiceprints (speechbrain 1.1.0 + torch
  CPU; ~90 MB model auto-downloaded to `perception/models/`, Windows-safe
  COPY_SKIP_CACHE fetch — the default SYMLINK strategy needs admin). One JSON per person
  in `perception/people/` (gitignored: personal data): enrolled prints (pinned) +
  adaptive prints (learned from confident matches, redundancy eviction) + facts +
  last-seen. Matching = raw cosine against an enrollment-weighted centroid (0.6/0.4), on
  silence-trimmed audio; thresholds 0.40 confident (with 0.06 margin over the runner-up) /
  0.32 tentative. NOTE: 0.32, not SpeechBrain's textbook 0.25 — a measured cross-voice TTS
  pair scored 0.31 while genuine clips sit 0.42–0.75. Utterances under ~0.9 s of NET
  speech carry the previous speaker instead of guessing. CLI: `enroll` (4 read-aloud
  lines) / `list` / `test` / `forget` / `fact`.
- **Live-agent integration**: mic audio is mirrored locally; each finished turn is
  embedded and matched, and the model receives a `[voice-id] That was X speaking` system
  note BEFORE it answers. Latency trick: the embedding (~0.8 s CPU) starts ~2 s INTO the
  utterance (speaker of the head = speaker of the turn), so the note is usually free. In
  VAD modes the client now creates the responses (`create_response:false` + manual
  `response.create` after the note — the GA-documented manual flow); PTT commits manually
  as before. Slicing uses the documented cumulative-audio-timeline `audio_start_ms`
  (48 bytes/ms).
- **New model tools**: `enroll_speaker(name)` — a stranger says their name once and Poppy
  binds the voice that JUST spoke to it forever (also handles "I'm not X, I'm Y!"
  corrections; a same-name-different-voice collision becomes "Sara 2" instead of silently
  merging two humans). `remember_person(name, fact)` — silent memory saves mid-chat,
  auto-creating voiceless entries for people only heard ABOUT (e.g. Hiba). Anti-poisoning:
  adaptation gated at 0.50 + 0.10 margin, throttled per person, and skipped whenever
  Poppy's own speaker was audible at any point during the utterance.
- **Session memory loop**: a who-said-what transcript
  (`perception/people/_sessions/*.jsonl`) whose speaker labels wait for the voice match
  (transcription is async and usually arrives first — naive labelling attributed lines to
  the previous speaker). On exit gpt-4.1-mini mines it once for lasting facts (including
  what people said to EACH OTHER) and merges them into the person files. Roster + facts
  are re-injected at every (re)connect, so he greets known people by name even after the
  60-min reconnect wipes the model's context.
- **Validated**: 35 store/matching checks, 27 session-flow checks driving the real event
  handlers through a fake websocket, a real-speech test (OpenAI TTS voices vs live ECAPA +
  the fact extractor), selftest in both VAD and PTT modes, and a live wiretest. Two
  research/review workflows (3 + 54 agents) pinned the GA event shapes and thresholds and
  found 12 confirmed defects, all fixed — the worst: a voice-model failure mid-session
  used to leave the agent permanently MUTE (session said `create_response:false`, the
  client stopped creating them), plus stale-turn responses talking over the user,
  enrollment binding the wrong person's voice, and transcript misattribution poisoning
  memories.
- RUNBOOK §5b documents the people-teaching workflow. Deps: `pip install torch torchaudio
  speechbrain` (installed in .venv). Without them, or with `--no-id`, the agent runs
  voice-blind exactly as before.
