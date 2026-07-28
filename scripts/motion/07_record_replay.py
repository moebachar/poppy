#!/usr/bin/env python
"""Record a move by physically puppeteering the soft robot; replay it anytime.

Everything is RAW motor space — no sim, no signs, no offsets. What you
sculpt is exactly what replays.

    python 07_record_replay.py --port COM7 record hello_wave
    python 07_record_replay.py --port COM7 replay hello_wave
    python 07_record_replay.py --port COM7 list

Record: all motors go soft, you move the robot like a puppet, Enter stops.
Replay: whole body freezes stiff, travels slowly to the move's first frame
(guarded), then streams the recording; Ctrl+C at any point = release.
"""
import argparse
import json
import threading
import time
from pathlib import Path

import pypot.dynamixel

RECORDED = Path(__file__).parent / "moves" / "recorded"
TEMP_HARD = 52


def do_record(dxl, present, args):
    path = RECORDED / f"{args.name}.json"
    dxl.disable_torque(present)
    print("robot is SOFT — hold him. Recording starts in 3s...", flush=True)
    time.sleep(3)
    stop = threading.Event()
    threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
    print(f"RECORDING at {args.hz} Hz — puppet the move now. Press Enter to stop.", flush=True)
    frames, t0 = [], time.time()
    period = 1.0 / args.hz
    while not stop.is_set() and time.time() - t0 < args.max_seconds:
        tick = time.time()
        pos = dxl.get_present_position(present)
        frames.append({"t": round(tick - t0, 3),
                       "pos": {str(i): round(p, 2) for i, p in zip(present, pos)}})
        time.sleep(max(0, period - (time.time() - tick)))
    if len(frames) < 5:
        raise SystemExit("recording too short — nothing saved")
    RECORDED.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"name": args.name, "space": "raw", "hz": args.hz, "ids": list(present),
         "frames": frames}, indent=1))
    print(f"saved {len(frames)} frames ({frames[-1]['t']:.1f} s) -> {path}")
    print(f"replay with:  python {Path(__file__).name} --port {args.port} replay {args.name}")


def do_replay(dxl, present, args):
    path = RECORDED / f"{args.name}.json"
    if not path.exists():
        raise SystemExit(f"no such recording: {path} (try 'list')")
    frames = json.loads(path.read_text())["frames"]
    ids = [i for i in present if str(i) in frames[0]["pos"]]
    first = {i: frames[0]["pos"][str(i)] for i in ids}

    try:
        # freeze the whole body where it is (per-motor, goal:=present first)
        current = dict(zip(present, dxl.get_present_position(present)))
        for i in present:
            dxl.set_moving_speed({i: 20})
            dxl.set_goal_position({i: current[i]})
            dxl.enable_torque((i,))
        time.sleep(0.3)
        off = [i for i, on in zip(present, dxl.is_torque_enabled(present)) if not on]
        print(f"TORQUE READ-BACK: {'ALL ON' if not off else f'OFF: {off}'}", flush=True)

        # travel slowly to the first frame, guarded
        worst = max(abs(first[i] - current[i]) for i in ids)
        if worst > args.max_travel and not args.force:
            raise SystemExit(f"refusing: first frame is {worst:.0f} deg away (--force to override)")
        for i in ids:
            dxl.set_goal_position({i: first[i]})
        time.sleep(worst / 20 + 0.8)
        print(f"at start — replaying {len(frames)} frames "
              f"({frames[-1]['t'] - frames[0]['t']:.1f} s)", flush=True)

        # stream the recording (drop frames if we fall behind)
        for i in ids:
            dxl.set_moving_speed({i: 150})
        t0, tref = time.time(), frames[0]["t"]
        last_temp = t0
        for fr in frames[1:]:
            target = t0 + (fr["t"] - tref)
            now = time.time()
            if now > target + 0.08:
                continue
            if target > now:
                time.sleep(target - now)
            for i in ids:
                v = fr["pos"].get(str(i))
                if v is not None:
                    dxl.set_goal_position({i: v})
            if time.time() - last_temp > 2:
                last_temp = time.time()
                if max(dxl.get_present_temperature(present)) >= TEMP_HARD:
                    print("overheat -> releasing", flush=True)
                    return
        print(f"replay done — holding {args.hold_seconds:.0f} s", flush=True)
        t_end = time.time() + args.hold_seconds
        while time.time() < t_end:
            if max(dxl.get_present_temperature(present)) >= TEMP_HARD:
                break
            time.sleep(min(5, max(0.1, t_end - time.time())))
    finally:
        dxl.disable_torque(present)
        print("released (compliant)", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("action", choices=("record", "replay", "list"))
    ap.add_argument("name", nargs="?", default="move")
    ap.add_argument("--hz", type=float, default=20.0)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    ap.add_argument("--hold-seconds", type=float, default=10.0)
    ap.add_argument("--max-travel", type=float, default=100.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.action == "list":
        files = sorted(RECORDED.glob("*.json")) if RECORDED.exists() else []
        for f in files:
            d = json.loads(f.read_text())
            print(f"  {f.stem:20s} {d['frames'][-1]['t']:6.1f} s  {len(d['frames'])} frames")
        if not files:
            print("  (no recordings yet)")
        return

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        present = [i for i in dxl.scan(list(range(60))) if i < 250]
        if args.action == "record":
            do_record(dxl, present, args)
        else:
            do_replay(dxl, present, args)


if __name__ == "__main__":
    main()
