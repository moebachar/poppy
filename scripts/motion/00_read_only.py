#!/usr/bin/env python
"""Motion ladder step 0 — read everything, move nothing (brief §5 Phase 5).

Pure reads: positions, voltage, temperature of every motor on the bus.
Never writes a register, never enables torque.

Usage:
    python 00_read_only.py --port COM3 [--baud 1000000] [--max-id 60]
"""
import argparse

import pypot.dynamixel

EXPECTED = {
    33: "abs_z", 34: "bust_y", 35: "bust_x",
    36: "head_z", 37: "head_y",
    41: "l_shoulder_y", 42: "l_shoulder_x", 43: "l_arm_z", 44: "l_elbow_y",
    51: "r_shoulder_y", 52: "r_shoulder_x", 53: "r_arm_z", 54: "r_elbow_y",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--max-id", type=int, default=60)
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = dxl.scan(list(range(args.max_id + 1)))
        print(f"{len(ids)} motor(s): {ids}\n")
        if not ids:
            return
        pos = dxl.get_present_position(ids)
        volt = dxl.get_present_voltage(ids)
        temp = dxl.get_present_temperature(ids)
        model = dxl.get_model(ids)
        print(f"{'id':>3} {'name':14s} {'model':8s} {'pos °':>8} {'V':>6} {'°C':>4}")
        for i, m, p, v, t in zip(ids, model, pos, volt, temp):
            name = EXPECTED.get(i, "??")
            flag = " <-- HOT" if isinstance(t, (int, float)) and t > 50 else ""
            print(f"{i:3d} {name:14s} {str(m):8s} {p:8.1f} {v:6.1f} {t:4.0f}{flag}")


if __name__ == "__main__":
    main()
