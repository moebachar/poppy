#!/usr/bin/env python
"""Jog ONE motor by raw degrees, to map raw direction -> physical direction.

    python scripts/diagnostics/jog.py --port COM7 --id 41 --delta -25

Prints the motor's EEPROM angle limits, freezes it at its current position,
moves by delta (raw), holds, returns, releases. 'reached vs asked' exposes
any silent clamping by the motor's internal limit registers.
"""
import argparse
import time

import pypot.dynamixel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--id", type=int, required=True, dest="mid")
    ap.add_argument("--delta", type=float, required=True)
    ap.add_argument("--speed", type=float, default=15.0)
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        mid = args.mid
        print(f"EEPROM angle limits: {dxl.get_angle_limit((mid,))[0]}")
        p = dxl.get_present_position((mid,))[0]
        print(f"present: {p:.1f}")
        dxl.set_moving_speed({mid: args.speed})
        dxl.set_goal_position({mid: p})
        dxl.enable_torque((mid,))
        time.sleep(0.3)
        goal = p + args.delta
        print(f"asking raw goal: {goal:.1f}", flush=True)
        dxl.set_goal_position({mid: goal})
        time.sleep(abs(args.delta) / args.speed + 1.0)
        now = dxl.get_present_position((mid,))[0]
        print(f"reached: {now:.1f}  (asked {goal:.1f})")
        time.sleep(1.0)
        dxl.set_goal_position({mid: p})
        time.sleep(abs(args.delta) / args.speed + 1.0)
        dxl.disable_torque((mid,))
        print("released")


if __name__ == "__main__":
    main()
