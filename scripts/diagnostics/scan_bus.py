#!/usr/bin/env python
"""Scan a Dynamixel Protocol-1.0 bus and report every motor found.

Read-only: never enables torque, never writes any register.

Usage:
    python scan_bus.py                  # auto-detect port, scan 1M + 57600 bps
    python scan_bus.py --port COM3
    python scan_bus.py --all-bauds      # also sweep legacy baudrates
    python scan_bus.py --max-id 60      # faster scan (default 253)
"""
import argparse
import sys

import pypot.dynamixel

DEFAULT_BAUDS = [1_000_000, 57_600]
EXTRA_BAUDS = [115_200, 500_000, 400_000, 250_000, 200_000, 19_200, 9_600]

# Ground truth from hardware/motor_map.md (poppy_torso.json @ 8073e69)
EXPECTED = {
    33: "abs_z", 34: "bust_y", 35: "bust_x",
    36: "head_z", 37: "head_y",
    41: "l_shoulder_y", 42: "l_shoulder_x", 43: "l_arm_z", 44: "l_elbow_y",
    51: "r_shoulder_y", 52: "r_shoulder_x", 53: "r_arm_z", 54: "r_elbow_y",
}


def scan_baud(port, baud, max_id):
    """Return {id: info} for every motor answering at this baudrate."""
    found = {}
    try:
        with pypot.dynamixel.DxlIO(port, baudrate=baud) as dxl:
            present = dxl.scan(list(range(max_id + 1)))
            for mid in present:
                info = {}
                for key, getter in [
                    ("model", dxl.get_model),
                    ("firmware", dxl.get_firmware),
                    ("pos_deg", dxl.get_present_position),
                    ("volt", dxl.get_present_voltage),
                    ("temp_C", dxl.get_present_temperature),
                ]:
                    try:
                        info[key] = getter((mid,))[0]
                    except Exception as exc:  # keep scanning even if one read fails
                        info[key] = f"read-fail ({exc.__class__.__name__})"
                found[mid] = info
    except Exception as exc:
        print(f"  !! could not scan at {baud} bps: {exc}")
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="serial port (e.g. COM3); auto-detect if omitted")
    ap.add_argument("--all-bauds", action="store_true", help="also sweep legacy baudrates")
    ap.add_argument("--max-id", type=int, default=253, help="highest ID to ping (default 253)")
    args = ap.parse_args()

    port = args.port
    if not port:
        ports = pypot.dynamixel.get_available_ports()
        print(f"available ports: {ports}")
        if len(ports) != 1:
            sys.exit("specify --port (none or several candidates found)")
        port = ports[0]
    print(f"scanning {port} (read-only) ...")

    bauds = DEFAULT_BAUDS + (EXTRA_BAUDS if args.all_bauds else [])
    all_found = {}  # id -> (baud, info)
    for baud in bauds:
        print(f"\n--- {baud} bps ---")
        found = scan_baud(port, baud, args.max_id)
        if not found:
            print("  nothing")
        for mid, info in sorted(found.items()):
            name = EXPECTED.get(mid, "?? not in map")
            print(f"  id {mid:3d}  {str(info['model']):8s} fw {info['firmware']}  "
                  f"pos {info['pos_deg']}°  {info['volt']} V  {info['temp_C']} °C   [{name}]")
            all_found.setdefault(mid, (baud, info))

    print("\n=== summary ===")
    print(f"found {len(all_found)} motor(s): {sorted(all_found)}")
    missing = sorted(set(EXPECTED) - set(all_found))
    extra = sorted(set(all_found) - set(EXPECTED))
    if missing:
        print(f"MISSING vs map: {[f'{i} ({EXPECTED[i]})' for i in missing]}")
    if extra:
        print(f"UNEXPECTED ids: {extra}")
    if not missing and not extra:
        print("perfect match with hardware/motor_map.md")


if __name__ == "__main__":
    main()
