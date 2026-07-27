#!/usr/bin/env python
"""Motion ladder step 2 — stand stiff (hold pose), then wave the left arm on command.

Sequence: freeze every motor at its current position (no jump: goal:=present
before torque-on) -> hold -> optional left-arm wave (shoulder lift + elbow
oscillation) -> return to freeze pose -> keep holding -> gentle release.
Temp watchdog throughout; always exits compliant (finally-block).

Usage:
    python 02_hold_and_wave.py --port COM7 --probe-shoulder          # tiny 42 twitch, then release
    python 02_hold_and_wave.py --port COM7 --wave --shoulder-sign -1 # full demo
    python 02_hold_and_wave.py --port COM7 --hold-seconds 120        # just stand stiff
"""
import argparse
import time

import pypot.dynamixel

L_SHOULDER_X, L_ELBOW = 42, 44
TEMP_SOFT, TEMP_HARD = 48, 52
MARGIN = 5.0
MAX_EXCURSION = 50.0  # no joint ever commanded further than this from its freeze pose


def clamp(v, lo, hi):
    return min(max(v, lo), hi)


class Holder:
    def __init__(self, dxl, ids):
        self.dxl = dxl
        self.ids = ids
        self.freeze = dict(zip(ids, dxl.get_present_position(ids)))
        self.limits = {}
        for mid, (lo, hi) in zip(ids, dxl.get_angle_limit(ids)):
            lo, hi = (lo, hi) if lo < hi else (hi, lo)
            self.limits[mid] = (lo + MARGIN, hi - MARGIN)

    def target(self, mid, pos):
        lo, hi = self.limits[mid]
        p0 = self.freeze[mid]
        pos = clamp(pos, p0 - MAX_EXCURSION, p0 + MAX_EXCURSION)
        return clamp(pos, lo, hi)

    def goto(self, mid, pos, speed):
        self.dxl.set_moving_speed({mid: speed})
        self.dxl.set_goal_position({mid: self.target(mid, pos)})

    def temps_ok(self):
        temps = self.dxl.get_present_temperature(self.ids)
        worst = max(temps)
        if worst >= TEMP_HARD:
            print(f"!! {worst:.0f} C reached -> releasing")
            return False
        if worst >= TEMP_SOFT:
            print(f"warn: hottest motor {worst:.0f} C")
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--probe-shoulder", action="store_true",
                    help="tiny +10 deg raw twitch on id 42, report, release")
    ap.add_argument("--wave", action="store_true")
    ap.add_argument("--shoulder-sign", type=int, choices=(-1, 1), default=1,
                    help="raw direction that lifts the left arm OUT (from probe)")
    ap.add_argument("--shoulder-delta", type=float, default=35.0)
    ap.add_argument("--elbow-only", action="store_true",
                    help="wave with the elbow alone: raise forearm, oscillate, lower")
    ap.add_argument("--elbow-sign", type=int, choices=(-1, 1), default=1,
                    help="raw direction that raises the forearm")
    ap.add_argument("--elbow-raise", type=float, default=30.0)
    ap.add_argument("--elbow-amp", type=float, default=18.0)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--hold-seconds", type=float, default=25.0,
                    help="stiff hold time after the action")
    args = ap.parse_args()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = [i for i in dxl.scan(list(range(60))) if i < 250]
        print(f"motors: {ids}")
        h = Holder(dxl, ids)
        try:
            # freeze in place, ONE MOTOR AT A TIME: multi-id broadcast writes are
            # silently dropped/mangled on this USB2AX bus (2026-07-27 evidence:
            # soft body + stale-goal head jump). Single writes always worked.
            h.freeze = dict(zip(ids, dxl.get_present_position(ids)))  # last-moment re-read
            for i in ids:
                dxl.set_moving_speed({i: 30})
                dxl.set_goal_position({i: h.freeze[i]})
                dxl.enable_torque((i,))
            time.sleep(0.5)
            held = dict(zip(ids, dxl.get_present_position(ids)))
            drift = {i: round(held[i] - h.freeze[i], 1)
                     for i in ids if abs(held[i] - h.freeze[i]) > 4}
            print("STIFF — holding pose" + (f" (unexpected drift: {drift})" if drift else " (verified, no drift)"))
            time.sleep(2)

            if args.probe_shoulder:
                p0 = h.freeze[L_SHOULDER_X]
                h.goto(L_SHOULDER_X, p0 + 10, 15)
                time.sleep(1.5)
                h.goto(L_SHOULDER_X, p0, 15)
                time.sleep(1.5)
                print("probe done: which way did the arm move? OUT (away from body) or IN?")

            if args.wave and h.temps_ok():
                s0 = h.freeze[L_SHOULDER_X]
                e0 = h.freeze[L_ELBOW]
                if not args.elbow_only:
                    s_up = s0 + args.shoulder_sign * args.shoulder_delta
                    print("wave: shoulder up")
                    h.goto(L_SHOULDER_X, s_up, 25)
                    time.sleep(abs(args.shoulder_delta) / 25 + 0.6)
                center = e0 + (args.elbow_sign * args.elbow_raise if args.elbow_only else 0)
                if args.elbow_only:
                    print("wave: forearm up")
                    h.goto(L_ELBOW, center, 30)
                    time.sleep(abs(args.elbow_raise) / 30 + 0.5)
                half = 2 * args.elbow_amp / 50 + 0.25
                for c in range(args.cycles):
                    if not h.temps_ok():
                        break
                    h.goto(L_ELBOW, center + args.elbow_amp, 50)
                    time.sleep(half)
                    h.goto(L_ELBOW, center - args.elbow_amp, 50)
                    time.sleep(half)
                print("wave: arm back down")
                h.goto(L_ELBOW, e0, 30)
                time.sleep(abs(args.elbow_raise) / 30 + 0.6)
                if not args.elbow_only:
                    h.goto(L_SHOULDER_X, s0, 25)
                    time.sleep(abs(args.shoulder_delta) / 25 + 0.6)

            t_end = time.time() + args.hold_seconds
            while time.time() < t_end:
                if not h.temps_ok():
                    break
                time.sleep(3)
        finally:
            dxl.disable_torque(ids)
            temps = dxl.get_present_temperature(ids)
            print(f"released (compliant). hottest motor: {max(temps):.0f} C")


if __name__ == "__main__":
    main()
