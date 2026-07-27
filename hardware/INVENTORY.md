# Hardware inventory — as found (Phase 1, 2026-07-27)

Filled from Jalaleddin's Fab Lab session + 12 photos (`photos/phase1/`, verified by Claude one by one).

## Summary verdict

**Far better than the rumors.** The robot is structurally complete (both arms, head with screen/camera/speakers, suction base), every motor backdrives smoothly, the full electronics chain is present (USB2AX ×2, SMPS2Dynamixel-type injector, 12 V PSU, cables), and there are real spares (AX-12A in a gripper, a loose MX-look motor, a free Raspberry Pi 3). **Nothing blocking is missing — €0 procurement to reach first motion.** The "burned motors" rumor has zero physical evidence so far; Phase 2 scan will settle it.

Two watch-outs:
1. **The table also holds a Poppy Ergo Jr ecosystem stash** (new XL-320 servos ×~8, small-connector 3P cables, Dexter distance sensors, googly eyes, 3P Extension PCBs, orange gripper parts, and a Pi 3 + SD running an Ergo Jr arm). XL-320 gear is **NOT compatible** with the Torso (different connector, voltage, protocol). Do not mix. The Ergo Jr's own Pi + SD card stays untouched (it's a working lab setup).
2. **Multiple black power bricks on one table.** Only the verified 12 V one may ever touch the motor bus. Label + multimeter check is mandatory before first power-on (a 19 V laptop brick on the bus = dead servos).

## A. Structure & 3D-printed parts

- Complete torso: both arms with passive hands, head, spine, cone base with **suction pad** (A07). Fixation OK.
- No cracks/breaks reported; plastic looks sound in photos (A01–A08). "Poppy" handwritten on chest plate.
- Head shell = the **screen-era head**: face half contains a small screen module + red/black wiring (A06, B03); back half has port cutout + vents, **computer bay empty** (A05).

## B. Head + box contents

| Item | Status | Evidence |
|---|---|---|
| USB2AX (USB→Dynamixel TTL) | **FOUND ×2** (possibly 3) | B02 right side — green PCB dongles, USB-A + 3-pin socket |
| SMPS2Dynamixel (12 V injector) | **FOUND** (≥1; a second similar green board in a ziplock to confirm) | B02 — green board with barrel jack + capacitor + 3-pin sockets |
| 12 V PSU | **PRESENT — label/polarity check pending** | B03/B04 — large laptop-style brick + red/black DC plug cable assembly; colleague reports it works |
| Single-board computer in head | **ABSENT** (bay empty — as expected) | A05 |
| Camera | **FOUND** — in head, above screen | A01; operator confirms webcam in head |
| Speakers | **FOUND** — left + right in head | operator; wiring visible A06 |
| Screen | **FOUND** — in face shell (official small screen, discontinued part) | A06, B01 |
| microSD cards | Ergo Jr's card (off-limits); others "findable around the lab" | operator |
| Screws/small parts | Bags of ROBOTIS screw kits present | B01/B04 |
| Misc lab context (not ours) | TurtleBot3, VR controller, 3D-print service bag (translucent part "R-…") | B01 |

## C. Raspberry Pi(s)

- **Pi 3 #1 — free, in a box → OURS for Phase 3.** A small retail-boxed black PSU on the table looks like an official RPi supply — to confirm (label: 5.1 V).
- Pi 3 #2 — wired to the lab's **Poppy Ergo Jr** arm, with its SD card → **off-limits** (working setup, and its image is for Ergo Jr anyway).

## D. Cables

- All 3-pin bus cables present on the robot; **some unplugged** (visible dangling in A01–A08) → chain must be re-seated before scan (wiring diagram: `docs/img/humanoid/torso-wires.png`).
- Condition reported fine; no corrosion noted.
- Two new ROBOTIS bags "Robot Cable-3P 60mm/100mm 10pcs" (B02): **if** their connector matches the robot's motor sockets, that's a free stock of spare bus cables; if they're the smaller XL-320 type, they're Ergo Jr stock. → 10-second physical check pending.
- A USB-A plug dangles from the robot near the base (A01) — likely the bus end that went to the missing computer, possibly with a USB2AX already attached. To trace.

## E. Motors (13 expected)

- All joints **backdrive smoothly** — no grinding, no free-spin, none seized. Excellent after 12 years.
- Models read: **MX-28AT everywhere visible; neck = AX-12A** (matches the map: 11× MX-28 + 2× AX-12 — the second AX-12 (`head_z`) sits under the head, hard to see on the mounted robot).
- Original **ID stickers** present, some erased; "37" clearly visible on the neck motor (B03) = `head_y` per map → original addressing scheme intact.
- As-found IDs: unknown until the Phase 2 scan (stickers ≠ proof).
- **Spares:** AX-12A inside the orange gripper (B02) — compatible with head joints; one loose black motor on the table (B03/B04) — model to read, possibly MX-28AT.
- The ~8 boxed XL-320s are **not** Torso spares (Ergo Jr only).

## F. PSU

- Large brick + DC plug cable assembly present; colleague says it works.
- **Pending before first power:** read label (must say 12 V; note amps), multimeter sign check on the barrel (+12 expected, center-positive). Mandatory because several look-alike bricks share the table.

## G. Lab tools

- Multimeter ✔ · bench DC supply ("générateur DC") ✔ · soldering station ✔ · Ultimaker 3D printer + white PLA ✔

## H. Procurement decisions

- **Nothing to buy for bench bring-up and first motion.** All §3.4 items found in-lab.
- Later (Phase 3): a microSD ≥16 GB for our Pi 3 (find in lab or buy), Ethernet cable.

## Photos index

| File | Content |
|---|---|
| A01_front.jpg | Robot front, head with screen + camera dot |
| A02_left_side.jpg | Left profile |
| A03_back.jpg | Back; head back panel with empty port cutout |
| A04_right_side.jpg | Right profile |
| A05_head_back_closeup.jpg | Head back close-up: vents, empty computer bay |
| A06_head_open_screen.jpg | Head open: screen module + wiring in face shell |
| A07_base_suction_pad.jpg | Base underside: suction pad |
| A08_back_tilted.jpg | Back view tilted, spine motors |
| B01_parts_table_overview.jpeg | All found parts on table (robot, PSUs, Ergo Jr stash, boxes) |
| B02_electronics_closeup.jpeg | **Key photo**: USB2AX dongles, injector board(s), AX-12A gripper, XL-320 bags, cable bags |
| B03_robot_flat_psus.jpeg | Robot flat; neck motor "37" sticker; PSU bricks; loose spare motor |
| B04_parts_table_wide.jpeg | Wide angle of the whole spread |
