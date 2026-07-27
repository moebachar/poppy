#!/usr/bin/env python
"""THE robot script: stand still, then execute an exported move file, then hold.

Accepts a pypot Move JSON (recorded/exported from the CoppeliaSim workflow:
{"framerate": f, "positions": {"<t>": {"<joint>": [pos_deg, speed], ...}}})
or the keyframe format ({"frames": [{"deltas"|"positions": {...}, "duration": s}]}).

Safety on this 2013 unit (stale factory offsets, see PROJECT_LOG 2026-07-27):
sim angles are applied as DELTAS from the move's FIRST frame, on top of the
robot's recorded stance (poses/stand.json). So: make the sim move START from
the sim rest pose. Stale offsets cancel out; the robot's stance anchors reality.

    python 06_execute_move.py --port COM7 --move wave.json
    python 06_execute_move.py --port COM7 --move wave.json --hold-minutes 60
"""
import argparse
import json
import time
from pathlib import Path

import pypot.dynamixel

HERE = Path(__file__).parent
STANCE_FILE = HERE / "poses" / "stand.json"

# name -> (id, +1 direct / -1 indirect)   [ground truth: hardware/motor_map.md]
MOTORS = {
    "abs_z": (33, +1), "bust_y": (34, -1), "bust_x": (35, -1),
    "head_z": (36, +1), "head_y": (37, -1),
    "l_shoulder_y": (41, +1), "l_shoulder_x": (42, -1),
    "l_arm_z": (43, -1), "l_elbow_y": (44, +1),
    "r_shoulder_y": (51, -1), "r_shoulder_x": (52, -1),
    "r_arm_z": (53, -1), "r_elbow_y": (54, -1),
}
TEMP_HARD = 52
STEP = 0.1          # playback resample step (s)
MAX_DELTA = 120.0   # refuse joints asked to travel further than this from stance


def load_frames(path):
    """Return [(t_seconds, {name: robot_deg})] sorted by time."""
    data = json.loads(Path(path).read_text())
    if "positions" in data and isinstance(data["positions"], dict):   # pypot Move
        frames = [(float(t), {n: v[0] for n, v in pos.items() if n in MOTORS})
                  for t, pos in data["positions"].items()]
        return sorted(frames)
    if "frames" in data:                                              # keyframes
        frames, t = [], 0.0
        for fr in data["frames"]:
            src = fr.get("deltas") or fr.get("positions") or {}
            frames.append((t, {n: float(v) for n, v in src.items() if n in MOTORS}))
            t += max(float(fr.get("duration", 1.5)), 0.3)
        return frames
    raise SystemExit("unrecognized move file format")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--move", required=True, help="move file (path or name in moves/)")
    ap.add_argument("--hold-minutes", type=float, default=30.0)
    ap.add_argument("--speed-cap", type=float, default=80.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    mv = Path(args.move)
    if not mv.exists():
        mv = HERE / "moves" / (args.move if args.move.endswith(".json") else args.move + ".json")
    frames = load_frames(mv)
    if len(frames) < 2:
        raise SystemExit("move has fewer than 2 frames")
    stance = {int(k): v for k, v in
              json.loads(STANCE_FILE.read_text())["positions"].items()}

    t0, first = frames[0]
    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        present = [i for i in dxl.scan(list(range(60))) if i < 250]

        # robot-space frame -> raw goals: stance + sign * (pos - first_frame_pos)
        def raw_goals(pose):
            out = {}
            for name, robot_deg in pose.items():
                mid, sign = MOTORS[name]
                if mid not in present or mid not in stance or name not in first:
                    continue
                out[mid] = stance[mid] + sign * (robot_deg - first[name])
            return out

        worst = max((abs(g - stance[i]) for fr in frames for i, g in raw_goals(fr[1]).items()),
                    default=0)
        if worst > MAX_DELTA and not args.force:
            raise SystemExit(f"refusing: move reaches {worst:.0f} deg from stance (--force to override)")
        print(f"move: {mv.name}  {len(frames)} frames  {frames[-1][0] - t0:.1f} s  "
              f"max excursion {worst:.0f} deg", flush=True)

        try:
            # 1. stand still
            current = dict(zip(present, dxl.get_present_position(present)))
            for i in present:
                dxl.set_moving_speed({i: 20})
                dxl.set_goal_position({i: current[i]})
                dxl.enable_torque((i,))
            time.sleep(0.3)
            off = [i for i, on in zip(present, dxl.is_torque_enabled(present)) if not on]
            print(f"TORQUE READ-BACK: {'ALL ON' if not off else f'OFF: {off}'}", flush=True)
            start = raw_goals(first)
            for i in start:
                dxl.set_goal_position({i: start[i]})
            time.sleep(max((abs(current[i] - start[i]) for i in start), default=0) / 20 + 0.8)
            print("standing at move start — executing", flush=True)

            # 2. execute, resampled at STEP with per-joint speeds
            prev_t, prev = t0, start
            last_temp_check = time.time()
            for t, pose in frames[1:]:
                goals = raw_goals(pose)
                dt = max(t - prev_t, STEP)
                for i, g in goals.items():
                    v = min(max(abs(g - prev.get(i, g)) / dt, 5), args.speed_cap)
                    dxl.set_moving_speed({i: v})
                    dxl.set_goal_position({i: g})
                time.sleep(dt)
                prev_t, prev = t, goals
                if time.time() - last_temp_check > 2:
                    last_temp_check = time.time()
                    if max(dxl.get_present_temperature(present)) >= TEMP_HARD:
                        print("overheat -> releasing", flush=True)
                        return
            print(f"move done — holding {args.hold_minutes:.0f} min", flush=True)

            # 3. hold
            t_end = time.time() + args.hold_minutes * 60
            while time.time() < t_end:
                temps = dxl.get_present_temperature(present)
                n_on = sum(dxl.is_torque_enabled(present))
                print(f"holding: {n_on}/{len(present)} stiff, hottest {max(temps):.0f} C", flush=True)
                if max(temps) >= TEMP_HARD:
                    break
                time.sleep(30)
        finally:
            dxl.disable_torque(present)
            print("released (compliant)", flush=True)


if __name__ == "__main__":
    main()
