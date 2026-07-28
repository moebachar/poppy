# Poppy Torso — daily runbook

Every command below runs from a terminal on this laptop. `python` means the project's
Python: `C:\Users\mbachar\poppy\.venv\Scripts\python.exe` (VS Code terminals in this
folder usually pick it up automatically — if a command says "no module named pypot",
use the full path). The robot's port is **COM7**.

**Emergency stop, always:** pull the 12 V plug from the wall. Software stop: `Ctrl+C`
in the terminal running a script — every script releases the motors (goes soft) on exit.

## 1. Power up + health check

1. Plug the 12 V brick into the wall (green light on the injector board).
2. Plug the USB2AX into the laptop.
3. Scan (read-only, moves nothing):

   ```
   python scripts\diagnostics\scan_bus.py --port COM7
   ```

   Good = `found 12 motor(s)`, only `54 (r_elbow_y)` missing (dead, swap pending),
   temperatures under ~40 °C.

## 2. Make it stand still (from any messy position)

```
python scripts\motion\03_stand_still.py --port COM7
```

Freezes where it is, then travels slowly to the recorded `stand` pose and holds
30 min (change with `--minutes 60`). `--freeze-only` = stiffen in place, no travel.
`Ctrl+C` to release early.

## 3. Record a move by hand (no sim — the easy way)

```
python scripts\motion\07_record_replay.py --port COM7 record hello_wave
```

Robot goes fully soft (hold him!), 3 s countdown, then move his limbs like a
puppet — everything is recorded at 20 Hz. Press **Enter** to stop and save.
Replay anytime (whole body stiffens, returns to the move's start, then plays):

```
python scripts\motion\07_record_replay.py --port COM7 replay hello_wave
python scripts\motion\07_record_replay.py --port COM7 list
```

Raw motor space — no sim, no calibration involved; what you sculpt is what replays.

## 3-alt. Author a move in the simulator (no hardware touched)

1. Launch CoppeliaSim — **exactly one instance**, and it must be started with this
   command (a plain double-click won't open the robot port):

   ```
   & "C:\Program Files\CoppeliaRobotics\CoppeliaSimEdu\coppeliaSim.exe" -gREMOTEAPISERVERSERVICE_19997_FALSE_TRUE "C:\Users\mbachar\poppy\vendor\poppy-torso\software\poppy_torso\vrep-scene\poppy_torso.ttt"
   ```

2. In a second terminal, start the keyframer:

   ```
   python sim\keyframer.py
   ```

3. Type commands at the `kf>` prompt:

   | command | what it does |
   |---|---|
   | `l_shoulder_x 40` | move that sim joint to 40° (any joint from the cheatsheet) |
   | `get` | print all current joint angles |
   | `capture` | save the current sim pose as the next keyframe (`capture 2.5` = 2.5 s to reach it) |
   | `list` / `undo` | show frames / delete the last one |
   | `play` | preview the whole move in the sim |
   | `rest` | all joints back to 0 |
   | `export wave2` | write `scripts\motion\moves\wave2.json` |
   | `quit` | exit (export first — nothing is auto-saved) |

   Joint names, directions and safe ranges: **`hardware/JOINT_CHEATSHEET.md`**.
   Rules: start the move from rest (frame 1 is captured there automatically),
   ideally end at rest, stay inside the cheatsheet ranges.

## 4. Execute a move on the real robot

Stand clear of the arms, then:

```
python scripts\motion\06_execute_move.py --port COM7 --move wave2
```

It stands still, travels to the move's first frame, plays the move, then holds
30 min (`--hold-minutes 5` to shorten). It clamps to joint limits, skips the dead
motor, watches temperature, and refuses moves that reach >120° from stance.
`Ctrl+C` at any time = stop and go soft.

## 5. Poses (freeze-frame, no motion file)

```
python scripts\motion\04_pose.py --port COM7 save cool_pose    # record current physical pose
python scripts\motion\04_pose.py --port COM7 goto cool_pose    # go there and hold
python scripts\motion\04_pose.py --port COM7 release           # everything soft
```

To re-record the stance that anchors all moves: sculpt the robot by hand, then
`save stand`.

## 6. Shutdown

1. `Ctrl+C` any running script (motors go soft), or run the `release` command above.
2. Pull the 12 V brick from the wall.
3. Close CoppeliaSim (don't save the scene if it asks).
4. Unplug the USB2AX.

## Known quirks (this 2013 unit)

- `r_elbow_y` (motor 54) is dead — sim moves may use it; hardware skips it.
- Absolute poses don't match the sim exactly yet (old assembly offsets) — moves are
  applied as *changes* from the move's first frame, anchored on the `stand` pose.
  Zero calibration will fix this properly.
- If CoppeliaSim says `failed starting a remote API server on port 19997`: another
  CoppeliaSim instance is running — close ALL of them and relaunch with the command above.
