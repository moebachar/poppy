#!/usr/bin/env python
"""Motion ladder step 3 — stand stiff and STAY stiff (long hold).

Freezes every motor at its current position (one-by-one writes), reads back
TORQUE_ENABLE from each motor as proof, then holds for --minutes (default 15)
with a temperature watchdog printing status every 30 s. Ctrl+C or timeout or
overheat -> release compliant.
"""
import argparse
import time

import pypot.dynamixel

TEMP_SOFT, TEMP_HARD = 48, 52


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--minutes", type=float, default=15.0)
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = [i for i in dxl.scan(list(range(60))) if i < 250]
        print(f"motors: {ids}", flush=True)
        try:
            freeze = dict(zip(ids, dxl.get_present_position(ids)))
            for i in ids:
                dxl.set_moving_speed({i: 40})
                dxl.set_goal_position({i: freeze[i]})
                dxl.enable_torque((i,))
            time.sleep(0.3)
            states = dict(zip(ids, dxl.is_torque_enabled(ids)))
            off = [i for i, on in states.items() if not on]
            print(f"TORQUE READ-BACK: {'ALL ON' if not off else f'STILL OFF: {off}'}", flush=True)
            print("HOLDING NOW — push test welcome", flush=True)

            t_end = time.time() + args.minutes * 60
            while time.time() < t_end:
                temps = dxl.get_present_temperature(ids)
                worst = max(temps)
                states = dxl.is_torque_enabled(ids)
                n_on = sum(states)
                print(f"holding: {n_on}/{len(ids)} stiff, hottest {worst:.0f} C", flush=True)
                if worst >= TEMP_HARD:
                    print("overheat -> releasing", flush=True)
                    break
                time.sleep(30)
        finally:
            dxl.disable_torque(ids)
            print("released (compliant)", flush=True)


if __name__ == "__main__":
    main()
