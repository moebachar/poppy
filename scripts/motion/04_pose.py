#!/usr/bin/env python
"""Motion ladder step 4 — record and replay named poses.

    python 04_pose.py --port COM7 save stand          # capture current pose
    python 04_pose.py --port COM7 goto stand          # slowly return to it, hold, release
    python 04_pose.py --port COM7 goto stand --hold-minutes 30
    python 04_pose.py --port COM7 release

Poses live in scripts/motion/poses/<name>.json. Writes are one motor at a
time (house rule on this bus). Sanity guard: goto refuses any joint further
than --max-travel degrees from its target unless --force.
"""
import argparse
import json
import time
from pathlib import Path

import pypot.dynamixel

POSES_DIR = Path(__file__).parent / "poses"
TEMP_HARD = 52


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("action", choices=("save", "goto", "release"))
    ap.add_argument("name", nargs="?", default="stand")
    ap.add_argument("--speed", type=float, default=20.0)
    ap.add_argument("--hold-minutes", type=float, default=10.0)
    ap.add_argument("--max-travel", type=float, default=100.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    pose_file = POSES_DIR / f"{args.name}.json"

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = [i for i in dxl.scan(list(range(60))) if i < 250]

        if args.action == "save":
            pos = dict(zip(ids, dxl.get_present_position(ids)))
            POSES_DIR.mkdir(exist_ok=True)
            pose_file.write_text(json.dumps(
                {"name": args.name, "saved": time.strftime("%Y-%m-%d %H:%M"),
                 "positions": {str(i): round(p, 2) for i, p in pos.items()}}, indent=2))
            print(f"saved {len(pos)} joints -> {pose_file}")
            return

        if args.action == "release":
            dxl.disable_torque(ids)
            print("released (compliant)")
            return

        # goto
        target = {int(k): v for k, v in
                  json.loads(pose_file.read_text())["positions"].items()}
        target = {i: p for i, p in target.items() if i in ids}
        current = dict(zip(ids, dxl.get_present_position(ids)))
        too_far = {i: round(abs(current[i] - target[i]), 1)
                   for i in target if abs(current[i] - target[i]) > args.max_travel}
        if too_far and not args.force:
            raise SystemExit(f"refusing: joints too far from target {too_far} (use --force)")

        try:
            for i in target:                      # freeze at current first (no jump)
                dxl.set_moving_speed({i: args.speed})
                dxl.set_goal_position({i: current[i]})
                dxl.enable_torque((i,))
            time.sleep(0.2)
            for i in target:                      # then head for the pose, slowly
                dxl.set_goal_position({i: target[i]})
            t_end = time.time() + 20
            while time.time() < t_end:
                now = dict(zip(ids, dxl.get_present_position(ids)))
                err = max(abs(now[i] - target[i]) for i in target)
                if err < 3:
                    break
                time.sleep(0.3)
            print(f"pose reached (max error {err:.1f} deg) — holding {args.hold_minutes:.0f} min")
            t_end = time.time() + args.hold_minutes * 60
            while time.time() < t_end:
                temps = dxl.get_present_temperature(ids)
                if max(temps) >= TEMP_HARD:
                    print("overheat -> releasing")
                    break
                on = sum(dxl.is_torque_enabled(ids))
                print(f"holding: {on}/{len(ids)} stiff, hottest {max(temps):.0f} C", flush=True)
                time.sleep(30)
        finally:
            dxl.disable_torque(ids)
            print("released (compliant)")


if __name__ == "__main__":
    main()
