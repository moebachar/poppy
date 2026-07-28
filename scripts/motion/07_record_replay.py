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

Seam motors (41, 42, 44) run in multi-turn mode (see dxl_multiturn.py):
their position IO goes through raw registers, recordings are unwrapped to a
continuous series, and replays are rebased by whole turns to the current
reading — so the old +/-180 rollover can never produce a 300-degree sweep.
"""
import argparse
import json
import threading
import time
from pathlib import Path

import pypot.dynamixel

from dxl_multiturn import SEAM_IDS, present_deg, goto_deg, freeze, rebase, is_multiturn

RECORDED = Path(__file__).parent / "moves" / "recorded"
TEMP_HARD = 52


def unwrap(vals):
    """Make a recorded series continuous (undo +/-360 flickers at the seam)."""
    out = [vals[0]]
    for v in vals[1:]:
        d = v - out[-1]
        d -= 360.0 * round(d / 360.0)
        out.append(out[-1] + d)
    return out


def check_multiturn(dxl, seam):
    bad = [i for i in seam if not is_multiturn(dxl, i)]
    if bad:
        raise SystemExit(f"motors {bad} not in multi-turn mode — run: "
                         f"python scripts/motion/dxl_multiturn.py --port COM7 enable")


CORE_IDS = (33, 34, 35, 36, 37)   # waist, bust, head: stiffer so posture holds


def do_record(dxl, present, args):
    """Teach mode: robot holds its pose gently; push a limb firmly and it
    stays where you put it (goal follows the hand, torque ceiling lowered)."""
    path = RECORDED / f"{args.name}.json"
    seam = [i for i in present if i in SEAM_IDS]
    others = [i for i in present if i not in SEAM_IDS]
    check_multiturn(dxl, seam)

    def positions():
        pos = dict(zip(others, dxl.get_present_position(others)))
        for i in seam:
            pos[i] = present_deg(dxl, i)
        return pos

    try:
        # freeze at full strength first (no jump), optionally settle into stance
        current = positions()
        for i in present:
            dxl.set_moving_speed({i: 20})
            dxl.set_torque_limit({i: 100})
            if i in SEAM_IDS:
                freeze(dxl, i)
            else:
                dxl.set_goal_position({i: current[i]})
                dxl.enable_torque((i,))
        time.sleep(0.3)
        if args.from_pose != "none":
            pose_file = Path(__file__).parent / "poses" / f"{args.from_pose}.json"
            target = {int(k): v for k, v in
                      json.loads(pose_file.read_text())["positions"].items()}
            target = {i: v for i, v in target.items() if i in present}
            for i in target:
                if i in SEAM_IDS:
                    target[i] = rebase(target[i], current[i])
            worst = max(abs(target[i] - current[i]) for i in target)
            if worst <= 100:
                print(f"settling into pose '{args.from_pose}'...", flush=True)
                for i in target:
                    if i in SEAM_IDS:
                        goto_deg(dxl, i, target[i])
                    else:
                        dxl.set_goal_position({i: target[i]})
                time.sleep(worst / 20 + 0.8)
            else:
                print(f"note: too far from pose '{args.from_pose}' ({worst:.0f} deg) "
                      f"— teaching from current position", flush=True)

        # now lower the torque ceiling: gentle hold, yields to a firm push
        for i in present:
            dxl.set_moving_speed({i: 150})
            dxl.set_torque_limit(
                {i: args.core_stiffness if i in CORE_IDS else args.arm_stiffness})

        stop = threading.Event()
        threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
        print("TEACH MODE: he holds the pose — push limbs firmly to reshape him; "
              "they stay where you leave them.", flush=True)
        print(f"RECORDING at {args.hz} Hz — press Enter to stop.", flush=True)
        frames, t0 = [], time.time()
        period = 1.0 / args.hz
        goals = positions()
        while not stop.is_set() and time.time() - t0 < args.max_seconds:
            tick = time.time()
            pos = positions()
            for i in present:
                # goal follows the hand ONLY on deliberate displacement —
                # a deadband, so gravity sag can't ratchet the pose down
                if abs(pos[i] - goals[i]) > args.follow_deadband:
                    goals[i] = pos[i]
                    if i in SEAM_IDS:
                        goto_deg(dxl, i, pos[i])
                    else:
                        dxl.set_goal_position({i: pos[i]})
            frames.append({"t": round(tick - t0, 3),
                           "pos": {str(i): round(p, 2) for i, p in pos.items()}})
            time.sleep(max(0, period - (time.time() - tick)))
    finally:
        for i in present:
            dxl.set_torque_limit({i: 100})
        dxl.disable_torque(present)
        print("released (compliant), torque ceiling restored", flush=True)

    if len(frames) < 5:
        raise SystemExit("recording too short — nothing saved")
    RECORDED.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"name": args.name, "space": "raw", "hz": args.hz, "ids": list(present),
         "frames": frames}, indent=1))
    print(f"saved {len(frames)} frames ({frames[-1]['t']:.1f} s) -> {path}")
    print(f"replay with:  python scripts\\motion\\07_record_replay.py "
          f"--port {args.port} replay {args.name}")


def do_replay(dxl, present, args):
    path = RECORDED / f"{args.name}.json"
    if not path.exists():
        raise SystemExit(f"no such recording: {path} (try 'list')")
    frames = json.loads(path.read_text())["frames"]
    ids = [i for i in present if str(i) in frames[0]["pos"]]
    seam = [i for i in ids if i in SEAM_IDS]
    others = [i for i in ids if i not in SEAM_IDS]
    check_multiturn(dxl, seam)

    # seam trajectories: unwrap to continuous, then rebase to current reading
    seam_traj = {}
    for i in seam:
        series = unwrap([f["pos"][str(i)] for f in frames])
        shift = rebase(series[0], present_deg(dxl, i)) - series[0]
        seam_traj[i] = [v + shift for v in series]

    try:
        # freeze the whole body where it is (per-motor, goal:=present first)
        current = dict(zip(present, dxl.get_present_position(present)))
        for i in present:
            dxl.set_moving_speed({i: 20})
            dxl.set_torque_limit({i: 100})   # full strength for replay
            if i in SEAM_IDS:
                freeze(dxl, i)
                current[i] = present_deg(dxl, i)
            else:
                dxl.set_goal_position({i: current[i]})
                dxl.enable_torque((i,))
        time.sleep(0.3)
        off = [i for i, on in zip(present, dxl.is_torque_enabled(present)) if not on]
        print(f"TORQUE READ-BACK: {'ALL ON' if not off else f'OFF: {off}'}", flush=True)

        # travel slowly to the first frame, guarded
        first = {i: frames[0]["pos"][str(i)] for i in others}
        first.update({i: seam_traj[i][0] for i in seam})
        worst = max(abs(first[i] - current[i]) for i in ids)
        if worst > args.max_travel and not args.force:
            raise SystemExit(f"refusing: first frame is {worst:.0f} deg away (--force to override)")
        for i in others:
            dxl.set_goal_position({i: first[i]})
        for i in seam:
            goto_deg(dxl, i, first[i])
        time.sleep(worst / 20 + 0.8)
        print(f"at start — replaying {len(frames)} frames "
              f"({frames[-1]['t'] - frames[0]['t']:.1f} s)", flush=True)

        # stream the recording (drop frames if we fall behind)
        for i in ids:
            dxl.set_moving_speed({i: 150})
        t0, tref = time.time(), frames[0]["t"]
        last_temp = t0
        for n, fr in enumerate(frames[1:], start=1):
            target = t0 + (fr["t"] - tref)
            now = time.time()
            if now > target + 0.08:
                continue
            if target > now:
                time.sleep(target - now)
            for i in others:
                v = fr["pos"].get(str(i))
                if v is not None:
                    dxl.set_goal_position({i: v})
            for i in seam:
                goto_deg(dxl, i, seam_traj[i][n])
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
    ap.add_argument("--from-pose", default="stand",
                    help="pose to settle into before teach mode ('none' to skip)")
    ap.add_argument("--core-stiffness", type=float, default=60.0,
                    help="teach-mode torque %% for waist/bust/head")
    ap.add_argument("--arm-stiffness", type=float, default=25.0,
                    help="teach-mode torque %% for arms")
    ap.add_argument("--follow-deadband", type=float, default=4.0,
                    help="degrees a joint must be pushed before its goal follows")
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
