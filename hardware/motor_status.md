# Motor status — Phase 2 verdicts (bench evidence, 2026-07-27)

Method: laptop-direct bench (Plan B). USB2AX on **COM7** → SMPS2Dynamixel injector → chain. PSU verified 12.26 V open-circuit, center-positive; 11.2–11.8 V on the bus under idle load. Toolchain proven on a spare motor before touching the robot.

## Robot motors (scan `scripts/diagnostics/scan_bus.py`, Protocol 1.0)

| ID | Joint | Model | FW | Baud | Evidence | Verdict |
|---|---|---|---|---|---|---|
| 33 | abs_z | MX-28 | 40 | 1 M | answers, 34 °C | **OK** |
| 34 | bust_y | MX-28 | 40 | 1 M | answers, 34 °C | **OK** |
| 35 | bust_x | MX-28 | 40 | 1 M | answers, 38 °C | **OK** |
| 36 | head_z | AX-12 | 24 | 1 M | answers, 36 °C | **OK** |
| 37 | head_y | AX-12 | 24 | 1 M | answers, 35 °C | **OK** |
| 41 | l_shoulder_y | MX-28 | 40 | 1 M | answers, 34 °C | **OK** |
| 42 | l_shoulder_x | MX-28 | 40 | 1 M | answers, 38 °C | **OK** |
| 43 | l_arm_z | MX-28 | 40 | 1 M | answers, 38 °C | **OK** |
| 44 | l_elbow_y | MX-28 | 40 | 1 M | answers + **performed first motion** (12° and 20° bends, 15 °/s, ends compliant, ≤29 °C) | **OK — hero of the day** |
| 51 | r_shoulder_y | MX-28 | 40 | 1 M | answers, 33 °C | **OK** |
| 52 | r_shoulder_x | MX-28 | 40 | 1 M | answers, 37 °C | **OK** |
| 53 | r_arm_z | MX-28 | 40 | 1 M | answers, 37 °C | **OK** |
| 54 | r_elbow_y | MX-28AT (case) | — | — | no boot LED even fed directly; while connected, corrupts every reply on the bus (garbage bytes on all pings, both bauds); bus fully clean once unplugged | **DEAD — transceiver/electronics failure. The one true "burned motor".** |

**As-found configuration matches the official map exactly** (IDs, 1 Mbps, models). No archaeology needed — the 2013 unit is config-identical to current docs.

## Spares

| Item | Evidence | Status |
|---|---|---|
| Boxed MX-28AT | factory-fresh: **ID 1 @ 57600**, fw 41; bench-tested incl. commanded moves | **healthy — designated replacement for ID 54** (physical swap pending a PH0/PH1 screwdriver; then software rename ID 1→54 + baud→1 M) |
| Loose MX-28AT (was on table) | no boot LED in the same bench chain that later booted the boxed spare | suspect dead — probably a previously swapped-out failure; test again someday |
| AX-12A (in orange gripper) | untested | reserve for head joints |
| Dead ID 54 (after removal) | — | label "54 – dead", keep: firmware-recovery candidate (Dynamixel Wizard), gears = spares |

## Bench notes

- USB2AX answers at virtual **ID 253** (its own protocol feature) — not a motor; scanner ignores it.
- First garbled scans were caused by the dead 54 loading the data line — lesson: one corrupt device can silence a whole Dynamixel bus.
- Return-delay / EEPROM angle-limit audit + proper zero calibration of the replacement: to do during the Pi-era setup (poppy-configure), not needed for supervised relative moves.
