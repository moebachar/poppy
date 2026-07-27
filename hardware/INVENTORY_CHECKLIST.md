# Phase 1 — Physical inventory checklist (Fab Lab)

**Print this or open on phone. Work top to bottom. Tick every box.**
**Photos:** phone quality is fine → dump into `hardware/photos/phase1/`, named `<section><nn>_<desc>.jpg` (e.g. `A01_front.jpg`, `B02_usb2ax_back.jpg`).

## Rules (read first)

- ⛔ **POWER NOTHING in this phase.** Sole exception: §F measures the 12 V PSU **alone, open-circuit** (nothing connected to its output).
- Move joints **slowly and gently**, never force. Stop at hard resistance.
- Photo BEFORE opening/moving anything. Disassembled screws → labeled bags/cups.
- Flag suspects as you go: masking tape + marker on cables/motors.

**Kit:** phone/camera · multimeter · masking tape + marker · flashlight · small phillips screwdrivers · zip bags.

---

## A. Robot photo survey (~10 min)

- [ ] A01–A08: front, back, left, right, head close-up, inside head cavity, base/mount, top-down.
- [ ] Desk fixation: suction pad or clamp present? Condition? → A09
- [ ] Every 3D-printed part: cracks / breaks / warps? List each damaged part (location if name unknown): ......................................................
  - Expected: 2013-era plastic may be yellowed/brittle. Cosmetic ≠ structural — flag only cracks/breaks.
- [ ] Any serials / stickers / markings on the structure → photo.

## B. Head + box contents (~15 min) — answers brief §10 Q2/Q5

Photo EVERYTHING found, both sides, before removal.

- [ ] Single-board computer anywhere (head or box)? Model printed on PCB: ....................
- [ ] **USB2AX**: tiny USB-A dongle with a single 3-pin socket. Present? → B01/B02 both sides
- [ ] **SMPS2Dynamixel**: small PCB, DC barrel jack + 3-pin connector(s). Present? → B03
- [ ] Any other 3-pin hub / splitter PCB? → photo
- [ ] **12 V PSU brick**: present? → B04 photo of the LABEL (volts / amps / polarity symbol)
- [ ] microSD card(s): collect ALL (an old image is archaeology gold). Count: ......
- [ ] Camera module / webcam / speakers / screen? (robot config expects a camera)
- [ ] Spare cables / screws / horns / paper docs? → B09 photo of the whole spread

## C. Spare Raspberry Pi identification — answers §10 Q1, decides Phase 3 path

For EACH spare Pi at the lab:
- [ ] Silkscreen top side: "Raspberry Pi ___ Model ___" + RAM marking → one photo per board (C01, C02, …)
- Quick ID: micro-USB power + full-size HDMI = **Pi 3/3B+** ✅ · USB-C + 2× micro-HDMI = **Pi 4** ✅ · USB-C + power button = **Pi 5** ⛔ official image won't boot · tiny stick = **Zero** ⛔ too weak
- [ ] For the best candidate (Pi 3/4): its 5 V PSU available (micro-USB for Pi3, USB-C for Pi4)? microSD ≥16 GB? Ethernet cable?

Available Pis: ..................................................................

## D. Cable survey (~15 min, everything unpowered)

- [ ] Count 3-pin motor cables (Molex SPOX). In robot: ...... · loose/spare: ......
  (13 daisy-chained motors → expect ≥14 links incl. power injection; diagram: `docs/assembly-guides/poppy-torso/wiring_arrangement.md`)
- [ ] Inspect every reachable crimp: green/white corrosion? backed-out pins? cracked housing? → flag + photo worst ones (D01–D03)
- [ ] Gentle wiggle test at each connector: loose / falling out → flag.
- Suspect cables found: ......
- Expected: after ~12 years the crimps are suspect #1 (brief §3.3 rule 5). Flag generously.

## E. Motor survey — 13 expected (~20 min) — answers §10 Q3

Keep `hardware/motor_map.md` open alongside. Per motor: read the model printed on the case (MX-28AT / AX-12A / AX-18A?), note any ID sticker, then — everything UNPOWERED — rotate the joint slowly a few degrees each way where the structure allows:

- **smooth, firm resistance = OK** (an unpowered MX-28 backdrives stiffly — that's normal)
- clicking / grinding / notchy = gearbox suspect
- spins free, no resistance = stripped gears
- locked solid = do NOT force → flag

| Joint (map name) | Model on case | ID sticker | Rotation feel | Visual damage | Photo |
|---|---|---|---|---|---|
| abs_z (waist turn) | | | | | |
| bust_y (lean fwd/back) | | | | | |
| bust_x (lean sideways) | | | | | |
| head_z (head "no") | | | | | |
| head_y (head nod) | | | | | |
| l_shoulder_y (L arm swing fwd) | | | | | |
| l_shoulder_x (L arm lift side) | | | | | |
| l_arm_z (L upper-arm twist) | | | | | |
| l_elbow_y (L elbow) | | | | | |
| r_shoulder_y (R arm swing fwd) | | | | | |
| r_shoulder_x (R arm lift side) | | | | | |
| r_arm_z (R upper-arm twist) | | | | | |
| r_elbow_y (R elbow) | | | | | |

- [ ] Photo of each motor label where reachable (E01–E13, table order).
- [ ] Motor count ≠ 13, or a model ≠ map? Note: ..............................

## F. PSU electrical check — PSU ALONE, output unconnected

Skip if no 12 V PSU found (→ §H).

1. [ ] PSU label photo if not done (B04). Expected: 12 V, ≥5 A.
2. [ ] Plug PSU into mains, **nothing on its output**.
3. [ ] Multimeter: DC voltage, 20 V range. Black probe on barrel OUTSIDE (sleeve), red probe INSIDE (center pin).
4. [ ] Reading: .......... V — expected **+12.0 to +12.5 V, positive sign = center-positive**.
5. [ ] F01 photo of the multimeter display during measurement.
- ⚠️ Negative reading = center-negative → **do not use, flag loudly** (reverse polarity is the classic Dynamixel killer, brief §7.2).
- ⚠️ 0 V or far off → PSU dead → §H.

## G. Lab tools confirm

- [ ] Multimeter works (test on a AA battery ≈ 1.5 V).
- [ ] Bench power supply? Model/specs: .................... (useful substitute if it does 12 V / ≥5 A)
- [ ] Soldering iron · crimp tool · heat-shrink?
- [ ] 3D printer + filament available (for §A reprints)?

## H. Missing-parts tally → procurement (brief §3.4)

Tick what is MISSING after B–G, then order/scavenge:

- [ ] USB→Dynamixel adapter (no USB2AX found) → **Robotis U2D2** (~€50; Generation Robots / Robotis EU)
- [ ] Power injector (no SMPS2Dynamixel found) → SMPS2Dynamixel or U2D2 Power Hub Board
- [ ] 12 V ≥5 A PSU (none / dead / wrong polarity) → quality 12 V 5–6 A barrel PSU, center-positive (confirm jack size vs injector)
- [ ] Spare 3-pin cables → Molex SPOX 5264 3-pin, ~10× assorted 140–200 mm
- [ ] microSD ≥16 GB (class 10 / A1)
- [ ] Raspberry Pi 3B/3B+/4 + its 5 V PSU (if no usable spare at the lab)
- [ ] ⛔ Do NOT buy motors yet — Phase 2 evidence first (brief §3.3).

## I. Wrap-up

- [ ] All photos → `hardware/photos/phase1/`, renamed per scheme.
- [ ] Report findings to Claude → together fill `hardware/INVENTORY.md`, update brief §10, log the session.

**Phase 1 gate (DONE-WHEN):** `INVENTORY.md` complete with photos · missing-parts list resolved (in hand or ordered) · Pi model known.
