# Poppy Torso — joint command cheatsheet

For deriving `keyframer.py` / sim commands (`<joint> <degrees>`). Same names and degree-space
as the exported move files. Ranges come from the official robot config — **stay inside them**
(the keyframer does not clamp for you). 0° everywhere = rest pose (standing, arms down).

Visual reference: `docs/assembly-guides/poppy-torso/img/motor_naming_convention.jpg`
(shows the full humanoid — our Torso is the upper half, `abs_z` and above).

| Joint | Motion (plain English) | Range (°) |
|---|---|---|
| `abs_z` | waist rotation — whole upper body turns left/right | −80 … +80 |
| `bust_y` | chest pitch — lean forward/backward | −46 … +23 |
| `bust_x` | chest roll — tilt left/right | −40 … +40 |
| `head_z` | head yaw — "no" shake | −100 … +100 |
| `head_y` | head pitch — nod (narrow range!) | 0 … +50 |
| `l_shoulder_y` | left arm swing — forward/up ↔ backward | −120 … +155 |
| `l_shoulder_x` | left arm lift — out to the side ↔ across body | −105 … +110 |
| `l_arm_z` | left upper-arm twist (rotates the forearm's plane) | −90 … +90 |
| `l_elbow_y` | left elbow bend | −140 … 0 |
| `r_shoulder_y` | right arm swing — forward/up ↔ backward | −155 … +120 |
| `r_shoulder_x` | right arm lift — out to the side ↔ across body | −110 … +105 |
| `r_arm_z` | right upper-arm twist | −90 … +90 |
| `r_elbow_y` | right elbow bend | 0 … +147 |

## The three things that bite

1. **Left and right are sign-mirrored.** Same physical motion = opposite sign on the other arm.
   Clearest example: the LEFT elbow bends toward **−140**, the RIGHT elbow bends toward **+147**
   (0 = straight arm on both). The shoulder ranges mirror the same way.
2. **Signs are cheap to test in the sim** — type `l_shoulder_x 30`, watch which way it goes,
   negate if wrong. The simulator is your ground truth; nothing you do there touches hardware.
3. **`r_elbow_y` is currently dead on the real robot** (motor 54, replacement pending a
   screwdriver). Use it freely in the sim — the execute script automatically skips missing
   motors on hardware — just know the real right forearm won't bend yet.

## Recipe hints

- Wave, right... left arm: `l_shoulder_x 80` (arm out/up) + `l_elbow_y -90` (forearm up),
  then alternate `l_arm_z ±25` for the wag, captures between each.
- Nod yes: `head_y 35` ↔ `head_y 5`. Shake no: `head_z ±40`.
- Deep reference (bus IDs, raw offsets, bench data): `hardware/motor_map.md` ·
  live health: `hardware/motor_status.md`.
