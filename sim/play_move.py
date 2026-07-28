#!/usr/bin/env python
"""Replay an exported move file on the SIMULATED Poppy (CoppeliaSim must be open).

    python sim\play_move.py wave

Shows exactly what the execute script is asked to do. If it looks wrong here,
the move file is bad; if it looks right here but wrong on hardware, the
hardware sign table (06_execute_move.py MOTORS) is bad.
"""
import json
import sys
import time
from pathlib import Path

from pypot.creatures import PoppyTorso

from keyframer import JOINTS, goto

MOVES = Path(__file__).resolve().parent.parent / "scripts" / "motion" / "moves"


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "wave"
    p = Path(name)
    if not p.exists():
        p = MOVES / (name if name.endswith(".json") else name + ".json")
    frames = json.loads(p.read_text())["frames"]
    print(f"replaying {p.name} in sim: {len(frames)} frames")
    poppy = PoppyTorso(simulator="vrep")
    goto(poppy, {j: 0 for j in JOINTS}, 1.5)  # rest = hardware stance anchor
    time.sleep(0.5)
    goto(poppy, {j: frames[0]["positions"].get(j, 0) for j in JOINTS}, 1.0)
    for f in frames[1:]:
        goto(poppy, f["positions"], f["duration"])
    time.sleep(0.5)
    goto(poppy, {j: 0 for j in JOINTS}, 1.5)
    poppy.close()
    print("done")


if __name__ == "__main__":
    main()
