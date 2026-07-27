# Phase 1 — Physical inventory checklist (Fab Lab) — v2

Written for someone with **no robotics/electronics experience**. Two things to hold on to:

1. **While nothing is powered, you cannot break anything** by looking, photographing, or gently moving parts. The whole phase is unpowered except one PSU test (§F) which has its own step-by-step box.
2. **Universal rule: unsure what something is or what I'm asking? → photo it (or describe it), tick nothing, move on.** I'll identify parts from photos or descriptions. We can also do this live: go section by section and send me things as you go.

**No phone camera? Use this laptop.** It has a working webcam (verified) — press Win, type "Camera", Enter; spacebar takes a photo. Photos land in `Pictures\Camera Roll` — just tell me when you've taken a batch and I'll move + rename them into `hardware/photos/phase1/` myself. Tips: good light, hold the part 20–30 cm from the webcam, steady for a second. Small parts: hold them up to the camera one at a time.

**Even better than a photo, when there's printed text** (motor model, PSU label, board name): just read it and type it to me — more reliable than any webcam shot.

**When a photo is impractical** (whole-robot angles with a laptop are awkward): describe in words — size, color, what connectors it has — the gallery images below give you the vocabulary. Whole-robot photos can wait for a borrowed phone another day; they're documentation, not blockers.

**Photo naming:** `<section><nn>_<desc>.jpg` → `A01_front.jpg`, `B02_mystery_green_board.jpg`, … (skip renaming if using Camera Roll — I'll do it).

---

## 📷 Picture gallery — open these BEFORE the lab

These are local files from the official Poppy docs (click from VS Code / file explorer). They show what you're hunting for:

| Open this | What it shows |
|---|---|
| `docs/assembly-guides/poppy-torso/img/dynamixel-setup.jpg` | **The key photo.** Left to right: black power cable with round plug → **SMPS2Dynamixel** (small green "power injector" board in a clear case) → a **motor** (black box, "MX-28AT" printed on it). Bottom-left: the **USB2AX** (green USB-stick with a tiny white 3-pin plug). The two green things are the "missing switch / connecting device" your colleagues mentioned. |
| `docs/assembly-guides/poppy-torso/img/parts_electronics.JPG` | The **2013-era electronics kit, every part labeled** — including USB2AX (bottom right) and the "Hardkernel Odroid U3" — the old brain board that early Poppys used instead of a Raspberry Pi. If anything in the box resembles any of these: photo. |
| `docs/assembly-guides/poppy-torso/img/screwed_SMPS.JPG` | SMPS2Dynamixel close-up: green board, two black cylinders (capacitors), white 3-pin sockets. |
| `docs/assembly-guides/poppy-torso/img/head_odroid.JPG` | **Inside of an open head, 2013 era** (Odroid board + black cables). Our head may have looked like this before its board was removed. |
| `docs/assembly-guides/poppy-torso/img/raspi3_head.jpg` | Outside of the later Raspberry-Pi-3-era head. |
| `docs/assembly-guides/poppy-torso/img/power_wiring.JPG` | SMPS boards + black daisy-chain cables mounted on a robot. |
| `docs/assembly-guides/poppy-torso/img/motor_naming_convention.jpg` | Every joint's name + ID number. It shows the full humanoid — **our Torso is the upper half only** (abs_z and up). |
| `docs/img/humanoid/torso-motors.png` · `torso-wires.png` | Clean diagrams: which motor is which, and how the cables run, for OUR robot. |

## 📖 Mini-glossary

- **Motor / servo / "Dynamixel"** — each joint is a black plastic box, 3–5 cm. Its model name (MX-28AT, AX-12A…) is printed in small white text on the side of the case.
- **3-pin cable** — black cable; each end is a small white plastic connector (fingernail-sized) with 3 metal contacts. The robot's entire nervous system is these cables, chained from motor to motor (a "daisy-chain").
- **Crimp** — the tiny metal clip where a wire enters a white connector. The weakest point; ages badly.
- **Corrosion** — green/white crusty or powdery deposit on metal. Bad sign → photo it.
- **Barrel jack** — round power plug like old laptop chargers: metal sleeve outside, hole with a pin inside.
- **Board / PCB** — a green circuit board.
- **PSU** — power supply, i.e. a wall-adapter brick.

**Kit:** phone · multimeter (yellow/grey handheld tester with a dial and two probe wires — the lab has one) · masking tape + marker · flashlight · small phillips screwdrivers · zip bags for anything loose.

---

## A. Robot photo survey (~10 min)

- [ ] A01–A08: front, back, left side, right side, head close-up, **inside the head opening**, base/mount, top-down.
- [ ] How does it attach to a desk? (suction pad / clamp / nothing) → A09
- [ ] Look over every white plastic part: cracks, broken pieces, warping? List what/where (plain words fine — "left shoulder bracket cracked"): ......................................................
  - Expected: 12-year-old plastic may be yellowed. Ugly is fine — only cracks/breaks matter.
- [ ] Any stickers, serial numbers, handwriting on the robot → photo.

## B. Head + box contents (~15 min)

Empty the head and any boxes/bags that came with the robot. **Photo everything found, both sides, before moving it.** Compare against the gallery photos.

- [ ] Any computer board? (credit-card-sized green board — Raspberry Pi has its name printed on it; the Odroid U3 looks like the one in `parts_electronics.JPG`). Text printed on it: ....................
- [ ] **USB2AX** — green USB stick with a tiny white 3-pin socket (see gallery). Found? → B01/B02
- [ ] **SMPS2Dynamixel** — small green board with a barrel-jack socket + white 3-pin sockets (see gallery). Found? → B03
- [ ] Any other small board with several white 3-pin sockets (a "hub")? → photo
- [ ] **12 V wall/desk power brick**? → B04 = photo of its LABEL (we need the printed volts/amps and the little ⊕–•–⊖ polarity symbol)
- [ ] Memory cards (microSD, fingernail-sized, or eMMC module like in `parts_electronics.JPG`): collect ALL — an old card can tell us what software this robot ran. Count: ......
- [ ] Small camera module / webcam / speakers / little screen? → photo
- [ ] Loose cables, screws, metal discs (motor "horns"), paper documents? → B09 photo of the whole spread

## C. Raspberry Pi identification — decides how we build the new brain

For EACH spare Raspberry Pi the lab has:
- [ ] Photo of the board's top side (C01, C02, …) — the model ("Raspberry Pi 3 Model B+" etc.) is printed directly on the green board.
- Quick ID if unreadable: micro-USB power + full-size HDMI = **Pi 3** ✅ · USB-C power + 2 small micro-HDMI = **Pi 4** ✅ · USB-C + a tiny power button = **Pi 5** ⛔ (official image won't boot on it) · gum-stick-sized = **Pi Zero** ⛔ (too weak)
- [ ] For the best candidate (Pi 3 or 4): does the lab also have its 5 V charger (micro-USB for Pi 3, USB-C for Pi 4)? A microSD card ≥16 GB? An Ethernet cable?

Available Pis: ..................................................................

## D. Cable survey (~15 min, nothing powered)

- [ ] Count the black 3-pin cables: on the robot ...... · loose/spare ......
  (13 motors chained together → expect 14 or more. Diagram: `docs/img/humanoid/torso-wires.png`)
- [ ] Look at every white connector you can reach: green/white crust (corrosion)? metal contacts pushed out? cracked plastic? → mark with tape + photo the worst (D01–D03)
- [ ] Hold each connector and wiggle gently: if it falls out or feels loose → tape-flag it.
- Suspects found: ......
- Expected: after 12 years the crimps are the #1 suspect for "dead" motors. Flag generously — cables are cheap.

## E. Motor survey — 13 motors expected (~20 min)

Keep `hardware/motor_map.md` + `motor_naming_convention.jpg` open to know which joint is which. For each motor:

1. Read the model printed in white text on the black case: MX-28AT? AX-12A? AX-18A? something else?
2. Any handwritten sticker/number on it?
3. **Everything unpowered:** hold the limb next to that joint and move it slowly a few degrees the way the joint is obviously meant to move, then back. What does it feel like?
   - **smooth but firm resistance = OK** (unpowered motors resist — that's normal, don't fight it)
   - clicking / crunching / bumpy = gearbox suspect
   - moves totally freely like a loose hinge = stripped gears
   - won't move at all = do NOT force → flag

| Joint (map name) | Model on case | Sticker | Feel | Visible damage | Photo |
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

- [ ] E01–E13: photo of each motor's label where reachable (same order as the table).
- [ ] Fewer/more than 13 motors, or a model not in the map? Note it: ..............................

## F. PSU test — the ONLY powered step. PSU alone, nothing connected to it.

Skip if no 12 V brick was found (→ §H). This is safe: the brick's 12 V output cannot hurt you. The only real rule: **probe only the output plug, never the wall-plug prongs.**

**Multimeter how-to (any standard handheld one):**
1. [ ] Plug the brick into the wall. Its output cable (barrel jack) connects to **nothing**.
2. [ ] Multimeter probes: black probe into the socket marked **COM** · red probe into the socket marked **V** (often "VΩmA"). NOT the socket marked 10A/20A.
3. [ ] Turn the dial to **DC volts**: symbol **V⎓** (a V with a straight line + dashed line). If there are numbers, pick **20**. If your meter says "auto", that's fine.
4. [ ] Touch the **red probe tip inside the barrel's center hole**, and the **black probe tip against the outer metal sleeve**. Hold both steady.
5. [ ] Read the display: .......... V
   - Expected: **+12.0 to +12.5** → good, "center-positive".
   - **A minus sign** (−12) → center-negative → ⚠️ **do not ever use this brick, flag it loudly** — reversed polarity is the classic Dynamixel motor killer and possibly this robot's origin story.
   - 0 or garbage → brick is dead → §H.
6. [ ] F01: photo of the display while measuring if a colleague can help — otherwise just type me the exact number including the sign (e.g. "+12.14" or "−12.1"). The sign is the whole point.
- Meter looks different / display confusing → photo the meter's dial + display and ask me.

## G. Lab tools check

- [ ] Multimeter works? (quick test: dial on V⎓, probes on the two ends of any AA battery → ~1.5 V)
- [ ] Bench power supply (box with knobs + voltage display)? Model/specs: ....................
- [ ] Soldering iron? Crimping tool? Heat-shrink?
- [ ] 3D printer + filament (to reprint broken white parts)?

## H. What's missing → shopping list (mark after B–G)

- [ ] No USB2AX found → buy **Robotis U2D2** (~€50 — Generation Robots or Robotis EU webshop)
- [ ] No SMPS2Dynamixel found → buy **SMPS2Dynamixel** or **U2D2 Power Hub Board**
- [ ] No usable 12 V brick → buy 12 V / 5–6 A PSU, center-positive barrel plug
- [ ] Spare 3-pin cables → "Molex SPOX 5264 3-pin" Dynamixel cables, ~10× of 140–200 mm
- [ ] No microSD ≥16 GB → buy one (class 10 / A1)
- [ ] No Pi 3/4 at the lab → buy Pi 4 + official USB-C PSU
- [ ] ⛔ Do NOT buy motors yet — even if colleagues say some are burned. Phase 2 will test each motor and prove it.

## I. Wrap-up

- [ ] All photos → `hardware/photos/phase1/`, renamed per the scheme (approximate is fine).
- [ ] Come back to me with the photos + your notes → I fill `hardware/INVENTORY.md`, we update the brief's open questions and log the session.

**Phase 1 is done when:** inventory written up with photos · everything missing is in hand or ordered · we know which Pi we'll use.
