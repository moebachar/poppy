# Motor map — ground truth (Poppy Torso)

**Source:** `vendor/poppy-torso/software/poppy_torso/configuration/poppy_torso.json` @ commit `8073e69` (extracted 2026-07-27, Phase 0).
This file wins over `POPPY_TORSO_BRIEF.md` §2 in any disagreement. Cross-check result: **no disagreement** (see bottom).

## Bus / controller

| Setting | Value | Note |
|---|---|---|
| Controller | `upper_body_controller` | single controller, all 13 motors on one daisy-chain |
| Port | `"auto"` | pypot scans. Windows bench: `COMx` · Pi: `/dev/ttyACM0` (USB2AX) or `/dev/ttyUSB0` (U2D2) |
| sync_read | `true` | USB2AX-era optimization; if a U2D2 misbehaves at first bring-up, try `false` |
| Protocol | Dynamixel Protocol 1.0 | implied by MX-28 / AX-12 motor types |
| Baudrate | 1,000,000 bps | not stored in the JSON; pypot `DxlIO` default (`vendor/pypot/pypot/dynamixel/io/abstract_io.py:49`). Factory-fresh replacement motors ship at 57600 bps / ID 1 → must be reconfigured (Phase 2) |

## Motors (13)

Angles in degrees, pypot convention (offset & orientation applied). `Limits` = software angle limits from the config — never command outside them.

| Group | Name | ID | Type | Orientation | Offset | Limits | Physical joint |
|---|---|---|---|---|---|---|---|
| torso | `abs_z` | 33 | MX-28 | direct | 0.0 | −80 … +80 | waist rotation (whole torso turns left/right) |
| torso | `bust_y` | 34 | MX-28 | indirect | 0.0 | −46 … +23 | chest pitch (lean forward/back) |
| torso | `bust_x` | 35 | MX-28 | indirect | 0.0 | −40 … +40 | chest roll (lean left/right) |
| head | `head_z` | 36 | AX-12 | direct | 0.0 | −100 … +100 | head yaw ("no" shake) |
| head | `head_y` | 37 | AX-12 | indirect | −25.0 | 0 … +50 | head pitch (nod) |
| l_arm | `l_shoulder_y` | 41 | MX-28 | direct | +90 | −120 … +155 | L shoulder pitch (arm swing forward/up) |
| l_arm | `l_shoulder_x` | 42 | MX-28 | indirect | −90.0 | −105 … +110 | L shoulder roll (arm lift out to the side) |
| l_arm | `l_arm_z` | 43 | MX-28 | indirect | 0.0 | −90 … +90 | L upper-arm twist |
| l_arm | `l_elbow_y` | 44 | MX-28 | direct | −90.0 | −140 … 0 | L elbow bend |
| r_arm | `r_shoulder_y` | 51 | MX-28 | indirect | +90 | −155 … +120 | R shoulder pitch (arm swing forward/up) |
| r_arm | `r_shoulder_x` | 52 | MX-28 | indirect | +90.0 | −110 … +105 | R shoulder roll (arm lift out to the side) |
| r_arm | `r_arm_z` | 53 | MX-28 | indirect | 0.0 | −90 … +90 | R upper-arm twist |
| r_arm | `r_elbow_y` | 54 | MX-28 | indirect | −90.0 | 0 … +147 | R elbow bend |

Motorgroups: `torso`, `head`, `l_arm`, `r_arm`, `arms` = `l_arm` + `r_arm`.

## Sensors declared in config

| Name | Type | Note |
|---|---|---|
| camera | OpenCVCamera, index −1 (auto), 20 fps, 640×480 | config expects a camera → brief §10 Q5: look for a Pi/USB camera in Phase 1 |

## Cross-check vs POPPY_TORSO_BRIEF.md §2 (Phase 0, step 3)

- Names, IDs, groups: **match** (torso 33–35, head 36–37, left arm 41–44, right arm 51–54).
- Types: config `MX-28` = MX-28**AT** hardware (TTL variant); config `AX-12` = AX-12A. Both head motors are AX-12 in the ground truth — the "one may be AX-18" rumor does **not** appear in the config → settle by reading the case printing in Phase 1 (checklist §E).
- **No correction to the brief required.**

## Bench notes (Phase 2)

- Target register state per motor: ID per table above, baud 1 Mbps, return delay time 0 — `poppy-configure torso <name>` (ships with pypot) sets all three.
- A 2013-era unit may have as-found IDs ≠ this table. Record as-found state first (`motor_status.md`), then converge to this map — **one motor on the bus at a time** when changing IDs (brief §7.8).
