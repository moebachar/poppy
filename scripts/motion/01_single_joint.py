#!/usr/bin/env python
"""Motion ladder step 1 — one joint, small slow move, back, torque off.

Safety (brief §7): starts compliant, ends compliant (finally-block), slow speed,
target clamped inside the motor's own EEPROM angle limits minus a margin,
aborts on bad voltage (wrong PSU) or high temperature.

Usage:
    python 01_single_joint.py --port COM3 --id 44 [--delta 12] [--speed 20] [--yes]
"""
import argparse
import time

import pypot.dynamixel

MARGIN_DEG = 5.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--id", type=int, required=True, dest="mid")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--delta", type=float, default=12.0, help="degrees to move (default 12)")
    ap.add_argument("--speed", type=float, default=20.0, help="deg/s (default 20, keep low)")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        mid = args.mid
        if not dxl.ping(mid):
            raise SystemExit(f"id {mid} does not answer on {args.port} @ {args.baud}")

        model = dxl.get_model((mid,))[0]
        volt = dxl.get_present_voltage((mid,))[0]
        temp = dxl.get_present_temperature((mid,))[0]
        p0 = dxl.get_present_position((mid,))[0]
        lo, hi = dxl.get_angle_limit((mid,))[0]

        print(f"id {mid} ({model})  pos {p0:.1f}°  limits [{lo:.0f}, {hi:.0f}]  {volt:.1f} V  {temp:.0f} °C")
        if not 10.0 <= volt <= 13.5:
            raise SystemExit(f"ABORT: bus voltage {volt:.1f} V is not ~12 V — wrong PSU?")
        if temp > 50:
            raise SystemExit(f"ABORT: motor already at {temp:.0f} °C — let it cool")

        target = min(max(p0 + args.delta, lo + MARGIN_DEG), hi - MARGIN_DEG)
        if abs(target - p0) < 2:  # no room that way -> go the other way
            target = min(max(p0 - args.delta, lo + MARGIN_DEG), hi - MARGIN_DEG)
        print(f"plan: {p0:.1f}° -> {target:.1f}° -> back, at {args.speed:.0f} °/s")

        if not args.yes:
            if input("hand near the power switch? type 'go': ").strip().lower() != "go":
                raise SystemExit("aborted")

        try:
            dxl.set_moving_speed({mid: args.speed})
            dxl.enable_torque((mid,))
            for goal in (target, p0):
                dxl.set_goal_position({mid: goal})
                t_end = time.time() + 6
                while time.time() < t_end:
                    if abs(dxl.get_present_position((mid,))[0] - goal) < 2:
                        break
                    time.sleep(0.05)
                time.sleep(0.3)
        finally:
            dxl.disable_torque((mid,))
            t = dxl.get_present_temperature((mid,))[0]
            print(f"torque OFF (compliant). temp now {t:.0f} °C")


if __name__ == "__main__":
    main()
