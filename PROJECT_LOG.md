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
