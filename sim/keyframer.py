#!/usr/bin/env python
"""Interactive keyframe authoring on the SIMULATED Poppy (CoppeliaSim must be open).

Run in your own terminal:
    C:\\Users\\mbachar\\poppy\\.venv\\Scripts\\python C:\\Users\\mbachar\\poppy\\sim\\keyframer.py

Commands:
    <joint> <deg>       move a sim joint, e.g.:  l_shoulder_x 40
                        (joints: abs_z bust_y bust_x head_z head_y
                                 l/r_shoulder_y l/r_shoulder_x l/r_arm_z l/r_elbow_y)
    get                 print all joint angles
    capture [seconds]   save current sim pose as next keyframe (default 1.5 s to reach)
    list                show keyframes
    undo                remove last keyframe
    play                preview the whole move in the simulator
    rest                all joints back to 0 (the rest pose)
    export <name>       write scripts/motion/moves/<name>.json for the real robot
    quit

Contract with the real robot: frame 1 is auto-captured at rest — author your
move FROM rest, and ideally end at rest. On hardware, angles are applied as
deltas from frame 1 anchored to the robot's recorded stance.
"""
import json
import time
from pathlib import Path

from pypot.creatures import PoppyTorso

MOVES_DIR = Path(__file__).resolve().parent.parent / "scripts" / "motion" / "moves"
JOINTS = ["abs_z", "bust_y", "bust_x", "head_z", "head_y",
          "l_shoulder_y", "l_shoulder_x", "l_arm_z", "l_elbow_y",
          "r_shoulder_y", "r_shoulder_x", "r_arm_z", "r_elbow_y"]


def pose_of(poppy):
    return {j: round(getattr(poppy, j).present_position, 1) for j in JOINTS}


def goto(poppy, target, duration):
    start = pose_of(poppy)
    steps = max(int(duration / 0.05), 1)
    for s in range(1, steps + 1):
        u = s / steps
        for j, v in target.items():
            getattr(poppy, j).goal_position = start[j] + (v - start[j]) * u
        time.sleep(duration / steps)


def main():
    print("connecting to CoppeliaSim...")
    poppy = PoppyTorso(simulator="vrep")
    print("connected. moving sim to rest pose (all joints 0)")
    for j in JOINTS:
        getattr(poppy, j).goal_position = 0
    time.sleep(2)
    frames = [{"positions": pose_of(poppy), "duration": 2.0}]
    print("frame 1 (rest) captured automatically. type commands ('quit' to exit):")

    while True:
        try:
            line = input("kf> ").strip()
        except (EOFError, KeyboardInterrupt):
            line = "quit"
        if not line:
            continue
        cmd, *rest = line.split()

        if cmd == "quit":
            poppy.close()
            print("bye (nothing auto-saved — use export before quit)")
            return
        elif cmd == "get":
            print(json.dumps(pose_of(poppy), indent=1))
        elif cmd == "rest":
            goto(poppy, {j: 0 for j in JOINTS}, 1.5)
            print("at rest")
        elif cmd == "capture":
            dur = float(rest[0]) if rest else 1.5
            frames.append({"positions": pose_of(poppy), "duration": dur})
            print(f"frame {len(frames)} captured ({dur} s to reach it)")
        elif cmd == "list":
            for n, f in enumerate(frames, 1):
                nz = {k: v for k, v in f["positions"].items() if abs(v) > 2}
                print(f"  {n}: {f['duration']}s  {nz if nz else 'rest'}")
        elif cmd == "undo":
            if len(frames) > 1:
                frames.pop()
                print(f"{len(frames)} frames left")
            else:
                print("frame 1 (rest) stays")
        elif cmd == "play":
            print("previewing in sim...")
            goto(poppy, frames[0]["positions"], 1.0)
            for f in frames[1:]:
                goto(poppy, f["positions"], f["duration"])
            print("preview done")
        elif cmd == "export":
            name = rest[0] if rest else "move"
            MOVES_DIR.mkdir(exist_ok=True)
            out = MOVES_DIR / f"{name}.json"
            out.write_text(json.dumps({"name": name, "frames": frames}, indent=2))
            print(f"exported {len(frames)} frames -> {out}")
        elif cmd in JOINTS:
            try:
                getattr(poppy, cmd).goal_position = float(rest[0])
            except (IndexError, ValueError):
                print("usage: <joint> <degrees>")
        else:
            print(f"unknown command '{cmd}' (try: get/capture/list/undo/play/rest/export/quit)")


if __name__ == "__main__":
    main()
