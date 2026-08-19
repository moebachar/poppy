#!/usr/bin/env python
"""Face tracking: Poppy's head follows the person in front of the camera.

    python 08_face_track.py --port /dev/ttyACM0
    python 08_face_track.py --port /dev/ttyACM0 --pan-sign -1   # if head turns away

The whole body settles into the stand pose and holds rigid; only the head
motors (36 pan, 37 tilt) chase the largest face the camera sees. No face for
a few seconds -> head eases back to center. Ctrl+C or --minutes = release.

The camera must be attached to the HEAD, looking where the face points —
tracking is closed-loop: turn toward the face until it is centered.
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import pypot.dynamixel

from dxl_multiturn import SEAM_IDS, present_deg, goto_deg, freeze, rebase

TEMP_HARD = 52
POSES = Path(__file__).parent / "poses"


def settle_rigid(dxl, present, pose_name):
    """Freeze everything at 100%, then travel slowly into the named pose."""
    current = dict(zip(present, dxl.get_present_position(present)))
    for i in present:
        dxl.set_moving_speed({i: 20})
        dxl.set_torque_limit({i: 100})
        if i in SEAM_IDS:
            freeze(dxl, i)
            current[i] = present_deg(dxl, i)
        else:
            dxl.set_goal_position({i: current[i]})
            dxl.enable_torque((i,))
    time.sleep(0.3)
    if pose_name == "none":
        return current
    target = {int(k): v for k, v in
              json.loads((POSES / f"{pose_name}.json").read_text())["positions"].items()}
    target = {i: v for i, v in target.items() if i in present}
    for i in target:
        if i in SEAM_IDS:
            target[i] = rebase(target[i], current[i])
    worst = max(abs(target[i] - current[i]) for i in target)
    if worst > 100:
        raise SystemExit(f"too far from pose '{pose_name}' ({worst:.0f} deg) — "
                         f"run 03_stand_still.py first")
    print(f"settling into '{pose_name}'...", flush=True)
    for i in target:
        if i in SEAM_IDS:
            goto_deg(dxl, i, target[i])
        else:
            dxl.set_goal_position({i: target[i]})
    time.sleep(worst / 20 + 0.8)
    current.update(target)
    return current


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--pose", default="stand")
    ap.add_argument("--pan-id", type=int, default=36)
    ap.add_argument("--tilt-id", type=int, default=37)
    ap.add_argument("--pan-sign", type=float, default=1.0)
    ap.add_argument("--tilt-sign", type=float, default=1.0)
    ap.add_argument("--gain", type=float, default=14.0,
                    help="deg of correction for a face at the image edge")
    ap.add_argument("--step-max", type=float, default=8.0)
    ap.add_argument("--max-pan", type=float, default=45.0)
    ap.add_argument("--max-tilt", type=float, default=20.0)
    ap.add_argument("--deadband", type=float, default=0.12,
                    help="normalized center zone where the head stays put")
    args = ap.parse_args()

    local = Path(__file__).parent / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(
        str(local) if local.exists()
        else cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        raise SystemExit(f"haar cascade not found (looked for {local})")

    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    ok = False
    for _ in range(10):
        ok, _f = cap.read()
    if not ok:
        raise SystemExit("camera gives no frames (check USB / uvcvideo quirk)")

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        present = [i for i in dxl.scan(list(range(60))) if i < 250]
        for hid in (args.pan_id, args.tilt_id):
            if hid not in present:
                raise SystemExit(f"head motor {hid} not on the bus ({present})")
        pose = settle_rigid(dxl, present, args.pose)
        pan0, tilt0 = pose[args.pan_id], pose[args.tilt_id]
        pan, tilt = pan0, tilt0
        dxl.set_moving_speed({args.pan_id: 80})
        dxl.set_moving_speed({args.tilt_id: 80})
        print(f"TRACKING for {args.minutes:g} min — stand in front of the camera. "
              f"Ctrl+C to stop.", flush=True)
        t_end = time.time() + args.minutes * 60
        last_face = last_temp = time.time()
        try:
            while time.time() < t_end:
                for _ in range(2):        # drop stale buffered frames
                    cap.grab()
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
                h, w = frame.shape[:2]
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.2, 4, minSize=(36, 36))
                if len(faces):
                    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                    ex = (x + fw / 2 - w / 2) / (w / 2)    # -1 left .. +1 right
                    ey = (y + fh / 2 - h / 2) / (h / 2)    # -1 top  .. +1 bottom
                    if abs(ex) > args.deadband:
                        step = max(-args.step_max, min(args.step_max,
                                   args.pan_sign * args.gain * ex))
                        pan = max(pan0 - args.max_pan,
                                  min(pan0 + args.max_pan, pan + step))
                    if abs(ey) > args.deadband:
                        step = max(-args.step_max, min(args.step_max,
                                   args.tilt_sign * args.gain * ey))
                        tilt = max(tilt0 - args.max_tilt,
                                   min(tilt0 + args.max_tilt, tilt + step))
                    dxl.set_goal_position({args.pan_id: pan})
                    dxl.set_goal_position({args.tilt_id: tilt})
                    last_face = time.time()
                elif time.time() - last_face > 4 and (pan, tilt) != (pan0, tilt0):
                    pan += max(-2.0, min(2.0, pan0 - pan))     # ease home
                    tilt += max(-2.0, min(2.0, tilt0 - tilt))
                    dxl.set_goal_position({args.pan_id: pan})
                    dxl.set_goal_position({args.tilt_id: tilt})
                if time.time() - last_temp > 3:
                    last_temp = time.time()
                    if max(dxl.get_present_temperature(present)) >= TEMP_HARD:
                        print("overheat -> releasing", flush=True)
                        return
        except KeyboardInterrupt:
            pass
        finally:
            cap.release()
            dxl.disable_torque(present)
            print("released (compliant)", flush=True)


if __name__ == "__main__":
    main()
