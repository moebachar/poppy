#!/usr/bin/env python
"""Multi-turn mode for the seam motors (41, 42, 44) + raw position IO.

The 2013 assembly put three left-arm joints' working arcs across the MX-28
encoder seam (the +/-180 deg rollover). Joint mode cannot be commanded across
it. Multi-turn mode (CW limit = CCW limit = 4095) makes the position counter
continuous (...179, 180, 181...) so commands cross the seam smoothly.

Position IO for these motors MUST go through this module: pypot's converters
clamp goals into one turn (degree_to_dxl) and misread negative multi-turn
registers (dxl_to_degree). Non-position controls (speed, torque, temperature)
still work fine through pypot.

Note: the counter re-bases into 0..360 at every power-up, so absolute values
may differ by +/-360 between sessions — always rebase() targets to the
current reading before commanding (see 07_record_replay.py).

CLI:
    python dxl_multiturn.py --port COM7 status
    python dxl_multiturn.py --port COM7 enable          # EEPROM, reversible
    python dxl_multiturn.py --port COM7 disable         # back to joint mode
    python dxl_multiturn.py --port COM7 jog --id 42 --delta 25
"""
import argparse
import time

import pypot.dynamixel

SEAM_IDS = (41, 42, 44)
ADDR_CW, ADDR_CCW, ADDR_MT_OFFSET, ADDR_RES_DIV = 6, 8, 20, 22
ADDR_GOAL, ADDR_PRESENT = 30, 36
# original EEPROM values on this unit (read 2026-07-28): CW=0, CCW=4095 all three


def read_reg(dxl, mid, addr, length=2):
    sp = dxl._send_packet(dxl._protocol.DxlReadDataPacket(mid, addr, length))
    if sp is None:
        raise IOError(f"no answer from id {mid} reading addr {addr}")
    p = sp.parameters
    return (p[0] | (p[1] << 8)) if length == 2 else p[0]


def write_reg(dxl, mid, addr, value, length=2):
    v = value & (0xFFFF if length == 2 else 0xFF)
    coded = (v & 0xFF, v >> 8) if length == 2 else (v,)
    sp = dxl._send_packet(dxl._protocol.DxlWriteDataPacket(mid, addr, coded))
    if sp is None:
        raise IOError(f"no answer from id {mid} writing addr {addr}")


def s16(v):
    return v - 65536 if v > 32767 else v


def reg_to_deg(r):
    return r * 360.0 / 4095.0 - 180.0


def deg_to_reg(d):
    return int(round((d + 180.0) * 4095.0 / 360.0))


def present_deg(dxl, mid):
    return reg_to_deg(s16(read_reg(dxl, mid, ADDR_PRESENT)))


def goto_deg(dxl, mid, deg):
    if not -700.0 <= deg <= 700.0:   # sanity: our joints never leave one turn
        raise ValueError(f"refusing absurd goal {deg:.1f} deg for id {mid}")
    write_reg(dxl, mid, ADDR_GOAL, deg_to_reg(deg))


def freeze(dxl, mid):
    """goal := present (raw), then torque on. Seam-safe."""
    goto_deg(dxl, mid, present_deg(dxl, mid))
    dxl.enable_torque((mid,))


def rebase(target_deg, current_deg):
    """Shift target by whole turns to the representation nearest current."""
    return target_deg + round((current_deg - target_deg) / 360.0) * 360.0


def is_multiturn(dxl, mid):
    return read_reg(dxl, mid, ADDR_CW) == 4095 and read_reg(dxl, mid, ADDR_CCW) == 4095


def cmd_status(dxl, ids):
    print("motor    cw   ccw  mt_off  resdiv  present     mode")
    for mid in ids:
        cw, ccw = read_reg(dxl, mid, ADDR_CW), read_reg(dxl, mid, ADDR_CCW)
        off = s16(read_reg(dxl, mid, ADDR_MT_OFFSET))
        div = read_reg(dxl, mid, ADDR_RES_DIV, 1)
        mode = "MULTI-TURN" if cw == ccw == 4095 else "joint"
        print(f"{mid:>5} {cw:5d} {ccw:5d} {off:7d} {div:7d} {present_deg(dxl, mid):8.1f}  {mode}")


def cmd_enable(dxl, ids):
    for mid in ids:
        dxl.disable_torque((mid,))
        if s16(read_reg(dxl, mid, ADDR_MT_OFFSET)) != 0:
            write_reg(dxl, mid, ADDR_MT_OFFSET, 0)  # keep readings == joint mode
        write_reg(dxl, mid, ADDR_CW, 4095)
        write_reg(dxl, mid, ADDR_CCW, 4095)
        time.sleep(0.1)
        ok = is_multiturn(dxl, mid)
        print(f"id {mid}: multi-turn {'ON (verified)' if ok else 'FAILED'}")


def cmd_disable(dxl, ids):
    for mid in ids:
        dxl.disable_torque((mid,))
        write_reg(dxl, mid, ADDR_CW, 0)
        write_reg(dxl, mid, ADDR_CCW, 4095)
        time.sleep(0.1)
        print(f"id {mid}: joint mode restored "
              f"(cw={read_reg(dxl, mid, ADDR_CW)}, ccw={read_reg(dxl, mid, ADDR_CCW)})")


def cmd_jog(dxl, args):
    mid = args.mid
    dxl.set_moving_speed({mid: args.speed})
    p = present_deg(dxl, mid)
    print(f"present {p:.1f} -> goal {p + args.delta:.1f} (raw deg)")
    freeze(dxl, mid)
    time.sleep(0.3)
    try:
        goto_deg(dxl, mid, p + args.delta)
        time.sleep(abs(args.delta) / args.speed + 1.0)
        print(f"reached {present_deg(dxl, mid):.1f}")
        time.sleep(1.0)
        goto_deg(dxl, mid, p)
        time.sleep(abs(args.delta) / args.speed + 1.0)
    finally:
        dxl.disable_torque((mid,))
        print("released")


def cmd_watch(dxl, args):
    mid = args.mid
    print(f"WATCHING id {mid} for {args.seconds:.0f}s — move the limb NOW, slowly.", flush=True)
    t0, last = time.time(), None
    while time.time() - t0 < args.seconds:
        p = present_deg(dxl, mid)
        if last is None or abs(p - last) > 0.8:
            print(f"{time.time() - t0:5.1f}s  {p:8.1f}", flush=True)
            last = p
        time.sleep(0.1)
    print("done")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("action", choices=("status", "enable", "disable", "jog", "watch"))
    ap.add_argument("--ids", type=int, nargs="+", default=list(SEAM_IDS))
    ap.add_argument("--id", type=int, dest="mid")
    ap.add_argument("--delta", type=float, default=20.0)
    ap.add_argument("--speed", type=float, default=15.0)
    ap.add_argument("--seconds", type=float, default=40.0)
    args = ap.parse_args()

    unknown = [i for i in args.ids if i not in SEAM_IDS]
    if unknown:
        raise SystemExit(f"refusing to touch non-seam motors: {unknown}")

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        if args.action == "status":
            cmd_status(dxl, args.ids)
        elif args.action == "enable":
            cmd_enable(dxl, args.ids)
        elif args.action == "disable":
            cmd_disable(dxl, args.ids)
        elif args.action == "jog":
            if args.mid not in SEAM_IDS:
                raise SystemExit("jog needs --id one of " + str(SEAM_IDS))
            cmd_jog(dxl, args)
        elif args.action == "watch":
            if not args.mid:
                raise SystemExit("watch needs --id")
            cmd_watch(dxl, args)


if __name__ == "__main__":
    main()
