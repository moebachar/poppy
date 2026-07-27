#!/usr/bin/env python
"""Keyframe moves: record by physical demonstration, replay from file.

RECORD (interactive via command file, robot starts stiff-in-place):
    python 05_keyframes.py record --port COM7 --move wave
  Commands are single lines written to scripts/motion/.kf_cmd:
    capture            capture current pose as next keyframe, stiffen everything
    soft               whole body compliant (sculpt freely, arms will droop)
    soft l_arm         only that group compliant, rest keeps holding
                       (groups: l_arm, r_arm, head, torso)
    duration 1.5       seconds allotted to reach the NEXT captured frames
    undo               drop last keyframe
    save               write moves/<move>.json, release, exit
    abort              release, exit without saving

PLAY:
    python 05_keyframes.py play --port COM7 --move wave [--hold-minutes 5]
  Travels slowly to frame 1, then steps through all frames, holds the last
  one, releases. Temp watchdog throughout.
"""
import argparse
import json
import time
from pathlib import Path

import pypot.dynamixel

HERE = Path(__file__).parent
MOVES_DIR = HERE / "moves"
CMD_FILE = HERE / ".kf_cmd"
GROUPS = {"l_arm": [41, 42, 43, 44], "r_arm": [51, 52, 53, 54],
          "head": [36, 37], "torso": [33, 34, 35]}
TEMP_HARD = 52


def freeze(dxl, ids, speed=20):
    pos = dict(zip(ids, dxl.get_present_position(ids)))
    for i in ids:
        dxl.set_moving_speed({i: speed})
        dxl.set_goal_position({i: pos[i]})
        dxl.enable_torque((i,))
    return pos


def record(dxl, ids, args):
    frames, duration = [], 1.5
    CMD_FILE.write_text("")
    freeze(dxl, ids)
    print("RECORDING — robot stiff. Waiting for commands (capture/soft/save/...)", flush=True)
    try:
        while True:
            time.sleep(0.5)
            temps = dxl.get_present_temperature(ids)
            if max(temps) >= TEMP_HARD:
                print("overheat -> abort recording, releasing", flush=True)
                return
            cmd = CMD_FILE.read_text().strip().lower() if CMD_FILE.exists() else ""
            if not cmd:
                continue
            CMD_FILE.write_text("")
            if cmd == "capture":
                pos = freeze(dxl, ids)  # re-freeze exactly where sculpted
                frames.append({"positions": {str(i): round(pos[i], 2) for i in ids},
                               "duration": duration})
                print(f"frame {len(frames)} captured — body stiff", flush=True)
            elif cmd == "soft":
                dxl.disable_torque(ids)
                print("whole body SOFT — sculpt, then 'capture'", flush=True)
            elif cmd.startswith("soft "):
                g = cmd.split(None, 1)[1]
                if g in GROUPS:
                    freeze(dxl, [i for i in ids if i not in GROUPS[g]])
                    dxl.disable_torque([i for i in GROUPS[g] if i in ids])
                    print(f"{g} SOFT, rest holding — sculpt, then 'capture'", flush=True)
                else:
                    print(f"unknown group '{g}'", flush=True)
            elif cmd.startswith("duration"):
                duration = float(cmd.split()[1])
                print(f"next frames will take {duration} s", flush=True)
            elif cmd == "undo" and frames:
                frames.pop()
                print(f"dropped last frame ({len(frames)} left)", flush=True)
            elif cmd == "save":
                MOVES_DIR.mkdir(exist_ok=True)
                out = MOVES_DIR / f"{args.move}.json"
                out.write_text(json.dumps({"name": args.move, "frames": frames}, indent=2))
                print(f"saved {len(frames)} frames -> {out}", flush=True)
                return
            elif cmd == "abort":
                print("aborted, nothing saved", flush=True)
                return
    finally:
        dxl.disable_torque(ids)
        print("released (compliant)", flush=True)


def play(dxl, ids, args):
    data = json.loads((MOVES_DIR / f"{args.move}.json").read_text())
    frames = data["frames"]
    if not frames:
        raise SystemExit("empty move")
    try:
        current = freeze(dxl, ids)
        first = {int(k): v for k, v in frames[0]["positions"].items() if int(k) in ids}
        far = {i: round(abs(current[i] - first[i]), 1)
               for i in first if abs(current[i] - first[i]) > 100}
        if far:
            raise SystemExit(f"refusing: too far from frame 1 {far}")
        print("traveling to frame 1...", flush=True)
        for i in first:
            dxl.set_moving_speed({i: 20})
            dxl.set_goal_position({i: first[i]})
        time.sleep(max(abs(current[i] - first[i]) for i in first) / 20 + 0.8)

        prev = first
        for n, fr in enumerate(frames[1:], start=2):
            tgt = {int(k): v for k, v in fr["positions"].items() if int(k) in ids}
            dur = max(float(fr.get("duration", 1.5)), 0.3)
            for i in tgt:
                speed = min(max(abs(tgt[i] - prev.get(i, tgt[i])) / dur, 5), 70)
                dxl.set_moving_speed({i: speed})
                dxl.set_goal_position({i: tgt[i]})
            time.sleep(dur + 0.15)
            temps = dxl.get_present_temperature(ids)
            print(f"frame {n}/{len(frames)} done (hottest {max(temps):.0f} C)", flush=True)
            if max(temps) >= TEMP_HARD:
                print("overheat -> releasing", flush=True)
                return
            prev = tgt
        print(f"move complete — holding last frame {args.hold_minutes} min", flush=True)
        t_end = time.time() + args.hold_minutes * 60
        while time.time() < t_end:
            temps = dxl.get_present_temperature(ids)
            if max(temps) >= TEMP_HARD:
                break
            time.sleep(15)
    finally:
        dxl.disable_torque(ids)
        print("released (compliant)", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("record", "play"))
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--move", default="wave")
    ap.add_argument("--hold-minutes", type=float, default=5.0)
    args = ap.parse_args()
    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        ids = [i for i in dxl.scan(list(range(60))) if i < 250]
        print(f"motors: {ids}", flush=True)
        (record if args.action == "record" else play)(dxl, ids, args)


if __name__ == "__main__":
    main()
