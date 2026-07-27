#!/usr/bin/env python
"""Stand still — from ANY position, slowly return to the recorded stance and hold it.

Flow: freeze in place (no jump) -> verify torque via read-back -> travel every
joint slowly to the saved pose (default scripts/motion/poses/stand.json) ->
hold stiff with temp watchdog + 30 s status prints -> release on timeout,
overheat or Ctrl+C.

    python 03_stand_still.py --port COM7                  # goto 'stand', hold 30 min
    python 03_stand_still.py --port COM7 --minutes 120
    python 03_stand_still.py --port COM7 --freeze-only    # old behavior: stiffen where it is
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
    ap.add_argument("--pose", default="stand")
    ap.add_argument("--freeze-only", action="store_true",
                    help="hold current position instead of traveling to the pose")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--speed", type=float, default=20.0)
    ap.add_argument("--max-travel", type=float, default=100.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = [i for i in dxl.scan(list(range(60))) if i < 250]
        print(f"motors: {ids}", flush=True)
        current = dict(zip(ids, dxl.get_present_position(ids)))

        if args.freeze_only:
            target = dict(current)
        else:
            pose = json.loads((POSES_DIR / f"{args.pose}.json").read_text())
            target = {int(k): v for k, v in pose["positions"].items() if int(k) in ids}
            missing = [i for i in ids if i not in target]
            if missing:
                print(f"note: no saved position for {missing}, freezing them in place", flush=True)
                target.update({i: current[i] for i in missing})
            too_far = {i: round(abs(current[i] - target[i]), 1)
                       for i in target if abs(current[i] - target[i]) > args.max_travel}
            if too_far and not args.force:
                raise SystemExit(f"refusing: joints too far from pose {too_far} (use --force)")

        try:
            for i in ids:  # freeze at current first: no jump at torque-on
                dxl.set_moving_speed({i: args.speed})
                dxl.set_goal_position({i: current[i]})
                dxl.enable_torque((i,))
            time.sleep(0.3)
            off = [i for i, on in zip(ids, dxl.is_torque_enabled(ids)) if not on]
            print(f"TORQUE READ-BACK: {'ALL ON' if not off else f'STILL OFF: {off}'}", flush=True)

            if not args.freeze_only:
                print("traveling to pose...", flush=True)
                for i in ids:
                    dxl.set_goal_position({i: target[i]})
                t_end = time.time() + 30
                err = 999
                while time.time() < t_end:
                    now = dict(zip(ids, dxl.get_present_position(ids)))
                    err = max(abs(now[i] - target[i]) for i in ids)
                    if err < 3:
                        break
                    time.sleep(0.4)
                print(f"stance reached (max error {err:.1f} deg)", flush=True)

            print("STANDING — holding, push test welcome", flush=True)
            t_end = time.time() + args.minutes * 60
            while time.time() < t_end:
                temps = dxl.get_present_temperature(ids)
                n_on = sum(dxl.is_torque_enabled(ids))
                print(f"holding: {n_on}/{len(ids)} stiff, hottest {max(temps):.0f} C", flush=True)
                if max(temps) >= TEMP_HARD:
                    print("overheat -> releasing", flush=True)
                    break
                time.sleep(30)
        finally:
            dxl.disable_torque(ids)
            print("released (compliant)", flush=True)


if __name__ == "__main__":
    main()
